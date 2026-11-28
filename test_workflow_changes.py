import os
os.environ['TESTING'] = 'true'
os.environ['FLASK_DEBUG'] = 'false'

import unittest
import json
import time
import io
from app import app
from elearning.models import (
    db, User, Course, Slide, MCQ, Enrolment, TestAttempt, PaymentOrder
)

class WorkflowChangesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Create unique verified test learner
        self.email = f"learner_wf_{int(time.time() * 1000)}@example.com"
        self.user = User(
            first_name="Pooja",
            last_name="Sharma",
            email=self.email,
            is_verified=True,
            is_active=True,
            role="learner"
        )
        self.user.set_password("Password@2026!")
        db.session.add(self.user)
        db.session.commit()

        # Enrol in GDP
        self.course = Course.query.filter_by(slug='good-documentation-practices').first()
        self.enrolment = Enrolment(
            user_id=self.user.id,
            course_id=self.course.id,
            certificate_option='paid'
        )
        db.session.add(self.enrolment)
        db.session.commit()

        # Log in
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['user_name'] = self.user.full_name
            sess['user_role'] = self.user.role

    def tearDown(self):
        self.ctx.pop()

    def test_req_1_practice_mcq_response_locking(self):
        """Req 1: Once submitted, response cannot be changed or overwritten."""
        mcq = MCQ.query.filter_by(course_id=self.course.id, type='practice').first()
        self.assertIsNotNone(mcq)

        # First submission
        res1 = self.client.post('/elearning/api/practice/submit', json={
            'mcq_id': mcq.id,
            'selected_option': 'A'
        })
        data1 = res1.get_json()
        self.assertTrue(data1['success'])

        # Attempt to change response to 'B'
        res2 = self.client.post('/elearning/api/practice/submit', json={
            'mcq_id': mcq.id,
            'selected_option': 'B'
        })
        data2 = res2.get_json()
        self.assertTrue(data2['success'])
        # Vetted response should be preserved as 'A'
        from elearning.models import PracticeMCQResponse
        resp_obj = PracticeMCQResponse.query.filter_by(enrolment_id=self.enrolment.id, mcq_id=mcq.id).first()
        self.assertEqual(resp_obj.selected_option, 'A')

    def test_req_2_and_7_completion_and_cycle_reset(self):
        """Req 2 & 7: Reaching/completing slides unlocks test; reviewing slides resets exhausted 3 attempts."""
        total_slides = Slide.query.filter_by(course_id=self.course.id, is_active=True).count()
        
        # Simulate learner reaching final slide
        self.enrolment.current_slide_number = total_slides
        self.enrolment.highest_slide_completed = total_slides
        self.enrolment.slides_completed = True
        self.enrolment.attempts_used_in_current_cycle = 3  # Exhausted 3 attempts
        self.enrolment.presentation_completions_count = 1
        db.session.commit()

        # Calling test_start or take_test on completed presentation should reset attempts to 0 and unlock cycle 2
        res = self.client.get(f'/elearning/course/{self.course.slug}/test', follow_redirects=False)
        self.enrolment = db.session.get(Enrolment, self.enrolment.id)
        self.assertEqual(self.enrolment.attempts_used_in_current_cycle, 0)
        self.assertEqual(self.enrolment.presentation_completions_count, 2)
        # Should redirect directly to take_test
        self.assertEqual(res.status_code, 302)
        self.assertIn('/test/take', res.location)

    def test_req_3_incorrect_responses_review(self):
        """Req 3: Post test submission, incorrect responses, correct answers, and explanations are shown."""
        self.enrolment.slides_completed = True
        self.enrolment.highest_slide_completed = 233
        self.enrolment.attempts_used_in_current_cycle = 0
        db.session.commit()

        # Start test (GET)
        res_get = self.client.get(f'/elearning/course/{self.course.slug}/test/take')
        self.assertEqual(res_get.status_code, 200)

        # Get question IDs from session
        with self.client.session_transaction() as sess:
            session_key = f"test_q_ids_{self.enrolment.id}_1"
            q_ids = sess.get(session_key)

        self.assertIsNotNone(q_ids)
        self.assertEqual(len(q_ids), 20)

        # Submit test with 10 correct and 10 incorrect
        mcqs = {m.id: m for m in MCQ.query.filter(MCQ.id.in_(q_ids)).all()}
        form_data = {}
        for idx, q_id in enumerate(q_ids):
            correct_opt = mcqs[q_id].correct_option
            if idx < 10:
                form_data[f"q_{q_id}"] = correct_opt  # Correct
            else:
                wrong_opt = 'B' if correct_opt != 'B' else 'C'
                form_data[f"q_{q_id}"] = wrong_opt  # Incorrect

        res_post = self.client.post(f'/elearning/course/{self.course.slug}/test/take', data=form_data, follow_redirects=True)
        self.assertEqual(res_post.status_code, 200)
        # Check that result page displays test not passed, and includes review section
        self.assertIn(b'Test Not Passed', res_post.data)
        self.assertIn(b'See Incorrect Responses', res_post.data)
        self.assertIn(b'Review Incorrect Questions', res_post.data)

    def test_req_4_terminate_revision_and_sequence(self):
        """Req 4: Learner can terminate revision and take test in sequence (e.g. Attempt 2)."""
        self.enrolment.slides_completed = True
        self.enrolment.highest_slide_completed = 233
        self.enrolment.attempts_used_in_current_cycle = 1  # 1 attempt failed, attempt 2 pending
        db.session.commit()

        # Access slide player
        res_slide = self.client.get(f'/elearning/course/{self.course.slug}/player?slide_num=10')
        self.assertEqual(res_slide.status_code, 200)
        self.assertIn(b'Terminate & Go to Test (Attempt 2 of 3)', res_slide.data)

    def test_req_5_minimum_75_percent_novel_questions(self):
        """Req 5: Minimum 75% of questions are different from previous attempt."""
        self.enrolment.slides_completed = True
        self.enrolment.highest_slide_completed = 233
        self.enrolment.attempts_used_in_current_cycle = 0
        db.session.commit()

        # Attempt 1
        self.client.get(f'/elearning/course/{self.course.slug}/test/take')
        with self.client.session_transaction() as sess:
            q_ids_att1 = set(sess[f"test_q_ids_{self.enrolment.id}_1"])

        # Submit attempt 1
        form_data = {f"q_{qid}": 'A' for qid in q_ids_att1}
        self.client.post(f'/elearning/course/{self.course.slug}/test/take', data=form_data, follow_redirects=True)

        # Attempt 2
        self.client.get(f'/elearning/course/{self.course.slug}/test/take')
        with self.client.session_transaction() as sess:
            q_ids_att2 = set(sess[f"test_q_ids_{self.enrolment.id}_2"])

        # Novel questions in attempt 2
        novel_questions = q_ids_att2 - q_ids_att1
        diff_pct = (len(novel_questions) / 20.0) * 100.0
        self.assertGreaterEqual(diff_pct, 75.0, f"Expected >= 75% novel questions, got {diff_pct}% ({len(novel_questions)}/20)")

    def test_req_6_revise_slides_option_after_second_failed_attempt(self):
        """Req 6: After second failed attempt, learner can go through slides."""
        self.enrolment.slides_completed = True
        self.enrolment.highest_slide_completed = 233
        self.enrolment.attempts_used_in_current_cycle = 2  # 2 attempts failed
        db.session.commit()

        # Result page should show both Revise Slides and Attempt 3
        res = self.client.get(f'/elearning/course/{self.course.slug}/test/summary')
        self.assertEqual(res.status_code, 302)  # No passed attempt, redirects to test_start

        # Start slide player from slide 1
        res_player = self.client.get(f'/elearning/course/{self.course.slug}/player?slide_num=1')
        self.assertEqual(res_player.status_code, 200)
        self.assertIn(b'Page 1', res_player.data)

    def test_req_9_upload_payment_file_validation(self):
        """Req 9: Only JPG, PNG, PDF, and HEIC files are allowed for payment proof."""
        ref_code = f"REF_TEST_UPLOAD_{int(time.time() * 1000)}"
        order = PaymentOrder(
            enrolment_id=self.enrolment.id,
            user_id=self.user.id,
            course_id=self.course.id,
            order_reference=ref_code,
            expected_amount=588.82,
            currency="INR",
            status="pending"
        )
        db.session.add(order)
        db.session.commit()

        # Reject invalid file extension (.exe or .docx)
        bad_file = (io.BytesIO(b"fake data"), "malicious.exe")
        res_bad = self.client.post(f'/elearning/payment/order/{order.order_reference}/submit', data={
            'proof_file': bad_file,
            'amount_paid': '588.82',
            'payment_mode': 'UPI',
            'payment_date': '2026-11-24',
            'transaction_reference': f'UTR_{int(time.time() * 1000)}_1',
            'payer_name': 'Pooja Sharma',
            'is_draft': '0'
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn(b'Only JPG, PNG, PDF, and HEIC', res_bad.data)

        # Accept valid file extension (.png)
        good_file = (io.BytesIO(b"\x89PNG\r\n\x1a\nfake png data"), "receipt.png")
        res_good = self.client.post(f'/elearning/payment/order/{order.order_reference}/submit', data={
            'proof_file': good_file,
            'amount_paid': '588.82',
            'payment_mode': 'UPI',
            'payment_date': '2026-11-24',
            'transaction_reference': f'UTR_{int(time.time() * 1000)}_2',
            'payer_name': 'Pooja Sharma',
            'is_draft': '0'
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn(b'Payment submission received', res_good.data)


if __name__ == '__main__':
    unittest.main()
