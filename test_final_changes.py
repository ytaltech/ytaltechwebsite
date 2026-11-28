import os
os.environ['TESTING'] = 'true'
os.environ['FLASK_DEBUG'] = 'false'

import unittest
import re
from app import app
from elearning.models import db, User, Course, Enrolment, Slide, MCQ, TestAttempt

class TestFinalChanges(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.client = app.test_client()
        self.user = User.query.filter_by(role='learner').first()
        if not self.user:
            self.user = User(
                email='test_learner_fc@example.com',
                first_name='Rahul',
                last_name='Sharma',
                role='learner',
                age=28,
                gender='Male',
                is_verified=True,
                is_active=True
            )
            self.user.set_password('Learner@2026!')
            db.session.add(self.user)
            db.session.commit()

        self.course = Course.query.filter_by(slug='good-documentation-practices').first()
        self.enrolment = Enrolment.query.filter_by(user_id=self.user.id, course_id=self.course.id).first()
        if not self.enrolment:
            self.enrolment = Enrolment(
                user_id=self.user.id,
                course_id=self.course.id,
                certificate_option='paid'
            )
            db.session.add(self.enrolment)
            db.session.commit()
            
        # Reset attempts for test
        TestAttempt.query.filter_by(enrolment_id=self.enrolment.id).delete()
        total_slides = Slide.query.filter_by(course_id=self.course.id).count()
        self.enrolment.highest_slide_completed = total_slides
        self.enrolment.slides_completed = True
        self.enrolment.attempts_used_in_current_cycle = 0
        self.enrolment.presentation_completions_count = 1
        db.session.commit()

    def tearDown(self):
        self.ctx.pop()

    def test_registration_note(self):
        """Item 3: Registration page has note about email reflecting on certificate."""
        res = self.client.get('/elearning/register')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("This email ID will reflect on your final course certificate", html)

    def test_gcp_slide_count_and_slide_190(self):
        """Item 1 & 2: GCP has 191 slides, and Slide 190 has updated last bullet point."""
        gcp = Course.query.filter_by(slug='ich-gcp').first()
        self.assertEqual(len(gcp.slides), 191)
        s190 = Slide.query.filter_by(course_id=gcp.id, slide_number=190).first()
        self.assertIsNotNone(s190)
        self.assertEqual(s190.title, "References & Regulatory Guidelines")
        self.assertIn("The ICH E6(R3) structure, Principles, Annex 1 sections and Data Governance requirements", s190.content_html)
        s191 = Slide.query.filter_by(course_id=gcp.id, slide_number=191).first()
        self.assertIn("COURSE COMPLETION & CERTIFICATION", s191.title)
        s192 = Slide.query.filter_by(course_id=gcp.id, slide_number=192).first()
        self.assertIsNone(s192)

    def test_gdp_slide_69_date_format(self):
        """Item 4: GDP slide 69 has updated date format text."""
        s69 = Slide.query.filter_by(course_id=self.course.id, slide_number=69).first()
        self.assertIsNotNone(s69)
        self.assertIn("preferred format is DD-MMM-YYYY i.e. 03-Apr-2026", s69.content_html)

    def test_final_assessment_workflow_and_review_options(self):
        """Item 5: Test examination workflow has Review and Submit options, free navigation."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user.id
            sess['_user_remember'] = 'clear'
            
        res = self.client.get(f'/elearning/course/{self.course.slug}/test/take')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        
        self.assertIn('name="question_ids_list"', html)
        self.assertIn('Go through all responses', html)
        self.assertIn('Submit the responses', html)
        self.assertIn('reviewAllModal', html)

        # Extract question IDs
        match = re.search(r'name="question_ids_list" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        q_ids = [int(x) for x in match.group(1).split(',')]
        self.assertEqual(len(q_ids), 20)

        # Answer 18 questions correctly, 2 incorrectly (Score 18/20 = 90% PASSED)
        mcq_objs = {q.id: q for q in MCQ.query.filter(MCQ.id.in_(q_ids)).all()}
        form_data = {'question_ids_list': match.group(1), 'attempt_number': '1'}
        for idx, qid in enumerate(q_ids):
            correct = mcq_objs[qid].correct_option
            if idx < 18:
                form_data[f'q_{qid}'] = correct
            else:
                form_data[f'q_{qid}'] = 'A' if correct != 'A' else 'B'

        # Submit POST
        res_post = self.client.post(f'/elearning/course/{self.course.slug}/test/take', data=form_data, follow_redirects=True)
        self.assertEqual(res_post.status_code, 200)
        result_html = res_post.get_data(as_text=True)
        self.assertIn('You have successfully passed the test!', result_html)
        self.assertIn('Score: 90.0% (PASSED)', result_html)

        # Item 6: Incorrect responses option on passed test
        self.assertIn('See Incorrect Responses (2) for Revision', result_html)

        # Item 7: Slide player in revision mode has Terminate & Go to Certificate Claim
        res_player = self.client.get(f'/elearning/course/{self.course.slug}/player/1')
        self.assertEqual(res_player.status_code, 200)
        player_html = res_player.get_data(as_text=True)
        self.assertIn('Terminate & Go to Certificate Claim', player_html)
        self.assertIn('/test/summary', player_html)

if __name__ == '__main__':
    unittest.main()
