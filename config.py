import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ytaltech-secure-elearning-secret-key-2026-prod-grade')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'ytaltech_elearning.db')}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload directories
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    RECEIPTS_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'receipts')
    SLIDES_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'slides')
    CERTIFICATES_FOLDER = os.path.join(BASE_DIR, 'static', 'certificates')
    INVOICES_FOLDER = os.path.join(BASE_DIR, 'static', 'invoices')
    
    # Max file upload size (10 MB)
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    
    # Allowed file extensions
    ALLOWED_PROOF_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'heic'}
    ALLOWED_SLIDE_EXTENSIONS = {'pptx', 'ppt', 'pdf', 'png', 'jpg', 'jpeg'}
    
    # Course Pricing Configuration
    PRICE_INR_BASE = 499.00
    GST_PERCENT = 18.0
    PRICE_INR_TOTAL = round(PRICE_INR_BASE * (1 + GST_PERCENT / 100.0), 2)  # 588.82
    PRICE_USD = 9.49
    
    # Bank & UPI Details for Manual Payment
    COMPANY_NAME = "Ytal Tech Solutions & Services LLP"
    COMPANY_ADDRESS = "103, Parijat Gardens Gulmohar CHS Ltd., Ghodbunder Road, Kasarvadavali, Thane - 400615, Maharashtra, India"
    COMPANY_EMAIL = "contact@ytaltech.com"
    COMPANY_PHONE = "+91 9372571921"
    COMPANY_GSTIN = "27AADFY4241Q1ZL"
    COMPANY_PAN = "AADFY4241Q"
    BANK_NAME = "SBI"
    BANK_BRANCH = "Kasarvadavali branch, Thane"
    BANK_ACCOUNT_NAME = "Ytal Tech Solutions and Services LLP"
    BANK_ACCOUNT_NUMBER = "43028833589"
    BANK_IFSC = "SBIN0061708"
    BANK_ACCOUNT_TYPE = "Current Account"
    UPI_ID = "ytaltechservices@sbi"
    UPI_QR_IMAGE = "elearning/img/sbi_upi_qr_poster.png"
    SAC_CODE = "998314"
    
    # Session & Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() in ['true', '1', 'yes']
    PERMANENT_SESSION_LIFETIME = 7200  # 2 hours session timeout
    
    # SMTP Email Configuration (Outbound Mail Server)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtpout.secureserver.net')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'true').lower() in ['true', '1', 'yes']
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', '1', 'yes']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'contact@ytaltech.com')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', 'Ajayganesh@2024')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Ytal Tech <contact@ytaltech.com>')
    MAIL_TIMEOUT = int(os.environ.get('MAIL_TIMEOUT', 15))

    # Pass rule constants
    PASSING_PERCENTAGE = 80.0
    MAX_ATTEMPTS_PER_CYCLE = 3
    TOTAL_TEST_QUESTIONS = 20
    PRACTICE_POOL_COUNT = 8
    FINAL_POOL_COUNT = 12
    MIN_SLIDE_DWELL_SECONDS = 15
