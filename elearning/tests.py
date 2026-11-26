import json
import random
import re
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, current_app
)
from elearning.models import (
    db, Course, Slide, MCQ, Enrolment, TestAttempt, PaymentOrder
)
from elearning.auth import login_required, get_current_user
from elearning.utils import log_audit_event, send_transactional_email

tests_bp = Blueprint('tests', __name__, url_prefix='/elearning')

def check_and_sync_test_eligibility(enrolment, course):
    """
    Ensures enrolment state accurately reflects presentation completion and attempt cycles.
    Unlocks fresh attempts when a learner completes the initial presentation or a review cycle.
    """
    total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
    if total_slides == 0:
        return
        
    is_at_final_slide = (
        enrolment.current_slide_number >= total_slides or
        enrolment.highest_slide_completed >= total_slides - 1 or
        enrolment.highest_slide_completed >= total_slides
    )
    
    if is_at_final_slide:
        enrolment.highest_slide_completed = total_slides
        enrolment.slides_completed = True
        
        # If learner had exhausted all 3 attempts and reviewed the presentation:
        if enrolment.attempts_used_in_current_cycle >= 3:
            enrolment.presentation_completions_count = (enrolment.presentation_completions_count or 1) + 1
            enrolment.attempts_used_in_current_cycle = 0
            log_audit_event(
                enrolment.user_id,
                "PRESENTATION_CYCLE_UNLOCKED",
                "Course",
                course.id,
                f"Presentation review cycle {enrolment.presentation_completions_count} completed. 3 fresh attempts unlocked."
            )
        elif enrolment.presentation_completions_count == 0:
            enrolment.presentation_completions_count = 1
            enrolment.attempts_used_in_current_cycle = 0
            if not enrolment.completed_at:
                enrolment.completed_at = datetime.now(timezone.utc)
            log_audit_event(
                enrolment.user_id,
                "PRESENTATION_COMPLETED",
                "Course",
                course.id,
                "Initial presentation completed"
            )
        db.session.commit()


@tests_bp.route('/course/<slug>/test')
@login_required
def test_start(slug):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
    
    if not enrolment:
        flash("You are not enrolled in this course.", "warning")
        return redirect(url_for('elearning.course_detail', slug=course.slug))
        
    check_and_sync_test_eligibility(enrolment, course)
    
    total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
    if not enrolment.slides_completed or enrolment.highest_slide_completed < total_slides:
        flash("You must complete all course slides and practice questions before taking the final test.", "warning")
        return redirect(url_for('elearning.slide_player', slug=course.slug))
        
    # Check if already passed
    if enrolment.has_passed_test:
        flash("You have already passed this course examination!", "info")
        return redirect(url_for('tests.test_result_summary', slug=course.slug))
        
    # Check attempts used in current cycle
    if enrolment.attempts_used_in_current_cycle >= 3:
        flash("You have exhausted all 3 attempts for this presentation cycle. You must review the course presentation again before unlocking another 3 attempts.", "warning")
        return render_template('elearning/test_exhausted.html', course=course, enrolment=enrolment)
        
    # When clicking "Take final certified examination", open the examination directly in one click!
    return redirect(url_for('tests.take_test', slug=course.slug))


