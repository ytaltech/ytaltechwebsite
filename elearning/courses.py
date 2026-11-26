import time
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from elearning.models import (
    db, Course, Slide, MCQ, Enrolment, SlideViewLog,
    PracticeMCQResponse, TestAttempt, PaymentOrder
)
from elearning.auth import login_required, get_current_user
from elearning.utils import log_audit_event, generate_order_reference

courses_bp = Blueprint('elearning', __name__, url_prefix='/elearning')

@courses_bp.route('/')
@courses_bp.route('/courses')
def courses_list():
    courses = Course.query.filter_by(is_active=True).all()
    user = get_current_user()
    
    # Map user enrolments
    enrolment_map = {}
    if user:
        for enr in user.enrolments:
            enrolment_map[enr.course_id] = enr
            
    return render_template('elearning/courses.html', courses=courses, user=user, enrolment_map=enrolment_map)


@courses_bp.route('/course/<slug>')
@login_required
def course_detail(slug):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
    
    # If already enrolled, can go to player or view options
    return render_template('elearning/course_detail.html', course=course, user=user, enrolment=enrolment)


@courses_bp.route('/course/<slug>/enrol', methods=['POST'])
@login_required
def enrol_course(slug):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    
    cert_option = request.form.get('certificate_option', 'paid')
    if cert_option not in ['paid', 'free']:
        cert_option = 'paid'
        
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
    if not enrolment:
        enrolment = Enrolment(
            user_id=user.id,
            course_id=course.id,
            certificate_option=cert_option,
            current_slide_number=1,
            highest_slide_completed=0,
            slides_completed=False,
            presentation_completions_count=0,
            attempts_used_in_current_cycle=0,
            enrolled_at=datetime.now(timezone.utc)
        )
        db.session.add(enrolment)
        db.session.commit()
        
        # If paid option selected, create a pending payment order right away if none exists
        if cert_option == 'paid':
            existing_order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
            if not existing_order:
                order_ref = generate_order_reference()
                order = PaymentOrder(
                    order_reference=order_ref,
                    enrolment_id=enrolment.id,
                    user_id=user.id,
                    course_id=course.id,
                    expected_amount=course.total_price_inr,
                    currency='INR',
                    gst_amount=course.gst_amount_inr,
                    status='pending_submission'
                )
                db.session.add(order)
                db.session.commit()
            elif existing_order.status == 'pending_submission':
                existing_order.expected_amount = course.total_price_inr
                existing_order.gst_amount = course.gst_amount_inr
                db.session.commit()
                
        log_audit_event(user.id, "ENROLLED_COURSE", "Course", course.id, f"Enrolled with option: {cert_option}")
        flash(f"You have successfully enrolled in {course.title} ({cert_option.upper()} option).", "success")
    else:
        # Check 1-month upgrade window expiration if upgrading from free after passing test
        if enrolment.certificate_option == 'free' and cert_option == 'paid' and enrolment.has_passed_test:
            if enrolment.is_free_upgrade_expired:
                flash("The 1-month window to pay and download a certificate has expired. Please revise the course and retake the examination.", "danger")
                return redirect(url_for('tests.test_result_summary', slug=course.slug))

        # Update option if changed
        if enrolment.certificate_option != cert_option:
            enrolment.certificate_option = cert_option
            if cert_option == 'paid':
                existing_order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
                if not existing_order:
                    order_ref = generate_order_reference()
                    order = PaymentOrder(
                        order_reference=order_ref,
                        enrolment_id=enrolment.id,
                        user_id=user.id,
                        course_id=course.id,
                        expected_amount=course.total_price_inr,
                        currency='INR',
                        gst_amount=course.gst_amount_inr,
                        status='pending_submission'
                    )
                    db.session.add(order)
                elif existing_order.status == 'pending_submission':
                    existing_order.expected_amount = course.total_price_inr
                    existing_order.gst_amount = course.gst_amount_inr
            db.session.commit()
            flash("Your certificate preference has been updated.", "info")
            
    # If learner has completed course or passed test, directly move to certificate issuance and verification status screen
    if enrolment.has_passed_test or enrolment.slides_completed:
        return redirect(url_for('tests.test_result_summary', slug=course.slug))

    # Otherwise redirect to slide player to continue learning
    return redirect(url_for('elearning.slide_player', slug=course.slug))


