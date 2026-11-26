import json
from datetime import datetime, timezone
import bcrypt
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    
    # Roles: learner, super_admin, course_admin, content_editor, finance_admin, certificate_admin, support_agent
    role = db.Column(db.String(50), nullable=False, default='learner')
    
    is_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(128), nullable=True)
    reset_password_token = db.Column(db.String(128), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    
    google_id = db.Column(db.String(100), nullable=True, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    
    # Delivery address fields for certificate physical delivery
    house_no = db.Column(db.String(100), nullable=True)
    building = db.Column(db.String(150), nullable=True)
    street = db.Column(db.String(150), nullable=True)
    area = db.Column(db.String(150), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), default='India')
    pincode = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    gstin = db.Column(db.String(30), nullable=True)
    organization_name = db.Column(db.String(200), nullable=True)
    billing_address = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    enrolments = db.relationship('Enrolment', backref='user', lazy=True, cascade='all, delete-orphan')
    payment_orders = db.relationship('PaymentOrder', foreign_keys='PaymentOrder.user_id', backref='user', lazy=True)
    certificates = db.relationship('Certificate', backref='user', lazy=True)
    audit_logs = db.relationship('AuditLog', backref='user', lazy=True)

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join([p.strip() for p in parts if p and p.strip()])

    def set_password(self, password):
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception:
            return False

    def has_role(self, *roles):
        if self.role == 'super_admin':
            return True
        return self.role in roles

    @property
    def has_complete_profile(self):
        return bool(self.first_name and self.last_name and self.age and self.gender)

    @property
    def has_delivery_address(self):
        return bool(self.house_no and self.street and self.city and self.state and self.pincode)

    @property
    def is_international(self):
        if not self.country:
            return False
        return self.country.strip().lower() not in ['india', 'in', 'bharat']


class Course(db.Model):
    __tablename__ = 'courses'
    
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    short_description = db.Column(db.Text, nullable=False)
    overview = db.Column(db.Text, nullable=True)
    estimated_duration = db.Column(db.String(50), default='2 Hours')
    language = db.Column(db.String(50), default='English')
    
    price_inr = db.Column(db.Float, default=499.00)
    gst_rate = db.Column(db.Float, default=0.18)
    price_usd = db.Column(db.Float, default=9.49)
    
    version = db.Column(db.String(20), default='v1.0')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    slides = db.relationship('Slide', backref='course', lazy=True, order_by='Slide.slide_number', cascade='all, delete-orphan')
    mcqs = db.relationship('MCQ', backref='course', lazy=True, cascade='all, delete-orphan')
    enrolments = db.relationship('Enrolment', backref='course', lazy=True, cascade='all, delete-orphan')
    certificates = db.relationship('Certificate', backref='course', lazy=True)

    @property
    def total_price_inr(self):
        return round(self.price_inr * (1 + self.gst_rate), 2)

    @property
    def gst_amount_inr(self):
        return round(self.price_inr * self.gst_rate, 2)


class Slide(db.Model):
    __tablename__ = 'slides'
    
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    slide_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content_html = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    minimum_dwell_seconds = db.Column(db.Integer, default=15)
    has_practice_mcq = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    
    practice_mcqs = db.relationship('MCQ', backref='slide', lazy=True)


class MCQ(db.Model):
    __tablename__ = 'mcqs'
    
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    slide_id = db.Column(db.Integer, db.ForeignKey('slides.id'), nullable=True)
    
    # Type: 'practice' or 'final_test'
    type = db.Column(db.String(20), nullable=False, default='final_test')
    
    # Part: 'A' or 'B' for final assessment question pools
    part = db.Column(db.String(10), nullable=True, default='B')
    
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.Text, nullable=False)
    option_b = db.Column(db.Text, nullable=False)
    option_c = db.Column(db.Text, nullable=False)
    option_d = db.Column(db.Text, nullable=False)
    correct_option = db.Column(db.String(5), nullable=False)  # 'A', 'B', 'C', 'D'
    explanation = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(20), default='medium')
    marks = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)