@tests_bp.route('/course/<slug>/test/take', methods=['GET', 'POST'])
@login_required
def take_test(slug):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
    
    if not enrolment:
        flash("You are not enrolled in this course.", "warning")
        return redirect(url_for('elearning.course_detail', slug=course.slug))
        
    check_and_sync_test_eligibility(enrolment, course)
    
    if enrolment.has_passed_test:
        flash("You have already passed this examination.", "info")
        return redirect(url_for('tests.test_result_summary', slug=course.slug))
        
    total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
    if not enrolment.slides_completed or enrolment.highest_slide_completed < total_slides:
        flash("You must complete all course slides and practice questions before taking the final test.", "warning")
        return redirect(url_for('elearning.slide_player', slug=course.slug))
        
    if enrolment.attempts_used_in_current_cycle >= 3:
        flash("You have exhausted all 3 attempts for this presentation cycle. You must review the course presentation again before unlocking another 3 attempts.", "warning")
        return render_template('elearning/test_exhausted.html', course=course, enrolment=enrolment)

    session_q_ids_key = f"test_q_ids_{enrolment.id}_{enrolment.attempts_used_in_current_cycle + 1}"
    
    if request.method == 'GET':
        # Rule: Exactly 20 questions for Final Assessment:
        # Part A contributes 40% (exactly 8 questions)
        # Part B contributes 60% (exactly 12 questions)
        # Sourced dynamically with minimum 75% novel questions compared to previous attempt
        part_a_pool = MCQ.query.filter_by(course_id=course.id, type='final_test', part='A', is_active=True).all()
        part_b_pool = MCQ.query.filter_by(course_id=course.id, type='final_test', part='B', is_active=True).all()
        
        # Identify questions used in the previous attempt (if any) to ensure >= 75% difference
        latest_attempt = TestAttempt.query.filter_by(enrolment_id=enrolment.id).order_by(TestAttempt.id.desc()).first()
        prev_q_ids = set()
        if latest_attempt:
            for q_item in latest_attempt.get_questions_data():
                if isinstance(q_item, dict) and 'id' in q_item:
                    prev_q_ids.add(q_item['id'])
                    
        part_a_novel = [q for q in part_a_pool if q.id not in prev_q_ids]
        part_a_used = [q for q in part_a_pool if q.id in prev_q_ids]
        part_b_novel = [q for q in part_b_pool if q.id not in prev_q_ids]
        part_b_used = [q for q in part_b_pool if q.id in prev_q_ids]
        
        # Requirement: Minimum 75% of questions (at least 15 / 20) must be different from previous attempt.
        # Select Part A (8 questions): at least 6 novel if pool allows
        target_novel_a = min(8, max(6, len(part_a_novel))) if len(part_a_novel) >= 6 else len(part_a_novel)
        selected_a = random.sample(part_a_novel, min(target_novel_a, len(part_a_novel)))
        if len(selected_a) < 8:
            needed_a = 8 - len(selected_a)
            selected_a += random.sample(part_a_used, min(needed_a, len(part_a_used)))
            
        # Select Part B (12 questions): at least 9 novel if pool allows
        target_novel_b = min(12, max(9, len(part_b_novel))) if len(part_b_novel) >= 9 else len(part_b_novel)
        selected_b = random.sample(part_b_novel, min(target_novel_b, len(part_b_novel)))
        if len(selected_b) < 12:
            needed_b = 12 - len(selected_b)
            selected_b += random.sample(part_b_used, min(needed_b, len(part_b_used)))
            
        all_selected = selected_a + selected_b
        # Fallback if total selected is under 20
        if len(all_selected) < 20:
            remaining_pool = [q for q in (part_a_pool + part_b_pool) if q not in all_selected]
            needed = 20 - len(all_selected)
            if remaining_pool and needed > 0:
                all_selected += random.sample(remaining_pool, min(needed, len(remaining_pool)))
            
        # Dynamic sequence: randomized on every test attempt
        random.shuffle(all_selected)
        
        # Store only compact question IDs in session
        q_ids = [q.id for q in all_selected]
        session[session_q_ids_key] = q_ids
        session[f"{session_q_ids_key}_start"] = datetime.now(timezone.utc).isoformat()
        
        # Build sequential question list (1 to 20) with no Part A/B references
        test_questions = []
        for idx, q in enumerate(all_selected, start=1):
            clean_question = re.sub(r'\bPART\s+[AB]\b', '', q.question_text, flags=re.IGNORECASE).strip()
            clean_question = re.sub(r'^(FINAL\s+ASSESSMENT\s*\|\s*Question\s*\d+\s*)+', '', clean_question, flags=re.IGNORECASE).strip()
            clean_explanation = re.sub(r'\bPART\s+[AB]\b', '', q.explanation or '', flags=re.IGNORECASE).strip()

            options = [
                ('A', q.option_a),
                ('B', q.option_b),
                ('C', q.option_c),
                ('D', q.option_d)
            ]
            test_questions.append({
                'number': idx,
                'id': q.id,
                'question_text': clean_question or q.question_text,
                'options': options
            })
            
        q_ids_csv = ",".join(str(qid) for qid in q_ids)
        return render_template(
            'elearning/test.html',
            course=course,
            enrolment=enrolment,
            questions=test_questions,
            total_questions=len(test_questions),
            attempt_num=enrolment.attempts_used_in_current_cycle + 1,
            q_ids_csv=q_ids_csv
        )
        
    elif request.method == 'POST':
        q_ids_raw = request.form.get('question_ids_list')
        if q_ids_raw:
            q_ids = [int(x.strip()) for x in q_ids_raw.split(',') if x.strip().isdigit()]
        else:
            q_ids = session.get(session_q_ids_key)

        expected_total = current_app.config.get('TOTAL_TEST_QUESTIONS', 20)
        
        # Security Validation 1: Require exact 20 questions to prevent single-question bypass
        if not q_ids or len(q_ids) != expected_total:
            flash("Invalid examination submission. Exactly 20 questions are required.", "danger")
            return redirect(url_for('tests.take_test', slug=course.slug))

        # Security Validation 2: Ensure all questions belong to this course and are valid final_test questions
        mcq_objs = MCQ.query.filter(MCQ.id.in_(q_ids), MCQ.course_id == course.id, MCQ.type == 'final_test').all()
        if len(mcq_objs) != expected_total:
            flash("Invalid examination questions submitted. Submission rejected.", "danger")
            return redirect(url_for('tests.take_test', slug=course.slug))
            
        # Security Validation 3: Verify questions match active session question set if set in session
        session_q_ids = session.get(session_q_ids_key)
        if session_q_ids and set(q_ids) != set(session_q_ids):
            flash("Examination questions mismatch with active session. Submission rejected.", "danger")
            return redirect(url_for('tests.take_test', slug=course.slug))

        mcq_dict = {q.id: q for q in mcq_objs}
        
        correct_count = 0
        total_q = len(q_ids)
        snapshot = []
        
        for idx, q_id in enumerate(q_ids, start=1):
            q_obj = mcq_dict.get(q_id)
            if not q_obj:
                continue
                
            user_choice = (request.form.get(f"q_{q_id}") or request.form.get(f"q_text_{q_id}") or '').strip().upper()
            is_correct = (user_choice == q_obj.correct_option)
            if is_correct:
                correct_count += 1
                
            clean_q = re.sub(r'\bPART\s+[AB]\b', '', q_obj.question_text, flags=re.IGNORECASE).strip()
            clean_q = re.sub(r'^(FINAL\s+ASSESSMENT\s*\|\s*Question\s*\d+\s*)+', '', clean_q, flags=re.IGNORECASE).strip()
            clean_exp = re.sub(r'\bPART\s+[AB]\b', '', q_obj.explanation or '', flags=re.IGNORECASE).strip()

            opt_map = {
                'A': q_obj.option_a,
                'B': q_obj.option_b,
                'C': q_obj.option_c,
                'D': q_obj.option_d,
            }

            snapshot.append({
                'id': q_id,
                'number': idx,
                'question_text': clean_q or q_obj.question_text,
                'user_choice': user_choice,
                'user_choice_text': opt_map.get(user_choice, 'No response'),
                'is_correct': is_correct,
                'correct_option': q_obj.correct_option,
                'correct_option_text': opt_map.get(q_obj.correct_option, ''),
                'explanation': clean_exp
            })
            
        percentage = round((correct_count / total_q) * 100.0, 1) if total_q > 0 else 0.0
        passed = (percentage >= 80.0)  # Requires at least 16/20
        
        enrolment.attempts_used_in_current_cycle += 1
        attempt_record = TestAttempt(
            enrolment_id=enrolment.id,
            attempt_number=enrolment.attempts_used_in_current_cycle,
            presentation_cycle=enrolment.presentation_completions_count,
            started_at=datetime.fromisoformat(session.get(f"{session_q_ids_key}_start", datetime.now(timezone.utc).isoformat())),
            submitted_at=datetime.now(timezone.utc),
            score=correct_count,
            percentage=percentage,
            passed=passed,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else '',
            questions_data=json.dumps(snapshot)
        )
        db.session.add(attempt_record)
        db.session.commit()
        
        # Clear session snapshot
        session.pop(session_q_ids_key, None)
        session.pop(f"{session_q_ids_key}_start", None)
        
        log_audit_event(
            user.id,
            "TEST_ATTEMPT_SUBMITTED",
            "TestAttempt",
            attempt_record.id,
            f"Score: {correct_count}/{total_q} ({percentage}%), Passed: {passed}"
        )
        
        # Send transactional email
        if passed:
            subj = f"Congratulations! You passed the {course.title} Examination"
            body = f"""
            <h3>Congratulations, {user.first_name}!</h3>
            <p>You have successfully passed the final certification examination for <strong>{course.title}</strong>.</p>
            <p><strong>Your Score:</strong> {correct_count}/{total_q} ({percentage}%) - <strong>PASSED</strong></p>
            <p>Passing requirement: 80% (16/20).</p>
            <p>Please log in to your dashboard to review next steps and manage your certificate issuance.</p>
            """
        else:
            remaining = max(0, 3 - enrolment.attempts_used_in_current_cycle)
            subj = f"Examination Result: {course.title} - Test Not Passed"
            body = f"""
            <h3>Hello {user.first_name},</h3>
            <p>Here is your result for the <strong>{course.title}</strong> final examination:</p>
            <p><strong>Your Score:</strong> {correct_count}/{total_q} ({percentage}%) - <strong>TEST NOT PASSED</strong></p>
            <p><strong>Result Notice:</strong> You did not clear the required mandate of correct responses (minimum 80% / 16 out of 20 correct) to pass the test and hence need to appear for the test again.</p>
            <p><strong>Remaining attempts in this cycle:</strong> {remaining}</p>
            <p>You may appear for the test again or review the course slides anytime from your learner dashboard.</p>
            """
        send_transactional_email(user.email, subj, body)
        
        return redirect(url_for('tests.test_result_view', slug=course.slug, attempt_id=attempt_record.id))