@courses_bp.route('/course/<slug>/player')
@courses_bp.route('/course/<slug>/player/<int:slide_num>')
@login_required
def slide_player(slug, slide_num=None):
    course = Course.query.filter_by(slug=slug, is_active=True).first_or_404()
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
    
    if not enrolment:
        flash("Please enrol in this course to start learning.", "warning")
        return redirect(url_for('elearning.course_detail', slug=course.slug))
        
    total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
    if total_slides == 0:
        flash("This course currently has no active slides.", "info")
        return redirect(url_for('elearning.courses_list'))
        
    # If no slide_num provided, resume from last reached slide
    if slide_num is None:
        slide_num = min(total_slides, max(1, enrolment.current_slide_number))
        
    is_revision = bool(enrolment.slides_completed)

    # Prevent skipping forward beyond completed slides + 1 (unless in course revision mode)
    if not is_revision:
        max_allowed = enrolment.highest_slide_completed + 1
        if slide_num > max_allowed:
            flash(f"You must complete slide {enrolment.highest_slide_completed + 1} before skipping ahead.", "warning")
            slide_num = min(max_allowed, total_slides)
            return redirect(url_for('elearning.slide_player', slug=slug, slide_num=slide_num))
        
    slide = Slide.query.filter_by(course_id=course.id, slide_number=slide_num, is_active=True).first_or_404()
    
    # Update current slide in enrolment
    enrolment.current_slide_number = slide_num
    db.session.commit()
    
    # Store slide start timestamp in session for server-side dwell time verification
    session_key = f"slide_start_{enrolment.id}_{slide_num}"
    if session_key not in session:
        session[session_key] = time.time()
        
    # Fetch MCQs attached to this slide (both practice in modules and final test MCQs towards the end)
    practice_mcqs = MCQ.query.filter_by(course_id=course.id, slide_id=slide.id, is_active=True).all()
    has_practice = len(practice_mcqs) > 0
    
    # Check if questions on this slide have already been answered by this learner and retrieve vetted response data
    previous_mcq_responses = {}
    answered_practice_ids = set()
    if practice_mcqs:
        mcq_ids = [q.id for q in practice_mcqs]
        responses = PracticeMCQResponse.query.filter(
            PracticeMCQResponse.enrolment_id == enrolment.id,
            PracticeMCQResponse.mcq_id.in_(mcq_ids)
        ).all()
        for r in responses:
            mcq_obj = next((q for q in practice_mcqs if q.id == r.mcq_id), None)
            previous_mcq_responses[str(r.mcq_id)] = {
                'selected_option': r.selected_option,
                'is_correct': r.is_correct,
                'correct_option': mcq_obj.correct_option if mcq_obj else '',
                'explanation': mcq_obj.explanation if mcq_obj else ''
            }
            answered_practice_ids.add(r.mcq_id)
        
    all_practice_answered = all(q.id in answered_practice_ids for q in practice_mcqs)
    practice_answered = all_practice_answered
    is_completed_previously = (slide_num <= enrolment.highest_slide_completed) or is_revision
    
    # Log slide view event
    log_entry = SlideViewLog(
        enrolment_id=enrolment.id,
        slide_id=slide.id,
        slide_number=slide_num,
        started_at=datetime.now(timezone.utc),
        ip_address=request.remote_addr
    )
    db.session.add(log_entry)
    db.session.commit()
    
    # Allow learner who previously failed a test attempt to terminate revision at any slide and resume test in sequence
    can_terminate_to_test = bool(enrolment.slides_completed and enrolment.attempts_used_in_current_cycle in [1, 2] and not enrolment.has_passed_test)
    next_attempt_seq = enrolment.attempts_used_in_current_cycle + 1

    # Allow learner who passed the test to terminate revision at any slide and return directly to certificate claim & status
    can_terminate_to_certificate = bool(enrolment.has_passed_test)

    return render_template(
        'elearning/player.html',
        course=course,
        slide=slide,
        slide_num=slide_num,
        total_slides=total_slides,
        enrolment=enrolment,
        practice_mcqs=practice_mcqs,
        has_practice=has_practice,
        all_practice_answered=all_practice_answered,
        practice_answered=practice_answered,
        previous_mcq_responses=previous_mcq_responses,
        is_completed_previously=is_completed_previously,
        is_revision=is_revision,
        can_terminate_to_test=can_terminate_to_test,
        next_attempt_seq=next_attempt_seq,
        can_terminate_to_certificate=can_terminate_to_certificate
    )