class Enrolment(db.Model):
    __tablename__ = 'enrolments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    
    # 'paid' (with certificate) or 'free' (without certificate)
    certificate_option = db.Column(db.String(20), nullable=False, default='paid')
    
    current_slide_number = db.Column(db.Integer, default=1)
    highest_slide_completed = db.Column(db.Integer, default=0)
    slides_completed = db.Column(db.Boolean, default=False)
    
    # Attempt management:
    # Learner gets 3 attempts upon completing the presentation cycle.
    # If all 3 attempts fail, presentation_completions_count must be incremented by going through the presentation again.
    presentation_completions_count = db.Column(db.Integer, default=0)
    attempts_used_in_current_cycle = db.Column(db.Integer, default=0)
    
    total_time_spent_seconds = db.Column(db.Integer, default=0)
    enrolled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    
    slide_logs = db.relationship('SlideViewLog', backref='enrolment', lazy=True, cascade='all, delete-orphan')
    practice_responses = db.relationship('PracticeMCQResponse', backref='enrolment', lazy=True, cascade='all, delete-orphan')
    test_attempts = db.relationship('TestAttempt', backref='enrolment', lazy=True, cascade='all, delete-orphan')
    payment_orders = db.relationship('PaymentOrder', backref='enrolment', lazy=True, cascade='all, delete-orphan')
    certificate = db.relationship('Certificate', backref='enrolment', uselist=False, lazy=True)

    @property
    def track_display_name(self):
        if self.certificate_option == 'paid':
            return 'Course with certificate'
        return 'Course without certificate'

    @property
    def remaining_attempts_in_cycle(self):
        return max(0, 3 - self.attempts_used_in_current_cycle)

    @property
    def can_take_test(self):
        # Must have completed all slides and have remaining attempts in current cycle
        return self.slides_completed and self.attempts_used_in_current_cycle < 3

    @property
    def has_passed_test(self):
        for att in self.test_attempts:
            if att.passed:
                return True
        return False

    @property
    def latest_passed_attempt(self):
        for att in sorted(self.test_attempts, key=lambda a: a.id, reverse=True):
            if att.passed:
                return att
        return None

    @property
    def latest_payment_order(self):
        if self.payment_orders:
            return sorted(self.payment_orders, key=lambda o: o.id, reverse=True)[0]
        return None

    @property
    def is_payment_approved(self):
        order = self.latest_payment_order
        return order is not None and order.status in [
            'verified_approved', 'certificate_issued',
            'certificate_dispatched', 'certificate_delivered'
        ]

    @property
    def free_upgrade_deadline(self):
        """
        If enrolled without certificate and passed test, learner has 1 month (30 days) from passing date to upgrade.
        """
        passed = self.latest_passed_attempt
        if passed:
            from datetime import timedelta
            ref_date = passed.submitted_at or passed.started_at
            if ref_date:
                return ref_date + timedelta(days=30)
        return None

    @property
    def is_free_upgrade_expired(self):
        deadline = self.free_upgrade_deadline
        if deadline:
            now = datetime.now(timezone.utc)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            return now > deadline
        return False

    @property
    def free_upgrade_days_remaining(self):
        deadline = self.free_upgrade_deadline
        if deadline:
            now = datetime.now(timezone.utc)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            diff = deadline - now
            return max(0, diff.days)
        return None


class SlideViewLog(db.Model):
    __tablename__ = 'slide_view_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    enrolment_id = db.Column(db.Integer, db.ForeignKey('enrolments.id'), nullable=False)
    slide_id = db.Column(db.Integer, db.ForeignKey('slides.id'), nullable=False)
    slide_number = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    time_spent_seconds = db.Column(db.Integer, default=0)
    ip_address = db.Column(db.String(45), nullable=True)