def get_attempt_incorrect_review(attempt):
    """Extracts all incorrectly answered questions from attempt snapshot with full question and answer details."""
    if not attempt:
        return []
    raw_questions = attempt.get_questions_data()
    incorrect_list = []
    for item in raw_questions:
        if not item.get('is_correct'):
            # Enrich from database if options are missing from legacy snapshots
            if not item.get('correct_option_text') and item.get('id'):
                mcq_rec = db.session.get(MCQ, item.get('id'))
                if mcq_rec:
                    opt_map = {'A': mcq_rec.option_a, 'B': mcq_rec.option_b, 'C': mcq_rec.option_c, 'D': mcq_rec.option_d}
                    item['correct_option'] = mcq_rec.correct_option
                    item['correct_option_text'] = opt_map.get(mcq_rec.correct_option, '')
                    item['user_choice_text'] = opt_map.get(item.get('user_choice'), 'No response')
                    item['explanation'] = mcq_rec.explanation or ''
            incorrect_list.append(item)
    return incorrect_list


@tests_bp.route('/course/<slug>/test/result/<int:attempt_id>')
@login_required
def test_result_view(slug, attempt_id):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first_or_404()
    attempt = TestAttempt.query.filter_by(id=attempt_id, enrolment_id=enrolment.id).first_or_404()
    
    needs_delivery_address = (
        enrolment.certificate_option == 'paid' and
        attempt.passed and
        not user.has_delivery_address
    )
    
    payment_order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).order_by(PaymentOrder.id.desc()).first()
    incorrect_questions = get_attempt_incorrect_review(attempt)
    
    return render_template(
        'elearning/test_result.html',
        course=course,
        enrolment=enrolment,
        attempt=attempt,
        needs_delivery_address=needs_delivery_address,
        payment_order=payment_order,
        remaining_attempts=max(0, 3 - enrolment.attempts_used_in_current_cycle),
        incorrect_questions=incorrect_questions,
        total_incorrect=len(incorrect_questions)
    )


