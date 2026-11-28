from datetime import datetime, timezone
from elearning.models import db, User, Course, Slide, MCQ, SystemSetting
from elearning.seed_from_pptx import import_pptx_presentations

def seed_database():
    """Initializes default system settings, roles, admin users, and official presentations."""
    
    # 1. System Settings
    settings_data = {
        'company_name': ('Ytal Tech Solutions & Services LLP', 'Registered company name'),
        'company_address': ('103, Parijat Gardens Gulmohar CHS Ltd., Ghodbunder Road, Kasarvadavali, Thane - 400615, Maharashtra, India', 'Registered office address'),
        'company_email': ('contact@ytaltech.com', 'Official contact email'),
        'company_phone': ('+91 9372571921', 'Official phone / WhatsApp support'),
        'company_gstin': ('27AADFY4241Q1ZL', 'Official GSTIN number'),
        'company_pan': ('AADFY4241Q', 'Official PAN number'),
        'bank_name': ('SBI', 'Company bank name'),
        'bank_branch': ('Kasarvadavali branch, Thane', 'Branch name'),
        'bank_account_name': ('Ytal Tech Solutions and Services LLP', 'Account beneficiary name'),
        'bank_account_number': ('43028833589', 'Current account number'),
        'bank_ifsc': ('SBIN0061708', 'IFSC Code'),
        'bank_account_type': ('Current Account', 'Type of bank account'),
        'upi_id': ('ytaltechservices@sbi', 'Official UPI ID for manual payment'),
        'upi_qr_image': ('elearning/img/sbi_upi_qr_poster.png', 'Official UPI QR code poster path'),
        'sac_code': ('998314', 'Services Accounting Code (SAC) for Tax Invoices'),
        'payment_verification_timeline': ('Within 12 to 24 business hours', 'Expected timeline for payment review'),
        'gst_percent': ('18.0', 'Applicable GST percentage for Indian learners'),
        'price_inr_base': ('499.00', 'Base course fee in INR'),
        'price_usd': ('9.49', 'Course fee in USD for international learners'),
        'certificate_validity_years': ('Lifetime', 'Digital certificate validity period')
    }
    
    for key, (val, desc) in settings_data.items():
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            db.session.add(SystemSetting(key=key, value=val, description=desc))
        elif key in ['company_gstin', 'company_pan', 'bank_name', 'bank_branch', 'bank_account_name', 'bank_account_number', 'bank_ifsc', 'upi_id', 'upi_qr_image', 'sac_code', 'price_inr_base']:
            # Ensure official credentials from SBI UPI PDF & docx are updated
            setting.value = val
            setting.description = desc
    
    # 2. Seed Administrative Users (Credentials injected via environment or generated securely)
    import secrets
    import os
    
    seed_users = [
        {
            'email': 'admin@ytaltech.com',
            'first_name': 'Dr. Ganesh',
            'middle_name': '',
            'last_name': 'Divekar',
            'role': 'super_admin',
            'age': 45,
            'gender': 'Male',
            'env_pwd_key': 'SEED_ADMIN_PASSWORD'
        },
        {
            'email': 'finance@ytaltech.com',
            'first_name': 'Priyanka',
            'middle_name': 'Ganesh',
            'last_name': 'Divekar',
            'role': 'finance_admin',
            'age': 40,
            'gender': 'Female',
            'env_pwd_key': 'SEED_FINANCE_PASSWORD'
        },
        {
            'email': 'courseadmin@ytaltech.com',
            'first_name': 'Ajay',
            'middle_name': '',
            'last_name': 'Kondekar',
            'role': 'course_admin',
            'age': 46,
            'gender': 'Male',
            'env_pwd_key': 'SEED_COURSEADMIN_PASSWORD'
        }
    ]
    
    for u_info in seed_users:
        if not User.query.filter_by(email=u_info['email']).first():
            # Never hardcode passwords in source code
            initial_pwd = os.environ.get(u_info['env_pwd_key'])
            if not initial_pwd:
                initial_pwd = secrets.token_urlsafe(16)
                print(f"[SECURITY NOTICE] Initialized {u_info['email']} with generated credential: {initial_pwd}")
                
            user = User(
                email=u_info['email'],
                first_name=u_info['first_name'],
                middle_name=u_info['middle_name'],
                last_name=u_info['last_name'],
                age=u_info['age'],
                gender=u_info['gender'],
                role=u_info['role'],
                is_verified=True,
                is_active=True
            )
            user.set_password(initial_pwd)
            db.session.add(user)
            
    db.session.commit()
    
    # 3. Seed Courses, Slides, and MCQs directly from the official PowerPoint presentations
    if Slide.query.count() < 100:
        import_pptx_presentations()
    
    print("Database seeding completed successfully!")