@courses_bp.route('/api/slide/complete', methods=['POST'])
@login_required
def complete_slide():
    """
    API called when client requests to mark slide completed and unlock next.
    Verifies:
    1. Minimum dwell time has elapsed on the server (unless slide was previously completed).
    2. All practice MCQs on this slide have been submitted.
    """
    data = request.get_json() or {}
    slug = data.get('slug')
    slide_num = data.get('slide_number')
    
    if not slug or not slide_num:
        return jsonify({'success': False, 'message': 'Invalid parameters'}), 400
        
    course = Course.query.filter_by(slug=slug, is_active=True).first()
    user = get_current_user()
    if not course or not user:
        return jsonify({'success': False, 'message': 'Course or user not found'}), 404
        
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
    if not enrolment:
        return jsonify({'success': False, 'message': 'Not enrolled'}), 403
        
    slide = Slide.query.filter_by(course_id=course.id, slide_number=slide_num).first()
    if not slide:
        return jsonify({'success': False, 'message': 'Slide not found'}), 404
        
    # Check MCQs on this slide (both practice in modules and final test MCQs)
    slide_mcqs = MCQ.query.filter_by(course_id=course.id, slide_id=slide.id, is_active=True).all()
    if slide_mcqs:
        answered = PracticeMCQResponse.query.filter_by(enrolment_id=enrolment.id).filter(
            PracticeMCQResponse.mcq_id.in_([q.id for q in slide_mcqs])
        ).count()
        if answered < len(slide_mcqs):
            return jsonify({
                'success': False,
                'message': 'You must submit your response to the question on this slide before proceeding.'
            }), 400

    # Verify dwell time on server if this is the learner's first time on this slide AND NOT in revision mode
    # NOTE: In revision mode there is NO timer, and MCQ slides do NOT have any timer.
    if not enrolment.slides_completed and slide_num > enrolment.highest_slide_completed:
        if not slide_mcqs and not slide.has_practice_mcq:
            session_key = f"slide_start_{enrolment.id}_{slide_num}"
            start_time = session.get(session_key)
            now = time.time()
            
            required_dwell = slide.minimum_dwell_seconds if slide.minimum_dwell_seconds is not None else 15
            # Allow minor clock tolerance
            tolerance = 0.5 if required_dwell <= 5 else 2.0
            if start_time and (now - start_time) < (required_dwell - tolerance):
                remaining = max(1, int(round(required_dwell - (now - start_time))))
                return jsonify({
                    'success': False,
                    'message': f"Please spend the full required time on this slide ({remaining}s remaining)."
                }), 400

        # Update highest slide completed
        enrolment.highest_slide_completed = max(enrolment.highest_slide_completed, slide_num)
        
    total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
    
    # Check if learner reached the end of the presentation (on the final slide)
    if slide_num >= total_slides:
        enrolment.highest_slide_completed = total_slides
        enrolment.slides_completed = True
        if not enrolment.has_passed_test:
            if enrolment.presentation_completions_count == 0:
                enrolment.presentation_completions_count = 1
                enrolment.attempts_used_in_current_cycle = 0
                if not enrolment.completed_at:
                    enrolment.completed_at = datetime.now(timezone.utc)
                log_audit_event(user.id, "PRESENTATION_COMPLETED", "Course", course.id, "Initial presentation completed")
            elif enrolment.attempts_used_in_current_cycle >= 3:
                # Learner had exhausted all 3 attempts, so completing a review cycle grants 3 fresh attempts
                enrolment.presentation_completions_count += 1
                enrolment.attempts_used_in_current_cycle = 0
                log_audit_event(user.id, "PRESENTATION_COMPLETED", "Course", course.id, f"Completed review cycle {enrolment.presentation_completions_count}")
            # NOTE: If attempts_used_in_current_cycle is 1 or 2, learner is revising slides between attempts.
            # Do NOT reset attempts_used_in_current_cycle!
        db.session.commit()
        
        # When clicking to proceed from the final slide, open the examination directly in one click
        target_url = url_for('tests.test_result_summary', slug=course.slug) if enrolment.has_passed_test else url_for('tests.take_test', slug=course.slug)
        return jsonify({
            'success': True,
            'completed_all': True,
            'next_url': target_url,
            'message': 'Congratulations! You have completed all slides.' + ('' if enrolment.has_passed_test else ' Final test unlocked.')
        })
        
    db.session.commit()
    next_slide_num = slide_num + 1
    return jsonify({
        'success': True,
        'completed_all': False,
        'next_slide_number': next_slide_num,
        'next_url': url_for('elearning.slide_player', slug=course.slug, slide_num=next_slide_num)
    })


@courses_bp.route('/api/practice/submit', methods=['POST'])
@login_required
def submit_practice_mcq():
    data = request.get_json() or {}
    mcq_id = data.get('mcq_id')
    selected_option = (data.get('selected_option') or '').strip().upper()
    
    mcq = db.session.get(MCQ, mcq_id)
    if not mcq:
        return jsonify({'success': False, 'message': 'Question not found'}), 404
        
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=mcq.course_id).first()
    if not enrolment:
        return jsonify({'success': False, 'message': 'Not enrolled'}), 403
        
    is_correct = (selected_option == mcq.correct_option)
    
    # Save response if first submission (cannot change response once submitted & vetted)
    resp = PracticeMCQResponse.query.filter_by(enrolment_id=enrolment.id, mcq_id=mcq.id).first()
    if not resp:
        resp = PracticeMCQResponse(
            enrolment_id=enrolment.id,
            mcq_id=mcq.id,
            selected_option=selected_option,
            is_correct=is_correct,
            attempted_at=datetime.now(timezone.utc)
        )
        db.session.add(resp)
        db.session.commit()
    else:
        # Response previously recorded and vetted; keep original response immutable
        is_correct = resp.is_correct
        selected_option = resp.selected_option
    
    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_option': mcq.correct_option,
        'explanation': mcq.explanation
    })