@tests_bp.route('/course/<slug>/test/summary')
@login_required
def test_result_summary(slug):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first_or_404()
    latest_passed = enrolment.latest_passed_attempt
    
    if not latest_passed:
        return redirect(url_for('tests.test_start', slug=course.slug))
        
    payment_order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).order_by(PaymentOrder.id.desc()).first()
    incorrect_questions = get_attempt_incorrect_review(latest_passed)
    return render_template(
        'elearning/test_result.html',
        course=course,
        enrolment=enrolment,
        attempt=latest_passed,
        needs_delivery_address=(enrolment.certificate_option == 'paid' and not user.has_delivery_address),
        payment_order=payment_order,
        remaining_attempts=max(0, 3 - enrolment.attempts_used_in_current_cycle),
        incorrect_questions=incorrect_questions,
        total_incorrect=len(incorrect_questions)
    )


@tests_bp.route('/course/<slug>/re-review', methods=['POST'])
@login_required
def restart_presentation(slug):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first_or_404()
    
    enrolment.highest_slide_completed = 0
    enrolment.current_slide_number = 1
    enrolment.slides_completed = False
    db.session.commit()
    
    log_audit_event(user.id, "PRESENTATION_RESTARTED", "Enrolment", enrolment.id, "Learner restarted presentation after exhausting attempts")
    flash("Course presentation restarted. Complete the slides to unlock 3 new examination attempts.", "info")
    return redirect(url_for('elearning.slide_player', slug=course.slug, slide_num=1))
