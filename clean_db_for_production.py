import os
import sqlite3
from app import app
from elearning.models import (
    db, User, PaymentOrder, Enrolment, TestAttempt, Certificate,
    CertificateComplaint, SlideViewLog, PracticeMCQResponse, AuditLog
)

ALLOWED_EMAILS = [
    'admin@ytaltech.com',
    'finance@ytaltech.com',
    'courseadmin@ytaltech.com',
    'learner@example.com'
]

def clean_postgres():
    print("--- Cleaning PostgreSQL Database ---")
    with app.app_context():
        extra_users = User.query.filter(~User.email.in_(ALLOWED_EMAILS)).all()
        extra_user_ids = [u.id for u in extra_users]
        extra_user_emails = [u.email for u in extra_users]
        if extra_user_ids:
            print(f"Purging {len(extra_user_ids)} non-production users: {extra_user_ids}")
            enrolment_ids = [e.id for e in Enrolment.query.filter(Enrolment.user_id.in_(extra_user_ids)).all()]
            if enrolment_ids:
                PracticeMCQResponse.query.filter(PracticeMCQResponse.enrolment_id.in_(enrolment_ids)).delete(synchronize_session=False)
                SlideViewLog.query.filter(SlideViewLog.enrolment_id.in_(enrolment_ids)).delete(synchronize_session=False)
                TestAttempt.query.filter(TestAttempt.enrolment_id.in_(enrolment_ids)).delete(synchronize_session=False)
            CertificateComplaint.query.filter(CertificateComplaint.reporter_email.in_(extra_user_emails)).delete(synchronize_session=False)
            Certificate.query.filter(Certificate.user_id.in_(extra_user_ids)).delete(synchronize_session=False)
            PaymentOrder.query.filter(PaymentOrder.user_id.in_(extra_user_ids)).delete(synchronize_session=False)
            if enrolment_ids:
                Enrolment.query.filter(Enrolment.id.in_(enrolment_ids)).delete(synchronize_session=False)
            AuditLog.query.filter(AuditLog.user_id.in_(extra_user_ids)).delete(synchronize_session=False)
            User.query.filter(User.id.in_(extra_user_ids)).delete(synchronize_session=False)
            db.session.commit()
            print("PostgreSQL cleanup committed.")
        else:
            print("PostgreSQL already clean.")
        remaining = User.query.all()
        print("Active PostgreSQL Users:", [(u.id, u.email, u.role) for u in remaining])

def clean_sqlite():
    db_path = 'ytaltech_elearning.db'
    if not os.path.exists(db_path):
        return
    print("\n--- Cleaning SQLite Database ---")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, email, role FROM users WHERE email NOT IN (?, ?, ?, ?)", tuple(ALLOWED_EMAILS))
    extras = c.fetchall()
    if extras:
        extra_ids = [x[0] for x in extras]
        extra_emails = [x[1] for x in extras]
        print(f"Purging {len(extra_ids)} SQLite non-production users: {extra_ids}")
        placeholders_ids = ','.join(['?'] * len(extra_ids))
        placeholders_emails = ','.join(['?'] * len(extra_emails))
        
        c.execute(f"DELETE FROM practice_mcq_responses WHERE enrolment_id IN (SELECT id FROM enrolments WHERE user_id IN ({placeholders_ids}))", extra_ids)
        c.execute(f"DELETE FROM slide_view_logs WHERE enrolment_id IN (SELECT id FROM enrolments WHERE user_id IN ({placeholders_ids}))", extra_ids)
        c.execute(f"DELETE FROM test_attempts WHERE enrolment_id IN (SELECT id FROM enrolments WHERE user_id IN ({placeholders_ids}))", extra_ids)
        c.execute(f"DELETE FROM certificate_complaints WHERE reporter_email IN ({placeholders_emails})", extra_emails)
        c.execute(f"DELETE FROM certificates WHERE user_id IN ({placeholders_ids})", extra_ids)
        c.execute(f"DELETE FROM payment_orders WHERE user_id IN ({placeholders_ids})", extra_ids)
        c.execute(f"DELETE FROM enrolments WHERE user_id IN ({placeholders_ids})", extra_ids)
        c.execute(f"DELETE FROM audit_logs WHERE user_id IN ({placeholders_ids})", extra_ids)
        c.execute(f"DELETE FROM users WHERE id IN ({placeholders_ids})", extra_ids)
        conn.commit()
        print("SQLite cleanup committed.")
    else:
        print("SQLite already clean.")
    c.execute("SELECT id, email, role FROM users")
    print("Active SQLite Users:", c.fetchall())
    conn.close()

if __name__ == '__main__':
    clean_postgres()
    clean_sqlite()
