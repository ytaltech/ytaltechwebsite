import os
os.environ['TESTING'] = 'true'
os.environ['FLASK_DEBUG'] = 'false'

import io
import time
import unittest
import json
from datetime import datetime, timezone
from app import app
from elearning.models import (
    db, User, Course, Slide, MCQ, Enrolment, TestAttempt,
    PaymentOrder, Certificate, CertificateComplaint, AuditLog, SystemSetting
)
from elearning.seed_from_pptx import import_pptx_presentations

class ElearningTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            admin = User.query.filter_by(email='admin@ytaltech.com').first()
            if admin:
                admin.set_password('Admin@Ytal2026!')
            finance = User.query.filter_by(email='finance@ytaltech.com').first()
            if finance:
                finance.set_password('Finance@Ytal2026!')
            courseadmin = User.query.filter_by(email='courseadmin@ytaltech.com').first()
            if courseadmin:
                courseadmin.set_password('CourseAdmin@Ytal2026!')

            learner = User.query.filter_by(email='learner@example.com').first()
            if not learner:
                learner = User(
                    email='learner@example.com',
                    first_name='Test',
                    last_name='Learner',
                    role='learner',
                    age=25,
                    gender='Male',
                    is_verified=True,
                    is_active=True
                )
                learner.set_password('Learner@2026!')
                db.session.add(learner)
            else:
                learner.set_password('Learner@2026!')
                learner.is_verified = True
                learner.is_active = True
            db.session.commit()

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_01_home_and_courses_discovery(self):
        """Test home page and course catalog endpoints."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Good Documentation Practices', response.data)
        self.assertIn(b'Good Clinical Practices', response.data)
        self.assertIn(b'New Drugs', response.data)
        self.assertIn(b'E-Learning', response.data)

        # Courses catalog
        res_courses = self.client.get('/elearning/courses')
        self.assertEqual(res_courses.status_code, 200)
        self.assertIn(b'Good Documentation Practices (GDP)', res_courses.data)
        self.assertIn(b'588.82', res_courses.data)
        self.assertIn(b'9.49', res_courses.data)

    def test_02_registration_validation_and_login(self):
        """Test registration constraints, password complexity, and login."""
        # Weak password should fail
        res_weak = self.client.post('/elearning/register', data={
            'first_name': 'Test',
            'last_name': 'Learner',
            'age': '25',
            'gender': 'Male',
            'email': 'testlearner@example.com',
            'password': 'weak',
            'confirm_password': 'weak',
            'dpdp_consent': '1'
        }, follow_redirects=True)
        self.assertIn(b'Password must be at least 8 characters long', res_weak.data)

        # Unique email for clean repeat testing
        unique_email = f"learner_{int(time.time() * 1000)}@example.com"
        res_valid = self.client.post('/elearning/register', data={
            'first_name': 'Ananya',
            'middle_name': 'R',
            'last_name': 'Deshmukh',
            'age': '27',
            'gender': 'Female',
            'email': unique_email,
            'password': 'Password@2026!',
            'confirm_password': 'Password@2026!',
            'dpdp_consent': '1'
        }, follow_redirects=True)
        self.assertEqual(res_valid.status_code, 200)
        self.assertIn(b'Registration successful', res_valid.data)

        u = User.query.filter_by(email=unique_email).first()
        self.assertIsNotNone(u)
        self.assertEqual(u.full_name, 'Ananya R Deshmukh')
        self.assertTrue(u.check_password('Password@2026!'))

    def test_03_course_enrolment_and_pricing_selection(self):
        """Test course enrolment with paid certificate option."""
        with self.client:
            self.client.post('/elearning/login', data={
                'email': 'learner@example.com',
                'password': 'Learner@2026!'
            }, follow_redirects=True)

            res_enrol = self.client.post('/elearning/course/good-documentation-practices/enrol', data={
                'certificate_option': 'paid'
            }, follow_redirects=True)
            self.assertEqual(res_enrol.status_code, 200)

            learner = User.query.filter_by(email='learner@example.com').first()
            course = Course.query.filter_by(slug='good-documentation-practices').first()
            enrolment = Enrolment.query.filter_by(user_id=learner.id, course_id=course.id).first()
            self.assertIsNotNone(enrolment)
            self.assertEqual(enrolment.certificate_option, 'paid')

            order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
            self.assertIsNotNone(order)
            self.assertAlmostEqual(order.expected_amount, 588.82, places=2)

    def test_04_slide_player_and_practice_mcq(self):
        """Test slide player rules and practice MCQ evaluation."""
        with self.client:
            self.client.post('/elearning/login', data={
                'email': 'learner@example.com',
                'password': 'Learner@2026!'
            })

            course = Course.query.filter_by(slug='good-documentation-practices').first()
            practice_mcq = MCQ.query.filter_by(course_id=course.id, type='practice').first()
            self.assertIsNotNone(practice_mcq)

            # Submit correct answer to practice MCQ
            res_mcq = self.client.post('/elearning/api/practice/submit', 
                data=json.dumps({'mcq_id': practice_mcq.id, 'selected_option': practice_mcq.correct_option}),
                content_type='application/json'
            )
            self.assertEqual(res_mcq.status_code, 200)
            data = json.loads(res_mcq.data)
            self.assertTrue(data['success'])
            self.assertTrue(data['is_correct'])

    def test_05_final_test_passing_and_scoring(self):
        """Test final test scoring (80% passing rule) and attempt management."""
        with self.client:
            self.client.post('/elearning/login', data={
                'email': 'learner@example.com',
                'password': 'Learner@2026!'
            })

            learner = User.query.filter_by(email='learner@example.com').first()
            course = Course.query.filter_by(slug='good-documentation-practices').first()
            enrolment = Enrolment.query.filter_by(user_id=learner.id, course_id=course.id).first()
            if not enrolment:
                enrolment = Enrolment(user_id=learner.id, course_id=course.id, certificate_option='paid')
                db.session.add(enrolment)
                db.session.commit()

            total_slides = Slide.query.filter_by(course_id=course.id).count()
            enrolment.highest_slide_completed = total_slides
            enrolment.slides_completed = True
            enrolment.attempts_used_in_current_cycle = 0
            # Reset any prior test attempts, payment orders, or certs for this enrolment
            Certificate.query.filter_by(enrolment_id=enrolment.id).delete()
            PaymentOrder.query.filter_by(enrolment_id=enrolment.id).delete()
            TestAttempt.query.filter_by(enrolment_id=enrolment.id).delete()
            db.session.commit()

            # Render test page to generate randomized question set
            res_test_page = self.client.get(f'/elearning/course/{course.slug}/test/take')
            self.assertEqual(res_test_page.status_code, 200)

            with self.client.session_transaction() as sess:
                q_ids = sess.get(f"test_q_ids_{enrolment.id}_1")
                self.assertIsNotNone(q_ids)
                self.assertEqual(len(q_ids), 20)

            mcq_objs = db.session.query(MCQ).filter(MCQ.id.in_(q_ids)).all()
            mcq_dict = {q.id: q for q in mcq_objs}

            # Submit test with 18 correct answers (90% score, PASSED >= 80%)
            form_data = {}
            for idx, q_id in enumerate(q_ids):
                q = mcq_dict[q_id]
                if idx < 18:
                    form_data[f"q_{q.id}"] = q.correct_option
                else:
                    wrong = 'B' if q.correct_option == 'A' else 'A'
                    form_data[f"q_{q.id}"] = wrong

            res_submit = self.client.post(f'/elearning/course/{course.slug}/test/take', data=form_data, follow_redirects=True)
            self.assertEqual(res_submit.status_code, 200)
            self.assertIn(b'You have successfully passed the test', res_submit.data)
            self.assertIn(b'18 / 20', res_submit.data)

    def test_06_manual_payment_submission_and_admin_approval(self):
        """Test manual payment submission, duplicate UTR detection, and Finance Admin verification."""
        learner = User.query.filter_by(email='learner@example.com').first()
        course = Course.query.filter_by(slug='good-documentation-practices').first()
        enrolment = Enrolment.query.filter_by(user_id=learner.id, course_id=course.id).first()
        
        # Ensure learner passed the test
        total_slides = Slide.query.filter_by(course_id=course.id).count()
        enrolment.highest_slide_completed = total_slides
        enrolment.slides_completed = True
        db.session.commit()

        order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
        if not order:
            from elearning.utils import generate_order_reference
            order = PaymentOrder(
                order_reference=generate_order_reference(),
                enrolment_id=enrolment.id,
                user_id=learner.id,
                course_id=course.id,
                expected_amount=588.82,
                currency='INR',
                gst_amount=89.82,
                status='pending_submission'
            )
            db.session.add(order)
            db.session.commit()

        # Learner submits payment proof
        with self.client:
            self.client.post('/elearning/login', data={'email': 'learner@example.com', 'password': 'Learner@2026!'})
            
            mock_file = (io.BytesIO(b"fake image receipt content"), "receipt.png")
            unique_utr = f"UTR{int(time.time() * 1000)}"
            res_pay = self.client.post(f'/elearning/payment/order/{order.order_reference}/submit', data={
                'action': 'submit',
                'amount_paid': '588.82',
                'currency': 'INR',
                'payment_mode': 'UPI',
                'payment_date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M'),
                'transaction_reference': unique_utr,
                'payer_name': 'Rahul Sharma',
                'payer_account_upi': 'rahul@okaxis',
                'learner_remarks': 'Paid via Google Pay with order ref in remark',
                'proof_file': mock_file
            }, follow_redirects=True)
            self.assertEqual(res_pay.status_code, 200)

            db.session.refresh(order)
            self.assertEqual(order.status, 'under_review')

        # Finance Admin logs in and approves payment
        with self.client:
            self.client.post('/elearning/login', data={'email': 'finance@ytaltech.com', 'password': 'Finance@Ytal2026!'})
            
            res_approve = self.client.post(f'/elearning/admin/payments/{order.id}/action', data={
                'action': 'approve',
                'admin_notes': 'Bank credit verified in HDFC Current A/C on 12-Nov-2026'
            }, follow_redirects=True)
            self.assertEqual(res_approve.status_code, 200)

            db.session.refresh(order)
            self.assertIn(order.status, ['verified_approved', 'certificate_issued'])

            cert = Certificate.query.filter_by(enrolment_id=enrolment.id).first()
            self.assertIsNotNone(cert)
            self.assertEqual(cert.status, 'valid')
            self.assertIn('YTAL-GDP-', cert.certificate_id)

    def test_07_certificate_verification_and_complaint(self):
        """Test public QR verification and fake certificate complaint flow."""
        learner = User.query.filter_by(email='learner@example.com').first()
        cert = Certificate.query.filter_by(user_id=learner.id).first()
        self.assertIsNotNone(cert)

        # Public verification
        res_verify = self.client.get(f'/verify-certificate?cert={cert.certificate_id}')
        self.assertEqual(res_verify.status_code, 200)
        self.assertIn(b'Verified Authentic Certificate', res_verify.data)
        self.assertIn(cert.user.full_name.encode('utf-8'), res_verify.data)

        # Verification of fake certificate
        res_fake = self.client.get('/verify-certificate?cert=FAKE-CERT-999')
        self.assertEqual(res_fake.status_code, 200)
        self.assertIn(b'This certificate could not be verified', res_fake.data)

        # Submit complaint for fake certificate
        res_comp = self.client.post('/verify-certificate/complaint', data={
            'certificate_id': 'FAKE-CERT-999',
            'reporter_name': 'Inspector Verma',
            'reporter_email': 'inspector@regulatory.gov.in',
            'reporter_phone': '9876543210',
            'issue_description': 'Found suspicious photocopy circulating in hospital',
            'consent_given': '1'
        }, follow_redirects=True)
        self.assertEqual(res_comp.status_code, 200)
        self.assertIn(b'submitted successfully to the Ytal Tech Compliance Team', res_comp.data)

        complaint = CertificateComplaint.query.filter_by(certificate_id_reported='FAKE-CERT-999').first()
        self.assertIsNotNone(complaint)
        self.assertEqual(complaint.reporter_name, 'Inspector Verma')

    def test_08_module_separator_color_and_dynamic_mcq_assessment(self):
        """
        Verify:
        1. Module separator slides across courses have #FFF200 yellow font color.
        2. Player has ergonomic left/right side navigation paddles.
        3. Final Assessment selects dynamic 20 questions with 40% Part A (8) and 60% Part B (12).
        4. No 'PART A' or 'PART B' is present anywhere on the presentation slides.
        """
        import re

        # 1. Verify #FFF200 yellow color against blue background and original styling against white background
        for slug in ['good-documentation-practices', 'ich-gcp', 'new-drugs-clinical-trials-rules-2019']:
            course = Course.query.filter_by(slug=slug).first()
            mod_covers = [s for s in course.slides if 'slide-type-module_cover' in s.content_html]
            self.assertGreater(len(mod_covers), 0, f"No module covers found for {slug}")
            for s in mod_covers:
                # Text against blue background in presentation-module-cover is Yellow #FFF200
                self.assertIn('presentation-module-cover', s.content_html)
                self.assertIn('#FFF200', s.content_html, f"Slide #{s.slide_number} in {slug} missing #FFF200 yellow font color")
                # Text in header against white background does not have inline yellow override
                self.assertNotIn('<div class="slide-breadcrumb" style="color: #FFF200', s.content_html)

        # 2. Verify ergonomic player layout with left/right side navigation
        with self.client:
            self.client.post('/elearning/login', data={'email': 'learner@example.com', 'password': 'Learner@2026!'})
            res_player = self.client.get('/elearning/course/good-documentation-practices/player/1')
            self.assertEqual(res_player.status_code, 200)
            self.assertIn(b'player-flank-layout', res_player.data)
            self.assertIn(b'btnPrevSlide', res_player.data)
            self.assertIn(b'btnNextSlide', res_player.data)

        # 3. Verify dynamic 20-slide examination with 8 Part A (40%) and 12 Part B (60%)
        unique_email = f"exam_verify_{int(time.time() * 1000)}@example.com"
        u = User(email=unique_email, first_name='Test', last_name='ExamLearner', age=29, gender='Male')
        u.set_password('Password@2026!')
        db.session.add(u)
        db.session.commit()

        u.is_verified = True
        gdp = Course.query.filter_by(slug='good-documentation-practices').first()
        enrol = Enrolment(
            user_id=u.id,
            course_id=gdp.id,
            certificate_option='paid',
            slides_completed=True,
            highest_slide_completed=len(gdp.slides)
        )
        db.session.add(enrol)
        db.session.commit()

        exam_client = self.app.test_client()
        with exam_client:
            exam_client.post('/elearning/login', data={'email': unique_email, 'password': 'Password@2026!'})
            res_exam = exam_client.get('/elearning/course/good-documentation-practices/test/take')
            self.assertEqual(res_exam.status_code, 200)
            html = res_exam.data.decode('utf-8')

            # Ensure NO mention of Part A or Part B on the slides
            self.assertEqual(len(re.findall(r'\bPART\s+A\b', html, re.IGNORECASE)), 0)
            self.assertEqual(len(re.findall(r'\bPART\s+B\b', html, re.IGNORECASE)), 0)

            # Check question slide structure and sequential numbering
            self.assertIn('FINAL ASSESSMENT &nbsp;|&nbsp; Question 1', html)
            self.assertIn('FINAL ASSESSMENT &nbsp;|&nbsp; Question 20', html)

            # Check exact 40% Part A and 60% Part B ratio from session
            session_key = f"test_q_ids_{enrol.id}_1"
            with exam_client.session_transaction() as sess:
                q_ids = sess.get(session_key)
                self.assertEqual(len(q_ids), 20)
                qs = MCQ.query.filter(MCQ.id.in_(q_ids)).all()
                part_a_qs = [q for q in qs if q.part == 'A']
                part_b_qs = [q for q in qs if q.part == 'B']
                self.assertEqual(len(part_a_qs), 8, "Expected exactly 8 questions from Part A (40%)")
                self.assertEqual(len(part_b_qs), 12, "Expected exactly 12 questions from Part B (60%)")

        # Clean up
        db.session.delete(enrol)
        db.session.delete(u)
        db.session.commit()

    def test_09_responsiveness_and_mobile_readiness(self):
        """Verify responsiveness meta tags, mobile nav toggle, and responsive CSS structure."""
        # 1. Main website responsiveness
        res_home = self.client.get('/')
        self.assertEqual(res_home.status_code, 200)
        home_html = res_home.data.decode('utf-8')
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', home_html)
        self.assertIn('id="mobileNavToggle"', home_html)
        self.assertIn('mobile-nav-toggle', home_html)

        # 2. E-learning portal base layout responsiveness
        res_catalog = self.client.get('/elearning/courses')
        self.assertEqual(res_catalog.status_code, 200)
        catalog_html = res_catalog.data.decode('utf-8')
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', catalog_html)
        self.assertIn('id="mobileNavToggle"', catalog_html)
        self.assertIn('mobile-nav-toggle', catalog_html)

        # 3. Slide player & test responsive markup
        with self.client:
            self.client.post('/elearning/login', data={'email': 'learner@example.com', 'password': 'Learner@2026!'})
            res_player = self.client.get('/elearning/course/good-documentation-practices/player/1')
            self.assertEqual(res_player.status_code, 200)
            player_html = res_player.data.decode('utf-8')
            self.assertIn('flank-left-col', player_html)
            self.assertIn('flank-right-col', player_html)
            self.assertIn('player-flank-layout', player_html)

        # 4. CSS file responsive rules inspection
        with open('static/style.css', 'r', encoding='utf-8') as f:
            style_css = f.read()
        self.assertIn('.mobile-nav-toggle', style_css)
        self.assertIn('.hamburger-bar', style_css)
        self.assertIn('.nav-links.nav-open', style_css)
        self.assertIn('@media (max-width: 768px)', style_css)
        self.assertIn('@media (max-width: 480px)', style_css)

        with open('static/elearning/elearning.css', 'r', encoding='utf-8') as f:
            elearning_css = f.read()
        self.assertIn('@media (max-width: 768px)', elearning_css)
        self.assertIn('grid-template-areas:', elearning_css)
        self.assertIn('"slide slide"', elearning_css)
        self.assertIn('"prev next"', elearning_css)
        self.assertIn('.mcq-dual-response-bar', elearning_css)
        self.assertIn('.exam-palette-bar', elearning_css)

    def test_10_equal_probability_and_presentation_slides_clean_finish(self):
        """Verify removal of final test slides from lecture presentation and equal probability of MCQ answers."""
        from collections import Counter

        for slug, expected_slides in [
            ('good-documentation-practices', 233),
            ('ich-gcp', 191),
            ('new-drugs-clinical-trials-rules-2019', 195)
        ]:
            course = Course.query.filter_by(slug=slug).first()
            self.assertIsNotNone(course)
            slides = Slide.query.filter_by(course_id=course.id).order_by(Slide.slide_number).all()
            self.assertEqual(len(slides), expected_slides, f"Expected {expected_slides} lecture slides for {slug}")

            # Verify that final slide is indeed the completion slide
            final_slide = slides[-1]
            self.assertIn('presentation-completion-slide', final_slide.content_html)
            self.assertIn('Congratulations on Completing the Curriculum', final_slide.content_html)

            # Verify that NO lecture slide contains final assessment MCQs
            for s in slides:
                self.assertNotIn('FINAL ASSESSMENT QUESTION', s.content_html)

            # Verify final_test MCQs in dedicated MCQ bank
            final_mcqs = MCQ.query.filter_by(course_id=course.id, type='final_test').all()
            self.assertGreater(len(final_mcqs), 0)

            # Verify Part A and Part B existence
            part_a = [q for q in final_mcqs if q.part == 'A']
            part_b = [q for q in final_mcqs if q.part == 'B']
            self.assertGreaterEqual(len(part_a), 8)
            self.assertGreaterEqual(len(part_b), 12)

            # Verify equal probability across all options (A, B, C, D)
            # In an equal probability distribution across 4 options, each option has ~25% frequency.
            # No single option should dominate (> 35% of the total questions)
            ans_counts = Counter(q.correct_option for q in final_mcqs)
            for opt in ['A', 'B', 'C', 'D']:
                self.assertIn(opt, ans_counts, f"Option {opt} should have correct answers in {slug}")
                percentage = (ans_counts[opt] / len(final_mcqs)) * 100.0
                # Check that distribution is balanced (between 15% and 35%)
                self.assertTrue(
                    15.0 <= percentage <= 35.0,
                    f"Option {opt} percentage {percentage}% out of expected balanced range [15%, 35%] in {slug}"
                )

    def test_11_admin_payment_columns_and_region(self):
        """Verify 3 separate amount columns (Amount, GST, Total) and India/International region column."""
        # Log in as Super Admin
        with self.client:
            self.client.post('/elearning/login', data={'email': 'admin@ytaltech.com', 'password': 'Admin@Ytal2026!'})
            res = self.client.get('/elearning/admin/payments')
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            
            # Verify separate table headers
            self.assertIn('<th>Region</th>', html)
            self.assertIn('<th>Base Amount</th>', html)
            self.assertIn('<th>GST (18%)</th>', html)
            self.assertIn('<th>Total Amount</th>', html)
            
            # Verify CSV export contains these separate columns
            res_csv = self.client.get('/elearning/admin/payments/export-csv')
            self.assertEqual(res_csv.status_code, 200)
            csv_text = res_csv.data.decode('utf-8')
            self.assertIn('Region,Currency,Base Amount,GST Amount,Total Amount,Customer GSTIN', csv_text)

    def test_12_mcq_edit_and_save(self):
        """Verify that MCQs can be loaded into edit form, edited, and saved to database."""
        with self.client:
            self.client.post('/elearning/login', data={'email': 'admin@ytaltech.com', 'password': 'Admin@Ytal2026!'})
            
            # Get an existing MCQ
            mcq = MCQ.query.filter_by(type='final_test').first()
            self.assertIsNotNone(mcq)
            
            # 1. Load Edit Form
            res_edit_get = self.client.get(f'/elearning/admin/mcqs/{mcq.id}/edit')
            self.assertEqual(res_edit_get.status_code, 200)
            edit_html = res_edit_get.data.decode('utf-8')
            self.assertIn(f'Edit Assessment Question #{mcq.id}', edit_html)
            self.assertIn(mcq.question_text[:30], edit_html)
            
            # 2. Edit and Save Changes
            updated_prompt = f"Updated prompt for test #{mcq.id} - ALCOA+ compliance check"
            res_edit_post = self.client.post(f'/elearning/admin/mcqs/{mcq.id}/edit', data={
                'course_id': str(mcq.course_id),
                'type': 'final_test',
                'part': 'B',
                'question_text': updated_prompt,
                'option_a': 'Option A Modified',
                'option_b': 'Option B Modified',
                'option_c': 'Option C Modified',
                'option_d': 'Option D Modified',
                'correct_option': 'C',
                'difficulty': 'hard',
                'explanation': 'Updated explanation for regulatory standard.',
                'is_active': '1'
            }, follow_redirects=True)
            self.assertEqual(res_edit_post.status_code, 200)
            self.assertIn(b'updated and saved successfully', res_edit_post.data)
            
            # Verify DB updated
            db.session.refresh(mcq)
            self.assertEqual(mcq.question_text, updated_prompt)
            self.assertEqual(mcq.correct_option, 'C')
            self.assertEqual(mcq.difficulty, 'hard')
            self.assertEqual(mcq.option_c, 'Option C Modified')

    def test_13_sbi_qr_scanner_setting_and_whatsapp_notice(self):
        """Verify official SBI QR code scanner setting from PDF and WhatsApp screenshot instruction."""
        # 1. Verify System Setting
        upi_qr = SystemSetting.get('upi_qr_image')
        self.assertIsNotNone(upi_qr)
        self.assertIn('sbi_upi_qr', upi_qr)
        
        # 2. Verify Payment Page displays official QR code and WhatsApp notice
        learner = User.query.filter_by(email='learner@example.com').first()
        order = PaymentOrder.query.filter_by(user_id=learner.id).first()
        self.assertIsNotNone(order)
        
        with self.client:
            self.client.post('/elearning/login', data={'email': learner.email, 'password': 'Learner@2026!'})
            res_pay = self.client.get(f'/elearning/payment/order/{order.order_reference}')
            self.assertEqual(res_pay.status_code, 200)
            pay_html = res_pay.data.decode('utf-8')
            
            # Official QR image displayed
            self.assertIn(upi_qr, pay_html)
            
            # WhatsApp screenshot instruction displayed (Requirement 5)
            self.assertIn('Additionally, you may share the payment screenshot on Whatsapp: <a href="https://wa.me/919372571921', pay_html)
            self.assertIn('9372571921', pay_html)

    def test_14_gst_invoice_docx_format_and_customer_gst_provision(self):
        """Verify customer GST details provision, SAC code 998314, and DOCX-matched Tax Invoice generation."""
        learner = User.query.filter_by(email='learner@example.com').first()
        order = PaymentOrder.query.filter_by(user_id=learner.id).first()
        self.assertIsNotNone(order)
        
        # Customer submits GST details
        with self.client:
            self.client.post('/elearning/login', data={'email': learner.email, 'password': 'Learner@2026!'})
            mock_file = (io.BytesIO(b"dummy receipt image"), "receipt.png")
            
            res_submit = self.client.post(f'/elearning/payment/order/{order.order_reference}/submit', data={
                'action': 'submit',
                'amount_paid': '588.82',
                'currency': 'INR',
                'payment_mode': 'UPI',
                'payment_date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M'),
                'transaction_reference': f'UTR_TEST_{int(time.time()*1000)}',
                'payer_name': 'Rahul Sharma',
                'payer_account_upi': 'rahul@okaxis',
                'customer_org_name': 'BB Precision Oncocare Centre Private Limited',
                'customer_gstin': '27AAACR1234F1Z5',
                'customer_state': 'Maharashtra',
                'customer_billing_address': 'Shop No.3, Western Heights Co-op Housing Society Ltd, Andheri West, Mumbai 400058',
                'proof_file': mock_file
            }, follow_redirects=True)
            self.assertEqual(res_submit.status_code, 200)
            
            # Verify fields saved on order
            db.session.refresh(order)
            self.assertEqual(order.customer_gstin, '27AAACR1234F1Z5')
            self.assertEqual(order.customer_org_name, 'BB Precision Oncocare Centre Private Limited')
            
            # Generate GST-compliant invoice
            from elearning.utils import generate_pdf_invoice
            pdf_path = generate_pdf_invoice(order)
            self.assertTrue(os.path.exists(pdf_path))
            
            # Read and inspect PDF text
            import pymupdf
            doc = pymupdf.open(pdf_path)
            full_text = "".join(p.get_text() for p in doc)
            
            self.assertIn('TAX RECEIPT', full_text)
            self.assertIn('Receipt No:', full_text)
            self.assertIn('Receipt Date:', full_text)
            self.assertIn('27AADFY4241Q1ZL', full_text)  # Supplier GSTIN
            self.assertIn('AADFY4241Q', full_text)        # Supplier PAN
            self.assertIn('998314', full_text)            # SAC Code (from docx)
            self.assertIn('27AAACR1234F1Z5', full_text)  # Customer GSTIN
            self.assertIn('BB Precision Oncocare Centre', full_text) # Customer Org
            self.assertIn('CGST @ 9%', full_text)
            self.assertIn('SGST @ 9%', full_text)
            self.assertIn('Amount in Words', full_text)
            self.assertIn('Authorized Signatory', full_text)
            self.assertNotIn('Payment Details', full_text)
            self.assertNotIn('A/c Number', full_text)
            self.assertNotIn('SBIN0061708', full_text)
            self.assertIn('contact@ytaltech.com', full_text)

    def test_15_bulk_discount_landing_page_notice(self):
        """Verify bulk discount callout on landing page and catalog."""
        # 1. E-Learning Course Catalog / Landing Page
        res_catalog = self.client.get('/elearning/courses')
        self.assertEqual(res_catalog.status_code, 200)
        cat_html = res_catalog.data.decode('utf-8')
        self.assertIn('bd@ytaltech.com', cat_html)
        self.assertIn('for bulk discount.', cat_html)
        self.assertNotIn('for EC members / clinical trial site team', cat_html)

        # 2. Main Website Landing Page
        res_home = self.client.get('/')
        self.assertEqual(res_home.status_code, 200)
        home_html = res_home.data.decode('utf-8')
        self.assertIn('bd@ytaltech.com', home_html)
        self.assertIn('for bulk discount.', home_html)
        self.assertNotIn('for EC members / clinical trial site team', home_html)

    def test_16_certificate_logo_proportions_and_designations(self):
        """Verify undistorted proportional logo and updated designations (Course Director & Compliance Director)."""
        from elearning.utils import generate_pdf_certificate
        import fitz

        cert = Certificate.query.filter_by(status='valid').first()
        self.assertIsNotNone(cert, "No valid certificate found for test.")

        pdf_path = generate_pdf_certificate(cert)
        self.assertTrue(os.path.exists(pdf_path))

        # Extract text from generated PDF
        doc = fitz.open(pdf_path)
        self.assertEqual(len(doc), 1, "Certificate must fit on exactly one single page.")
        text = doc[0].get_text()

        self.assertIn('Dr. Ganesh Divekar', text)
        self.assertIn('Course Director', text)
        self.assertIn('Ajay Kondekar', text)
        self.assertIn('Compliance Director', text)
        self.assertNotIn('Technical Architect', text)
        self.assertNotIn('Quality Compliance Head', text)

        # Also verify web preview template
        with self.client:
            self.client.post('/elearning/login', data={'email': cert.user.email, 'password': 'Password@2026!'})
            res_view = self.client.get(f'/elearning/certificate/{cert.certificate_id}')
            if res_view.status_code == 200:
                view_html = res_view.data.decode('utf-8')
                self.assertIn('Course Director', view_html)
                self.assertIn('Compliance Director', view_html)
                self.assertNotIn('Technical Architect', view_html)
                self.assertNotIn('Quality Compliance Head', view_html)

    def test_17_certificate_payment_confirmation_gate(self):
        """Verify certificate can appear and download ONLY after payment confirmation by finance or admin."""
        # Find or create a user and enrolment
        user = User.query.filter_by(email='unapproved_pay_learner@example.com').first()
        if not user:
            user = User(
                email='unapproved_pay_learner@example.com',
                first_name='Gated',
                last_name='Learner',
                age=29,
                gender='Male',
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='paid',
                slides_completed=True,
                highest_slide_completed=233
            )
            db.session.add(enrolment)
            db.session.commit()

        order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
        if not order:
            order = PaymentOrder(
                order_reference='ORD-GATE-TEST-001',
                enrolment_id=enrolment.id,
                user_id=user.id,
                course_id=course.id,
                expected_amount=course.total_price_inr,
                currency='INR',
                status='pending_submission'
            )
            db.session.add(order)
            db.session.commit()

        # Create certificate record
        cert = Certificate.query.filter_by(enrolment_id=enrolment.id).first()
        if not cert:
            cert = Certificate(
                certificate_id='YT-GATE-TEST-001',
                enrolment_id=enrolment.id,
                user_id=user.id,
                course_id=course.id,
                payment_order_id=order.id,
                issue_date=datetime.now(timezone.utc).date(),
                score_percentage=95.0,
                status='valid',
                digital_signature_hash='dummyhash123456789'
            )
            db.session.add(cert)
            db.session.commit()

        # 1. When payment is pending_submission, learner viewing/downloading certificate is blocked
        order.status = 'pending_submission'
        db.session.commit()
        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_view = self.client.get(f'/elearning/certificate/{cert.certificate_id}')
            self.assertEqual(res_view.status_code, 302)
            self.assertIn('/elearning/payment/status/', res_view.headers['Location'])

            res_dl = self.client.get(f'/elearning/certificate/{cert.certificate_id}/download')
            self.assertEqual(res_dl.status_code, 302)
            self.assertIn('/elearning/payment/status/', res_dl.headers['Location'])

        # 2. When payment is under_review, still blocked
        order.status = 'under_review'
        db.session.commit()
        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_view = self.client.get(f'/elearning/certificate/{cert.certificate_id}')
            self.assertEqual(res_view.status_code, 302)

        # 3. Once finance or admin approves (verified_approved), certificate view is permitted
        order.status = 'verified_approved'
        db.session.commit()
        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_view = self.client.get(f'/elearning/certificate/{cert.certificate_id}')
            self.assertEqual(res_view.status_code, 200)

    def test_18_login_password_visibility_toggle(self):
        """Verify login screen includes password visibility button toggle."""
        res = self.client.get('/elearning/login')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('id="loginPassword"', html)
        self.assertIn('id="togglePasswordBtn"', html)
        self.assertIn('👁', html)

    def test_19_vetted_mcq_response_on_previous_slide(self):
        """Verify slide player loads previously vetted MCQ response when returning to slide."""
        user = User.query.filter_by(email='mcq_vetted_user@example.com').first()
        if not user:
            user = User(
                email='mcq_vetted_user@example.com',
                first_name='MCQ',
                last_name='Tester',
                age=28,
                gender='Female',
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                current_slide_number=1,
                highest_slide_completed=10
            )
            db.session.add(enrolment)
            db.session.commit()

        # Find a slide with an active practice MCQ
        mcq = MCQ.query.filter_by(course_id=course.id, is_active=True).first()
        self.assertIsNotNone(mcq)
        slide = db.session.get(Slide, mcq.slide_id)
        enrolment.highest_slide_completed = max(enrolment.highest_slide_completed, slide.slide_number)
        db.session.commit()

        # Submit practice answer
        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_submit = self.client.post('/elearning/api/practice/submit', json={
                'mcq_id': mcq.id,
                'selected_option': mcq.correct_option
            })
            self.assertEqual(res_submit.status_code, 200)
            res_data = json.loads(res_submit.data)
            self.assertTrue(res_data['success'])
            self.assertTrue(res_data['is_correct'])

            # Now visit the slide player for this slide
            res_player = self.client.get(f'/elearning/course/{course.slug}/player/{slide.slide_number}')
            self.assertEqual(res_player.status_code, 200)
            player_html = res_player.data.decode('utf-8')
            self.assertIn('window.PREVIOUS_MCQ_RESPONSES', player_html)
            self.assertIn(str(mcq.id), player_html)
            self.assertIn(mcq.correct_option, player_html)

    def test_20_revision_mode_slide_navigation_and_no_timer(self):
        """Verify revision mode allows full presentation navigation (does not get stuck on slide 1)."""
        user = User.query.filter_by(email='revision_test_user@example.com').first()
        if not user:
            user = User(
                email='revision_test_user@example.com',
                first_name='Revise',
                last_name='Learner',
                age=30,
                gender='Male',
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                slides_completed=True,
                highest_slide_completed=total_slides,
                current_slide_number=1
            )
            db.session.add(enrolment)
            db.session.commit()
        else:
            enrolment.slides_completed = True
            enrolment.highest_slide_completed = total_slides
            db.session.commit()

        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})

            # Check slide player in revision mode
            res_p1 = self.client.get(f'/elearning/course/{course.slug}/player/1')
            self.assertEqual(res_p1.status_code, 200)
            p1_html = res_p1.data.decode('utf-8')
            self.assertIn('Revision Mode', p1_html)
            self.assertIn('data-revision="true"', p1_html)

            # Completing slide 1 during revision MUST advance to slide 2, NOT kick out to test
            res_c1 = self.client.post('/elearning/api/slide/complete', json={
                'slug': course.slug,
                'slide_number': 1
            })
            self.assertEqual(res_c1.status_code, 200)
            c1_data = json.loads(res_c1.data)
            self.assertTrue(c1_data['success'])
            self.assertFalse(c1_data['completed_all'])
            self.assertEqual(c1_data['next_slide_number'], 2)
            self.assertIn('/player/2', c1_data['next_url'])

    def test_21_upgrade_direct_redirect_to_verification_status(self):
        """Verify upgrading to paid certificate post-completion redirects directly to verification status screen."""
        user = User.query.filter_by(email='upgrade_redirect_user@example.com').first()
        if not user:
            user = User(
                email='upgrade_redirect_user@example.com',
                first_name='Direct',
                last_name='Upgrade',
                age=26,
                gender='Female',
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                slides_completed=True,
                highest_slide_completed=233
            )
            db.session.add(enrolment)
            db.session.commit()
        else:
            enrolment.certificate_option = 'free'
            enrolment.slides_completed = True
            db.session.commit()

        # Add passed attempt
        attempt = TestAttempt.query.filter_by(enrolment_id=enrolment.id).first()
        if not attempt:
            attempt = TestAttempt(
                enrolment_id=enrolment.id,
                attempt_number=1,
                score=18,
                percentage=90.0,
                passed=True,
                submitted_at=datetime.now(timezone.utc)
            )
            db.session.add(attempt)
            db.session.commit()

        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_upgrade = self.client.post(f'/elearning/course/{course.slug}/enrol', data={
                'certificate_option': 'paid'
            })
            # Must redirect directly to summary (verification status)
            self.assertEqual(res_upgrade.status_code, 302)
            self.assertIn(f'/course/{course.slug}/test/summary', res_upgrade.headers['Location'])
            self.assertNotIn('/player', res_upgrade.headers['Location'])

    def test_22_free_audit_one_month_upgrade_window(self):
        """Verify 1-month upgrade window logic for free track completion."""
        from datetime import timedelta
        user = User.query.filter_by(email='window_user@example.com').first()
        if not user:
            user = User(
                email='window_user@example.com',
                first_name='Window',
                last_name='Tester',
                age=31,
                gender='Male',
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                slides_completed=True,
                highest_slide_completed=233
            )
            db.session.add(enrolment)
            db.session.commit()

        attempt = TestAttempt.query.filter_by(enrolment_id=enrolment.id).first()
        if not attempt:
            attempt = TestAttempt(
                enrolment_id=enrolment.id,
                attempt_number=1,
                score=19,
                percentage=95.0,
                passed=True,
                submitted_at=datetime.now(timezone.utc)
            )
            db.session.add(attempt)
            db.session.commit()

        # Case A: Within 1-month window (e.g. passed 5 days ago)
        attempt.submitted_at = datetime.now(timezone.utc) - timedelta(days=5)
        enrolment.certificate_option = 'free'
        db.session.commit()

        self.assertFalse(enrolment.is_free_upgrade_expired)
        self.assertGreaterEqual(enrolment.free_upgrade_days_remaining, 24)

        # Case B: Expired window (e.g. passed 35 days ago)
        attempt.submitted_at = datetime.now(timezone.utc) - timedelta(days=35)
        db.session.commit()

        self.assertTrue(enrolment.is_free_upgrade_expired)
        self.assertEqual(enrolment.free_upgrade_days_remaining, 0)

        # Upgrade attempt when expired must be blocked
        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_blocked = self.client.post(f'/elearning/course/{course.slug}/enrol', data={
                'certificate_option': 'paid'
            }, follow_redirects=True)
            self.assertEqual(res_blocked.status_code, 200)
            self.assertIn(b'The 1-month window to pay and download a certificate has expired', res_blocked.data)

    def test_23_landing_page_copy_updates(self):
        """Verify the 4 copy updates on the e-learning landing page and course detail page."""
        with self.client:
            self.client.post('/elearning/login', data={'email': 'admin@ytaltech.com', 'password': 'Admin@Ytal2026!'})
            res_gdp = self.client.get('/elearning/course/good-documentation-practices')
            self.assertEqual(res_gdp.status_code, 200)
            gdp_html = res_gdp.data.decode('utf-8')

            # 1. Official Tax Receipt download (GST compliant)
            self.assertIn('Official Tax Receipt download (GST compliant)', gdp_html)
            self.assertNotIn('<li>Official Tax Receipt download</li>', gdp_html)

            # 2. Refund policy via bd@ytaltech.com
            self.assertIn('Refund Policy:</strong> Requests for refunds before payment verification or test commencement can be processed via bd@ytaltech.com.', gdp_html)
            self.assertNotIn('processed via support@ytaltech.com', gdp_html)

            # 3. GDP overview: 'This course provides comprehensive training...' without 'accredited'
            self.assertIn('This course provides comprehensive training on Good Documentation Practices (GDP) applicable across clinical trials, healthcare data management, and GxP regulated industries. Learners will understand ALCOA+ guidelines, contemporary signature rules, error rectification protocols, and electronic record compliance under 21 CFR Part 11.', gdp_html)
            self.assertNotIn('This accredited course provides comprehensive training on Good Documentation Practices', gdp_html)

            # 4. Bulk discount via bd@ytaltech.com on catalog and course detail
            self.assertIn('bd@ytaltech.com', gdp_html)
            self.assertIn('for bulk discount.', gdp_html)

        res_cat = self.client.get('/elearning/courses')
        self.assertEqual(res_cat.status_code, 200)
        cat_html = res_cat.data.decode('utf-8')
        self.assertIn('Please get in touch with us on <a href="mailto:bd@ytaltech.com?subject=Bulk%20Discount%20Inquiry%20-%20E-Learning" style="color: #065f46; text-decoration: underline; font-weight: 800;">bd@ytaltech.com</a> for bulk discount.', cat_html)

    def test_24_single_click_to_test_from_completion_slide(self):
        """Verify clicking Take Final Certified Examination once directly loads the test."""
        user = User.query.filter_by(email='single_click_user@example.com').first()
        if not user:
            user = User(
                email='single_click_user@example.com',
                first_name='Click',
                last_name='Tester',
                age=29,
                gender='Male',
                is_verified=True,
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                highest_slide_completed=total_slides - 1,
                current_slide_number=total_slides
            )
            db.session.add(enrolment)
            db.session.commit()

        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            # Clicking the completion slide link /course/<slug>/test directly opens the test (take_test)
            res = self.client.get(f'/elearning/course/{course.slug}/test', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            # Test interface with 20 questions is rendered immediately in 1 click
            self.assertIn('Final Certified Examination', html)
            self.assertIn('pal-btn-1', html)

    def test_25_test_not_passed_reword_and_appear_again(self):
        """Verify failed test shows 'Test Not Passed' and reworded mandate notice."""
        user = User.query.filter_by(email='fail_reword_user@example.com').first()
        if not user:
            user = User(
                email='fail_reword_user@example.com',
                first_name='Fail',
                last_name='Tester',
                age=25,
                gender='Female',
                is_verified=True,
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                slides_completed=True,
                highest_slide_completed=233,
                presentation_completions_count=1,
                attempts_used_in_current_cycle=1
            )
            db.session.add(enrolment)
            db.session.commit()

        attempt = TestAttempt(
            enrolment_id=enrolment.id,
            attempt_number=1,
            score=12,
            percentage=60.0,
            passed=False,
            submitted_at=datetime.now(timezone.utc)
        )
        db.session.add(attempt)
        db.session.commit()

        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res = self.client.get(f'/elearning/course/{course.slug}/test/result/{attempt.id}')
            self.assertEqual(res.status_code, 200)
            html = res.data.decode('utf-8')
            self.assertIn('Test Not Passed', html)
            self.assertIn('You did not clear the required mandate of correct responses to pass the test and hence need to appear for the test again.', html)
            self.assertIn('Appear for the Test Again', html)

    def test_26_revision_mode_preserves_attempt_progression(self):
        """Verify that reviewing slides in revision mode post failed attempt does NOT reset to Attempt 1."""
        user = User.query.filter_by(email='revision_prog_user@example.com').first()
        if not user:
            user = User(
                email='revision_prog_user@example.com',
                first_name='Prog',
                last_name='Tester',
                age=32,
                gender='Male',
                is_verified=True,
                is_active=True
            )
            user.set_password('Password@2026!')
            db.session.add(user)
            db.session.commit()
        user.is_verified = True
        db.session.commit()

        course = Course.query.filter_by(slug='good-documentation-practices').first()
        total_slides = Slide.query.filter_by(course_id=course.id, is_active=True).count()
        enrolment = Enrolment.query.filter_by(user_id=user.id, course_id=course.id).first()
        if not enrolment:
            enrolment = Enrolment(
                user_id=user.id,
                course_id=course.id,
                certificate_option='free',
                slides_completed=True,
                highest_slide_completed=total_slides,
                presentation_completions_count=1,
                attempts_used_in_current_cycle=1  # 1 attempt already failed
            )
            db.session.add(enrolment)
            db.session.commit()
        else:
            enrolment.attempts_used_in_current_cycle = 1
            db.session.commit()

        # Learner reviews slides and reaches final slide
        with self.client:
            self.client.post('/elearning/login', data={'email': user.email, 'password': 'Password@2026!'})
            res_comp = self.client.post('/elearning/api/slide/complete', json={
                'slug': course.slug,
                'slide_number': total_slides
            })
            self.assertEqual(res_comp.status_code, 200)

            # Enrolment must NOT have reset to 0! It must still be 1!
            db.session.refresh(enrolment)
            self.assertEqual(enrolment.attempts_used_in_current_cycle, 1)

            # Opening the test must show Attempt 2, NOT Attempt 1!
            res_test = self.client.get(f'/elearning/course/{course.slug}/test/take')
            self.assertEqual(res_test.status_code, 200)
            html = res_test.data.decode('utf-8')
            self.assertIn('Attempt 2 of 3', html)
            self.assertNotIn('Attempt 1 of 3', html)

    def test_27_login_gated_by_email_validation(self):
        """Verify user cannot log in post sign-up until email is validated by clicking validation link."""
        unique_email = f"unverified_{int(time.time() * 1000)}@example.com"
        
        # 1. Register new user
        res_reg = self.client.post('/elearning/register', data={
            'first_name': 'Validation',
            'last_name': 'Check',
            'age': '24',
            'gender': 'Male',
            'email': unique_email,
            'password': 'Password@2026!',
            'confirm_password': 'Password@2026!',
            'dpdp_consent': '1'
        }, follow_redirects=True)
        self.assertEqual(res_reg.status_code, 200)
        reg_html = res_reg.data.decode('utf-8')
        self.assertIn('Please validate your email ID', reg_html)

        u = User.query.filter_by(email=unique_email).first()
        self.assertIsNotNone(u)
        self.assertFalse(u.is_verified)
        self.assertIsNotNone(u.email_verification_token)

        # 2. Attempt login BEFORE validating email -> MUST BE BLOCKED
        res_login_blocked = self.client.post('/elearning/login', data={
            'email': unique_email,
            'password': 'Password@2026!'
        }, follow_redirects=True)
        self.assertEqual(res_login_blocked.status_code, 200)
        blocked_html = res_login_blocked.data.decode('utf-8')
        self.assertIn('Your email ID has not been validated yet', blocked_html)
        self.assertIn('Resend Validation Email', blocked_html)

        # 3. Click validation link from email
        res_verify = self.client.get(f'/elearning/verify-email/{u.email_verification_token}', follow_redirects=True)
        self.assertEqual(res_verify.status_code, 200)
        verify_html = res_verify.data.decode('utf-8')
        self.assertIn('Your email ID has been successfully validated', verify_html)

        db.session.refresh(u)
        self.assertTrue(u.is_verified)

        # 4. Now login SUCCEEDS
        res_login_ok = self.client.post('/elearning/login', data={
            'email': unique_email,
            'password': 'Password@2026!'
        }, follow_redirects=True)
        self.assertEqual(res_login_ok.status_code, 200)
        ok_html = res_login_ok.data.decode('utf-8')
        self.assertIn('Welcome back, Validation!', ok_html)

if __name__ == '__main__':
    unittest.main()
