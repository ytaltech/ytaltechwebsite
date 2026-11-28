import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from .env file with built-in fallback parser
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    _env_file = os.path.join(BASE_DIR, '.env')
    if os.path.exists(_env_file):
        try:
            with open(_env_file, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith('#') and '=' in _line:
                        _k, _v = _line.split('=', 1)
                        _k, _v = _k.strip(), _v.strip()
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v.strip('"').strip("'")
        except Exception:
            pass

class Config:
    # Secret Key: Strictly read from environment (.env). Falls back to ephemeral random key if omitted.
    SECRET_KEY = os.environ.get('SECRET_KEY') or __import__('secrets').token_hex(32)
    # Database Configuration: Strictly isolate test runs from live production database
    if os.environ.get('TESTING') == 'true' or os.environ.get('FLASK_ENV') == 'testing':
        _db_url = os.environ.get('TEST_DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'test_isolated.db')}")
    else:
        _db_url = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'ytaltech_elearning.db')}")
        
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif _db_url.startswith("postgresql://") and not _db_url.startswith("postgresql+"):
        _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Database connection pool sizing for multi-worker WSGI concurrency
    DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', 5))
    DB_MAX_OVERFLOW = int(os.environ.get('DB_MAX_OVERFLOW', 5))
    DB_POOL_TIMEOUT = int(os.environ.get('DB_POOL_TIMEOUT', 30))
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': DB_POOL_SIZE,
        'max_overflow': DB_MAX_OVERFLOW,
        'pool_timeout': DB_POOL_TIMEOUT
    }
    
    # Secure Storage directories (Stored OUTSIDE static/ to prevent direct unauthenticated Nginx access)
    STORAGE_ROOT = os.environ.get('STORAGE_ROOT', os.path.join(BASE_DIR, 'storage'))
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(STORAGE_ROOT, 'uploads'))
    RECEIPTS_UPLOAD_FOLDER = os.environ.get('RECEIPTS_UPLOAD_FOLDER', os.path.join(UPLOAD_FOLDER, 'receipts'))
    SLIDES_UPLOAD_FOLDER = os.environ.get('SLIDES_UPLOAD_FOLDER', os.path.join(UPLOAD_FOLDER, 'slides'))
    CERTIFICATES_FOLDER = os.environ.get('CERTIFICATES_FOLDER', os.path.join(STORAGE_ROOT, 'certificates'))
    INVOICES_FOLDER = os.environ.get('INVOICES_FOLDER', os.path.join(STORAGE_ROOT, 'invoices'))
    
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
    _is_debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 'yes']
    _cookie_secure_env = os.environ.get('SESSION_COOKIE_SECURE')
    if _cookie_secure_env is not None:
        SESSION_COOKIE_SECURE = _cookie_secure_env.lower() in ['true', '1', 'yes']
    else:
        SESSION_COOKIE_SECURE = not _is_debug
    PERMANENT_SESSION_LIFETIME = 7200  # 2 hours session timeout
    
    # SMTP Email Configuration (Outbound Mail Server)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtpout.secureserver.net')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'true').lower() in ['true', '1', 'yes']
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', '1', 'yes']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'contact@ytaltech.com')
    # Outbound SMTP password: Must strictly be loaded from environment (.env)
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Ytal Tech <contact@ytaltech.com>')
    MAIL_TIMEOUT = int(os.environ.get('MAIL_TIMEOUT', 15))
    MAIL_ASYNC = os.environ.get('MAIL_ASYNC', 'true').lower() in ['true', '1', 'yes']

    # Pass rule constants
    PASSING_PERCENTAGE = 80.0
    MAX_ATTEMPTS_PER_CYCLE = 3
    TOTAL_TEST_QUESTIONS = 20
    PRACTICE_POOL_COUNT = 8
    FINAL_POOL_COUNT = 12
    MIN_SLIDE_DWELL_SECONDS = 15

    # Google OAuth 2.0 Configuration
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI')