class PracticeMCQResponse(db.Model):
    __tablename__ = 'practice_mcq_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    enrolment_id = db.Column(db.Integer, db.ForeignKey('enrolments.id'), nullable=False)
    mcq_id = db.Column(db.Integer, db.ForeignKey('mcqs.id'), nullable=False)
    selected_option = db.Column(db.String(5), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    attempted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class TestAttempt(db.Model):
    __tablename__ = 'test_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    enrolment_id = db.Column(db.Integer, db.ForeignKey('enrolments.id'), nullable=False)
    attempt_number = db.Column(db.Integer, nullable=False)
    presentation_cycle = db.Column(db.Integer, default=1)
    
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    submitted_at = db.Column(db.DateTime, nullable=True)
    
    score = db.Column(db.Integer, default=0)  # Correct count out of 20
    percentage = db.Column(db.Float, default=0.0)
    passed = db.Column(db.Boolean, default=False)
    
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    questions_data = db.Column(db.Text, nullable=True)  # JSON dump of questions, shuffled choices, user answers

    def get_questions_data(self):
        if not self.questions_data:
            return []
        try:
            return json.loads(self.questions_data)
        except Exception:
            return []


class PaymentOrder(db.Model):
    __tablename__ = 'payment_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_reference = db.Column(db.String(64), unique=True, nullable=False, index=True)
    enrolment_id = db.Column(db.Integer, db.ForeignKey('enrolments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    
    expected_amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='INR')
    gst_amount = db.Column(db.Float, default=0.0)
    
    # Status:
    # 'pending_submission', 'under_review', 'verified_approved', 'rejected',
    # 'additional_info_required', 'refund_requested', 'refund_processed',
    # 'certificate_issued', 'certificate_dispatched', 'certificate_delivered'
    status = db.Column(db.String(50), default='pending_submission', index=True)
    
    amount_paid = db.Column(db.Float, nullable=True)
    payment_mode = db.Column(db.String(50), nullable=True)  # 'UPI', 'NEFT/RTGS/IMPS', 'Cheque', 'Demand Draft', 'Other'
    payment_date = db.Column(db.DateTime, nullable=True)
    transaction_reference = db.Column(db.String(100), nullable=True, index=True)  # UTR / Bank Ref / Cheque No
    payer_name = db.Column(db.String(150), nullable=True)
    payer_account_upi = db.Column(db.String(150), nullable=True)
    proof_file_path = db.Column(db.String(500), nullable=True)
    learner_remarks = db.Column(db.Text, nullable=True)
    
    # Customer Billing & GSTIN Details (for GST-Compliant Tax Invoice)
    customer_gstin = db.Column(db.String(30), nullable=True)
    customer_org_name = db.Column(db.String(200), nullable=True)
    customer_billing_address = db.Column(db.Text, nullable=True)
    customer_state = db.Column(db.String(100), nullable=True)
    
    admin_notes = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    additional_info_notes = db.Column(db.Text, nullable=True)
    
    verified_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    
    dual_approved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    dual_approved_at = db.Column(db.DateTime, nullable=True)
    
    submitted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    course = db.relationship('Course', backref='payment_orders')
    verifier = db.relationship('User', foreign_keys=[verified_by_user_id], backref='verified_payments')
    dual_approver = db.relationship('User', foreign_keys=[dual_approved_by_user_id], backref='dual_approved_payments')

    @property
    def is_international(self):
        return self.currency != 'INR'

    @property
    def region_label(self):
        return 'International' if self.is_international else 'India'

    @property
    def base_amount(self):
        if self.currency == 'INR':
            return round((self.amount_paid or self.expected_amount) - (self.gst_amount or 0.0), 2)
        return round(self.amount_paid or self.expected_amount, 2)

    @property
    def total_amount(self):
        return round(self.amount_paid or self.expected_amount, 2)


class Certificate(db.Model):
    __tablename__ = 'certificates'
    
    id = db.Column(db.Integer, primary_key=True)
    certificate_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    enrolment_id = db.Column(db.Integer, db.ForeignKey('enrolments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    payment_order_id = db.Column(db.Integer, db.ForeignKey('payment_orders.id'), nullable=True)
    
    issue_date = db.Column(db.Date, nullable=False)
    score_percentage = db.Column(db.Float, default=100.0)
    course_version = db.Column(db.String(20), default='v1.0')
    status = db.Column(db.String(20), default='valid')  # 'valid', 'revoked'
    
    digital_signature_hash = db.Column(db.String(128), nullable=False)
    pdf_file_path = db.Column(db.String(500), nullable=True)
    qr_code_path = db.Column(db.String(500), nullable=True)
    verification_url = db.Column(db.String(500), nullable=True)
    
    # Physical dispatch details
    dispatch_status = db.Column(db.String(50), default='pending_dispatch')  # 'pending_dispatch', 'dispatched', 'delivered', 'not_applicable'
    courier_name = db.Column(db.String(100), nullable=True)
    tracking_number = db.Column(db.String(100), nullable=True)
    dispatched_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    
    revocation_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    payment_order = db.relationship('PaymentOrder', backref='certificate', uselist=False)

    @property
    def is_international(self):
        if self.user and self.user.is_international:
            return True
        if self.payment_order and self.payment_order.currency != 'INR':
            return True
        return False


class CertificateComplaint(db.Model):
    __tablename__ = 'certificate_complaints'
    
    id = db.Column(db.Integer, primary_key=True)
    certificate_id_reported = db.Column(db.String(64), nullable=True)
    reporter_name = db.Column(db.String(100), nullable=False)
    reporter_email = db.Column(db.String(255), nullable=False)
    reporter_phone = db.Column(db.String(20), nullable=True)
    issue_description = db.Column(db.Text, nullable=False)
    attachment_path = db.Column(db.String(500), nullable=True)
    consent_given = db.Column(db.Boolean, default=True)
    
    status = db.Column(db.String(50), default='open')  # 'open', 'under_investigation', 'resolved', 'closed'
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def get(cls, key, default=None):
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting and setting.value is not None else default

    @classmethod
    def set(cls, key, value, description=None):
        setting = cls.query.filter_by(key=key).first()
        if not setting:
            setting = cls(key=key, value=value, description=description)
            db.session.add(setting)
        else:
            setting.value = value
            if description:
                setting.description = description
        db.session.commit()


class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='sent')
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
