import os
import re
import hmac
import hashlib
import uuid
import time
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import email.utils
from datetime import datetime, timezone
from collections import defaultdict
from urllib.parse import urlparse, urljoin
from flask import request, session, current_app, url_for
from werkzeug.utils import secure_filename
import qrcode
from PIL import Image

# ReportLab imports for Certificate & Invoice Generation
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from concurrent.futures import ThreadPoolExecutor

from elearning.models import db, EmailLog, AuditLog, SystemSetting, RateLimitRecord

# Global thread pool for asynchronous background email dispatch (non-blocking WSGI)
_email_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='ytal_email')

# In-memory rate limiter fallback (structure: { key: [timestamps] })
_rate_limits = defaultdict(list)

def check_rate_limit(key, max_attempts=5, window_seconds=60):
    """
    Sliding-window rate limiter for sensitive endpoints.
    Uses database-backed storage (RateLimitRecord) to synchronize limits across
    all multi-worker WSGI processes (Gunicorn, Waitress, uWSGI).
    Gracefully falls back to an in-memory sliding window if database is unavailable.
    """
    if current_app and current_app.config.get('TESTING'):
        return True
    
    now = time.time()
    cutoff = now - window_seconds
    
    # 1. Primary: Database-backed distributed rate limiting across all WSGI workers
    try:
        valid_count = RateLimitRecord.query.filter(
            RateLimitRecord.key == key,
            RateLimitRecord.timestamp >= cutoff
        ).count()
        
        if valid_count >= max_attempts:
            return False
            
        record = RateLimitRecord(key=key, timestamp=now)
        db.session.add(record)
        db.session.commit()
        
        # Periodic pruning of expired timestamps (5% chance on request)
        import random
        if random.random() < 0.05:
            try:
                prune_cutoff = now - 3600
                RateLimitRecord.query.filter(RateLimitRecord.timestamp < prune_cutoff).delete(synchronize_session=False)
                db.session.commit()
            except Exception:
                db.session.rollback()
                
        return True
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
            
    # 2. Resilient Fallback: In-memory sliding window per process
    if len(_rate_limits) > 5000:
        keys_to_delete = [k for k, v in _rate_limits.items() if not v or (now - v[-1] > 300)]
        for k in keys_to_delete:
            _rate_limits.pop(k, None)
            
    attempts = _rate_limits[key]
    valid_attempts = [t for t in attempts if now - t < window_seconds]
    _rate_limits[key] = valid_attempts
    if len(valid_attempts) >= max_attempts:
        return False
    _rate_limits[key].append(now)
    return True

def is_safe_url(target):
    """
    Ensures a redirect target URL is safe and belongs to the current application host,
    mitigating Open Redirect (CWE-601) attacks.
    """
    if not target:
        return False
    # Prohibit protocol-relative URLs (e.g. '//evil.com' or '\\evil.com')
    if target.startswith('//') or target.startswith('\\\\'):
        return False
    try:
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
        return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc
    except Exception:
        return False

def get_safe_redirect_url(target, default=None):
    """Returns target if safe, otherwise default or courses list."""
    if is_safe_url(target):
        return target
    return default or url_for('elearning.courses_list')

def validate_password_complexity(password):
    """
    Validates password against standard rules:
    - Minimum 8 chars (12+ recommended)
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not re.search(r'[A-Z]', password):
        errors.append("Password must contain at least one uppercase letter (A-Z).")
    if not re.search(r'[a-z]', password):
        errors.append("Password must contain at least one lowercase letter (a-z).")
    if not re.search(r'[0-9]', password):
        errors.append("Password must contain at least one number (0-9).")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=~/]', password):
        errors.append("Password must contain at least one special character (e.g. !@#$%^&*).")
    return len(errors) == 0, errors

def calculate_password_strength(password):
    """Returns a score from 0 to 4 and a label."""
    if not password:
        return 0, 'Very Weak'
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r'[A-Z]', password) and re.search(r'[a-z]', password):
        score += 1
    if re.search(r'[0-9]', password):
        score += 1
    if re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=~/]', password):
        score += 1
    
    mapping = {0: 'Very Weak', 1: 'Weak', 2: 'Fair', 3: 'Good', 4: 'Strong', 5: 'Very Strong'}
    return min(score, 5), mapping.get(min(score, 5), 'Fair')

def generate_order_reference():
    """Generates an order reference: YT-PAY-YYYY-XXXXXX"""
    year = datetime.now().year
    suffix = uuid.uuid4().hex[:6].upper()
    return f"YT-PAY-{year}-{suffix}"

def generate_certificate_id(course_slug):
    """Generates unique certificate ID: YTAL-COURSE-YYYY-XXXXXX"""
    year = datetime.now().year
    slug_map = {
        'good-documentation-practices': 'GDP',
        'ich-gcp': 'GCP',
        'new-drugs-clinical-trials-rules-2019': 'NDCT'
    }
    prefix = slug_map.get(course_slug, 'CERT')
    suffix = uuid.uuid4().hex[:6].upper()
    return f"YTAL-{prefix}-{year}-{suffix}"

def generate_digital_signature(cert_id, user_name, course_title, issue_date_str):
    """Generates a cryptographic HMAC-SHA256 signature to deter tampering."""
    secret = current_app.config.get('SECRET_KEY', 'ytaltech-secret').encode('utf-8')
    message = f"{cert_id}|{user_name}|{course_title}|{issue_date_str}|YTAL_TECH".encode('utf-8')
    return hmac.new(secret, message, hashlib.sha256).hexdigest().upper()

def is_allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_uploaded_file(file_storage, target_folder, allowed_extensions):
    """Safely saves an uploaded file and returns its relative or absolute path."""
    if not file_storage or not file_storage.filename:
        return None, "No file provided"
    
    if not is_allowed_file(file_storage.filename, allowed_extensions):
        return None, "File type not permitted. Only JPG, PNG, PDF, and HEIC files are allowed for payment screenshots/receipts."
    
    os.makedirs(target_folder, exist_ok=True)
    orig_ext = file_storage.filename.rsplit('.', 1)[1].lower()
    clean_name = f"{uuid.uuid4().hex}_{int(time.time())}.{orig_ext}"
    dest_path = os.path.join(target_folder, clean_name)
    file_storage.save(dest_path)
    return clean_name, None

def generate_qr_code_image(data_text, output_path):
    """Generates a QR code image saved to output_path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0A192F", back_color="white")
    img.save(output_path)
    return output_path

def log_audit_event(user_id, action, entity_type, entity_id, details=None):
    """Records an immutable audit log entry."""
    ip = request.remote_addr if request else '127.0.0.1'
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=str(details) if details else None,
        ip_address=ip,
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(entry)
    db.session.commit()

def send_transactional_email(recipient_email, subject, html_content, text_content=None, sender=None):
    """
    Sends transactional email via SMTP and logs to database.
    Supports SSL (port 465) and TLS/STARTTLS (port 587).
    Gracefully handles testing mode and network exceptions without interrupting the learner flow.
    """
    cfg = current_app.config if current_app else {}
    mail_server = cfg.get('MAIL_SERVER', 'smtpout.secureserver.net')
    mail_port = cfg.get('MAIL_PORT', 465)
    mail_use_ssl = cfg.get('MAIL_USE_SSL', True)
    mail_use_tls = cfg.get('MAIL_USE_TLS', False)
    mail_username = cfg.get('MAIL_USERNAME', 'contact@ytaltech.com')
    mail_password = cfg.get('MAIL_PASSWORD', 'Ajayganesh@2024')
    default_sender = cfg.get('MAIL_DEFAULT_SENDER', 'Ytal Tech <contact@ytaltech.com>')
    mail_timeout = cfg.get('MAIL_TIMEOUT', 15)

    from_addr = sender or default_sender

    # Construct clean email body with professional branded wrapping if needed
    if not ("<html" in (html_content or '').lower() and "<body" in (html_content or '').lower()):
        wrapped_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
  .email-container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; }}
  .email-header {{ background: #0b1a30; padding: 24px 30px; border-bottom: 3px solid #00AEEF; }}
  .email-header h1 {{ color: #ffffff; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0.5px; }}
  .email-body {{ padding: 30px; font-size: 15px; line-height: 1.6; color: #334155; }}
  .email-footer {{ background: #f1f5f9; padding: 18px 30px; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; text-align: center; }}
</style>
</head>
<body>
<div class="email-container">
  <div class="email-header">
    <h1>Ytal Tech Solutions &amp; Services</h1>
  </div>
  <div class="email-body">
    {html_content}
  </div>
  <div class="email-footer">
    <p><strong>Ytal Tech Solutions &amp; Services LLP</strong><br>
    103, Parijat Gardens Gulmohar CHS Ltd., Ghodbunder Road, Kasarvadavali, Thane - 400615, Maharashtra, India<br>
    Email: contact@ytaltech.com | Phone: +91 9372571921</p>
  </div>
</div>
</body>
</html>"""
    else:
        wrapped_html = html_content

    # Plain text fallback
    if not text_content:
        text_content = re.sub(r'<[^>]+>', ' ', html_content or '')
        text_content = re.sub(r'\s+', ' ', text_content).strip()

    status = 'sent'

    # If in testing mode or mail suppression configured, log without sending network packet
    if cfg.get('TESTING') or cfg.get('MAIL_SUPPRESS_SEND'):
        email_log = EmailLog(
            recipient=recipient_email,
            subject=subject,
            body_html=wrapped_html,
            status='sent',
            sent_at=datetime.now(timezone.utc)
        )
        db.session.add(email_log)
        db.session.commit()
        return True

    # Prepare message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = recipient_email

    _, sender_email = email.utils.parseaddr(from_addr)
    if not sender_email:
        sender_email = mail_username

    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(wrapped_html, 'html', 'utf-8'))

    # Prepare SSL Context with resilient CA cert discovery across all Python environments
    ssl_ctx = None
    try:
        import certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        candidate_pem = r"C:\Users\Dr Ganesh Divekar\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\certifi\cacert.pem"
        if os.path.exists(candidate_pem):
            try:
                ssl_ctx = ssl.create_default_context(cafile=candidate_pem)
            except Exception:
                pass
    if ssl_ctx is None:
        try:
            ssl_ctx = ssl.create_default_context()
        except Exception:
            ssl_ctx = ssl._create_unverified_context()

    def _execute_smtp_send(active_ctx):
        if mail_use_ssl:
            with smtplib.SMTP_SSL(mail_server, mail_port, context=active_ctx, timeout=mail_timeout) as server:
                if mail_username and mail_password:
                    server.login(mail_username, mail_password)
                server.sendmail(sender_email, [recipient_email], msg.as_string())
        else:
            with smtplib.SMTP(mail_server, mail_port, timeout=mail_timeout) as server:
                if mail_use_tls:
                    server.starttls(context=active_ctx)
                if mail_username and mail_password:
                    server.login(mail_username, mail_password)
                server.sendmail(sender_email, [recipient_email], msg.as_string())

    mail_async = cfg.get('MAIL_ASYNC', True)

    if mail_async:
        # Non-blocking asynchronous SMTP dispatch for high-performance WSGI
        email_log = EmailLog(
            recipient=recipient_email,
            subject=subject,
            body_html=wrapped_html,
            status='pending',
            sent_at=datetime.now(timezone.utc)
        )
        db.session.add(email_log)
        db.session.commit()
        email_log_id = email_log.id

        # Capture application instance for app context inside background worker
        app_obj = current_app._get_current_object()

        def _async_worker():
            with app_obj.app_context():
                worker_status = 'sent'
                try:
                    try:
                        _execute_smtp_send(ssl_ctx)
                    except (ssl.SSLCertVerificationError, ssl.SSLError) as ssl_err:
                        print(f"[SMTP Warning] SSL verification failed ({ssl_err}); retrying with unverified context fallback...")
                        _execute_smtp_send(ssl._create_unverified_context())
                except Exception as exc:
                    print(f"[Async SMTP Warning] Failed to send email to {recipient_email}: {exc}")
                    worker_status = 'failed'
                    try:
                        log_audit_event(
                            0,
                            "EMAIL_SEND_FAILED",
                            "Email",
                            email_log_id,
                            f"To: {recipient_email}, Subject: {subject}, Error: {str(exc)[:200]}"
                        )
                    except Exception:
                        pass
                try:
                    log_record = EmailLog.query.get(email_log_id)
                    if log_record:
                        log_record.status = worker_status
                        db.session.commit()
                except Exception:
                    db.session.rollback()

        _email_executor.submit(_async_worker)
        return True
    else:
        # Synchronous execution (for testing or single-process debugging)
        try:
            try:
                _execute_smtp_send(ssl_ctx)
            except (ssl.SSLCertVerificationError, ssl.SSLError) as ssl_err:
                print(f"[SMTP Warning] SSL verification failed ({ssl_err}); retrying with unverified context fallback...")
                _execute_smtp_send(ssl._create_unverified_context())
            status = 'sent'
        except Exception as exc:
            print(f"[SMTP Warning] Failed to send email to {recipient_email}: {exc}")
            status = 'failed'
            try:
                log_audit_event(
                    0,
                    "EMAIL_SEND_FAILED",
                    "Email",
                    0,
                    f"To: {recipient_email}, Subject: {subject}, Error: {str(exc)[:200]}"
                )
            except Exception:
                pass

        email_log = EmailLog(
            recipient=recipient_email,
            subject=subject,
            body_html=wrapped_html,
            status=status,
            sent_at=datetime.now(timezone.utc)
        )
        db.session.add(email_log)
        db.session.commit()
        return (status == 'sent')

# Numbered canvas for ReportLab PDF pagination / border drawing
class CertificateCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = []

    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self.pages)
        for page in self.pages:
            self.__dict__.update(page)
            self.draw_borders_and_decorations()
            super().showPage()
        super().save()

    def draw_borders_and_decorations(self):
        self.saveState()
        # Certificate border in landscape letter size: 11 x 8.5 inches (792 x 612 pt)
        width = 792
        height = 612
        
        # Outer decorative double border
        # Primary Cyan line
        self.setStrokeColor(colors.HexColor('#00AEEF'))
        self.setLineWidth(5)
        self.rect(20, 20, width - 40, height - 40)
        
        # Secondary Magenta/Pink inner line
        self.setStrokeColor(colors.HexColor('#EC008C'))
        self.setLineWidth(1.5)
        self.rect(26, 26, width - 52, height - 52)
        
        # Corner accent marks (Green #39B54A)
        self.setStrokeColor(colors.HexColor('#39B54A'))
        self.setLineWidth(3)
        # Top-left
        self.line(32, height - 32, 60, height - 32)
        self.line(32, height - 32, 32, height - 60)
        # Top-right
        self.line(width - 32, height - 32, width - 60, height - 32)
        self.line(width - 32, height - 32, width - 32, height - 60)
        # Bottom-left
        self.line(32, 32, 60, 32)
        self.line(32, 32, 32, 60)
        # Bottom-right
        self.line(width - 32, 32, width - 60, 32)
        self.line(width - 32, 32, width - 32, 60)
        
        # Security watermark text
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor('#888888'))
        self.drawRightString(width - 40, 32, "SECURE DIGITAL CERTIFICATE • VERIFY AT WWW.YTALTECH.COM")
        self.drawString(40, 32, "YTAL TECH SOLUTIONS & SERVICES LLP • OFFICIAL RECORD")
        self.restoreState()

def generate_pdf_certificate(certificate, base_url="https://www.ytaltech.com"):
    """
    Generates a tamper-evident, professionally designed PDF certificate
    using ReportLab with QR code and cryptographic signature hash.
    """
    output_filename = f"{certificate.certificate_id}.pdf"
    pdf_path = os.path.join(current_app.config['CERTIFICATES_FOLDER'], output_filename)
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    
    # Generate QR Code for certificate verification URL
    verify_url = f"{base_url}/verify-certificate?cert={certificate.certificate_id}"
    qr_filename = f"qr_{certificate.certificate_id}.png"
    qr_path = os.path.join(current_app.config['CERTIFICATES_FOLDER'], qr_filename)
    generate_qr_code_image(verify_url, qr_path)
    
    certificate.qr_code_path = f"certificates/{qr_filename}"
    certificate.verification_url = verify_url
    
    # Document dimensions (landscape letter: 792 x 612 pt)
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=landscape(letter),
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CertTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#0A192F'),
        alignment=1, # Center
        spaceAfter=6
    )
    
    sub_title_style = ParagraphStyle(
        'CertSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#00AEEF'),
        alignment=1,
        spaceAfter=15
    )
    
    certify_text_style = ParagraphStyle(
        'CertifyText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#555555'),
        alignment=1,
        spaceAfter=10
    )
    
    name_style = ParagraphStyle(
        'RecipientName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=26,
        leading=30,
        textColor=colors.HexColor('#EC008C'), # Signature magenta
        alignment=1,
        spaceAfter=12
    )
    
    course_style = ParagraphStyle(
        'CourseTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0A192F'),
        alignment=1,
        spaceAfter=15
    )
    
    meta_style = ParagraphStyle(
        'MetaDetails',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#444444'),
        alignment=1
    )
    
    hash_style = ParagraphStyle(
        'SecurityHash',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7,
        leading=9,
        textColor=colors.HexColor('#666666'),
        alignment=1
    )
    
    story = []
    
    # Logo header if available (proportional sizing to preserve exact aspect ratio without distortion)
    logo_path = os.path.join(current_app.root_path, 'static', 'Ytal Tech logo.jpg')
    if os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as p_img:
                orig_w, orig_h = p_img.size
                aspect = orig_w / float(orig_h)
            target_h = 1.0 * inch
            target_w = target_h * aspect
            story.append(RLImage(logo_path, width=target_w, height=target_h, kind='proportional'))
        except Exception:
            try:
                story.append(RLImage(logo_path, width=0.85*inch, height=0.85*inch, kind='proportional'))
            except Exception:
                pass
    
    story.append(Spacer(1, 8))
    story.append(Paragraph("YTAL TECH SOLUTIONS & SERVICES LLP", sub_title_style))
    story.append(Paragraph("CERTIFICATE OF COMPLETION", title_style))
    story.append(Paragraph("This is to certify that", certify_text_style))
    story.append(Paragraph(certificate.user.full_name.upper(), name_style))
    user_email_style = ParagraphStyle(
        'UserEmailStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#0284c7'),
        alignment=1,
        spaceAfter=8
    )
    story.append(Paragraph(f"Registered Email: <b>{certificate.user.email}</b>", user_email_style))
    story.append(Paragraph("has successfully completed the comprehensive training course & examination in", certify_text_style))
    story.append(Paragraph(f"“{certificate.course.title}”", course_style))
    
    score_text = f"Final Score: <b>{certificate.score_percentage:.1f}% (PASSED)</b> &nbsp;|&nbsp; Course Version: <b>{certificate.course_version}</b>"
    story.append(Paragraph(score_text, meta_style))
    story.append(Spacer(1, 15))
    
    # Bottom section with QR code, Issuing details, and Signatures
    # Using a 3-column table
    left_cell = [
        Paragraph(f"<b>Certificate ID:</b><br/>{certificate.certificate_id}", meta_style),
        Spacer(1, 3),
        Paragraph(f"<b>Issue Date:</b><br/>{certificate.issue_date.strftime('%d %B %Y')}", meta_style),
        Spacer(1, 3),
        Paragraph(f"<b>Candidate Email:</b><br/>{certificate.user.email}", meta_style),
        Spacer(1, 3),
        Paragraph(f"<b>Status:</b> <font color='#39B54A'><b>VALID / VERIFIED</b></font>", meta_style)
    ]
    
    middle_cell = [
        RLImage(qr_path, width=1.1*inch, height=1.1*inch),
        Paragraph("Scan QR to verify authenticity", ParagraphStyle('QRLabel', parent=styles['Normal'], fontName='Helvetica', fontSize=7, alignment=1))
    ]
    
    right_cell = [
        Paragraph("<b>Dr. Ganesh Divekar</b>", ParagraphStyle('Sign1', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=1)),
        Paragraph("Course Director<br/>Ytal Tech Solutions & Services LLP", ParagraphStyle('Sign1Desc', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=1)),
        Spacer(1, 8),
        Paragraph("<b>Ajay Kondekar</b>", ParagraphStyle('Sign2', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=1)),
        Paragraph("Compliance Director<br/>Ytal Tech Solutions & Services LLP", ParagraphStyle('Sign2Desc', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=1))
    ]
    
    footer_table = Table([[left_cell, middle_cell, right_cell]], colWidths=[240, 160, 240])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'CENTER'),
    ]))
    story.append(footer_table)
    story.append(Spacer(1, 10))
    
    # Cryptographic Hash row
    story.append(Paragraph(f"Cryptographic Tamper-Proof Digital Hash (HMAC-SHA256):<br/><b>{certificate.digital_signature_hash}</b>", hash_style))
    
    doc.build(story, canvasmaker=CertificateCanvas)
    certificate.pdf_file_path = f"certificates/{output_filename}"
    db.session.commit()
    return pdf_path

def amount_to_words(amount, currency='INR'):
    """Converts a numerical currency amount to words (Indian numbering for INR, International for USD)."""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
    
    def num_to_text(n):
        if n == 0:
            return ''
        elif n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + (' ' + ones[n % 10] if n % 10 != 0 else '')
        elif n < 1000:
            return ones[n // 100] + ' Hundred' + (' ' + num_to_text(n % 100) if n % 100 != 0 else '')
        elif n < 100000: # Lakhs
            return num_to_text(n // 1000) + ' Thousand' + (' ' + num_to_text(n % 1000) if n % 1000 != 0 else '')
        elif n < 10000000: # Crores
            return num_to_text(n // 100000) + ' Lakh' + (' ' + num_to_text(n % 100000) if n % 100000 != 0 else '')
        else:
            return num_to_text(n // 10000000) + ' Crore' + (' ' + num_to_text(n % 10000000) if n % 10000000 != 0 else '')

    amt_int = int(amount)
    fraction = int(round((amount - amt_int) * 100))
    
    main_words = num_to_text(amt_int) or 'Zero'
    prefix = 'INR ' if currency == 'INR' else 'USD '
    
    if fraction > 0:
        fraction_words = num_to_text(fraction)
        sub_unit = 'Paise' if currency == 'INR' else 'Cents'
        return f'{prefix}{main_words} and {fraction_words} {sub_unit} Only'
    else:
        return f'{prefix}{main_words} Only'


def generate_pdf_invoice(payment_order):
    """
    Generates official, GST-compliant Tax Invoice matching the exact format of
    gst_compliant_invoice_ytal_bb_precision_GD_22Sep26.docx.
    Includes SAC code, supplier details, customer GSTIN, tax breakdown, and banking particulars.
    """
    from elearning.models import SystemSetting
    
    filename = f"Invoice_{payment_order.order_reference}.pdf"
    pdf_path = os.path.join(current_app.config['INVOICES_FOLDER'], filename)
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []
    
    # Typography styles matching the docx format
    title_bold = ParagraphStyle('TBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, textColor=colors.HexColor('#0A192F'))
    normal_text = ParagraphStyle('TNorm', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor('#1E293B'))
    bold_text = ParagraphStyle('TBoldText', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor('#0A192F'))
    right_meta = ParagraphStyle('RMeta', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, alignment=2, textColor=colors.HexColor('#1E293B'))
    center_text = ParagraphStyle('TCenter', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, alignment=1)
    center_bold = ParagraphStyle('TCenterBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, alignment=1)
    right_cell = ParagraphStyle('TRight', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, alignment=2)
    right_cell_bold = ParagraphStyle('TRightBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, alignment=2)

    # System parameters
    co_name = SystemSetting.get('company_name', 'Ytal Tech Solutions & Services LLP')
    co_address = SystemSetting.get('company_address', '103, Parijat Gardens Gulmohar CHS Ltd., Ghodbunder Road, Kasarvadavali, Thane 400615, Maharashtra, India')
    co_gstin = SystemSetting.get('company_gstin', '27AADFY4241Q1ZL')
    co_pan = SystemSetting.get('company_pan', 'AADFY4241Q')
    co_email = SystemSetting.get('company_email', 'contact@ytaltech.com')
    sac_code = SystemSetting.get('sac_code', '998314')
    
    bank_name = SystemSetting.get('bank_name', 'SBI')
    bank_branch = SystemSetting.get('bank_branch', 'Kasarvadavali branch, Thane')
    acc_name = SystemSetting.get('bank_account_name', 'Ytal Tech Solutions and Services LLP')
    acc_number = SystemSetting.get('bank_account_number', '43028833589')
    ifsc = SystemSetting.get('bank_ifsc', 'SBIN0061708')

    # Invoice metadata
    inv_date = (payment_order.verified_at or payment_order.submitted_at or datetime.now()).strftime('%d-%b-%Y')
    invoice_number = f"2026/{payment_order.order_reference[:8].upper()}"

    # Customer billing resolution
    user = payment_order.user
    customer_org = payment_order.customer_org_name or getattr(user, 'organization_name', None) or user.full_name
    customer_gstin = payment_order.customer_gstin or getattr(user, 'gstin', None)
    customer_addr = payment_order.customer_billing_address or getattr(user, 'billing_address', None)
    if not customer_addr:
        addr_parts = [getattr(user, 'house_no', None), getattr(user, 'street', None), getattr(user, 'city', None), getattr(user, 'state', None), getattr(user, 'pincode', None)]
        customer_addr = ", ".join([p for p in addr_parts if p]) or "Thane, Maharashtra, India"

    customer_state = payment_order.customer_state or getattr(user, 'state', None) or 'Maharashtra'
    
    # State code determination
    state_code = '27'
    if customer_gstin and len(customer_gstin) >= 2 and customer_gstin[:2].isdigit():
        state_code = customer_gstin[:2]
    else:
        state_upper = customer_state.upper()
        if 'MAHARASHTRA' in state_upper: state_code = '27'
        elif 'DELHI' in state_upper: state_code = '07'
        elif 'KARNATAKA' in state_upper: state_code = '29'
        elif 'TAMIL' in state_upper: state_code = '33'
        elif 'GUJARAT' in state_upper: state_code = '24'
        elif 'UTTAR' in state_upper: state_code = '09'
        elif 'TELANGANA' in state_upper: state_code = '36'
        elif 'WEST BENGAL' in state_upper: state_code = '19'
        elif 'KERALA' in state_upper: state_code = '32'
        elif 'RAJASTHAN' in state_upper: state_code = '08'

    # Financial computations
    currency = payment_order.currency or 'INR'
    is_domestic = (currency == 'INR')
    total_amount = payment_order.total_amount
    gst_amount = payment_order.gst_amount if is_domestic else 0.0
    taxable_value = payment_order.base_amount
    
    # Intra-state vs Inter-state tax splitting (Maharashtra state code: 27)
    is_intra_state = is_domestic and (state_code == '27')
    cgst_amt = round(gst_amount / 2.0, 2) if is_intra_state else 0.0
    sgst_amt = round(gst_amount / 2.0, 2) if is_intra_state else 0.0
    igst_amt = gst_amount if (is_domestic and not is_intra_state) else 0.0
    
    amt_words = amount_to_words(total_amount, currency)

    # -------------------------------------------------------------
    # Table 1: Header (Supplier Left, TAX RECEIPT Meta Right)
    # -------------------------------------------------------------
    t1_data = [
        [
            Paragraph(f'<b>{co_name}</b><br/>{co_address}<br/><b>GSTIN:</b> {co_gstin}<br/><b>PAN:</b> {co_pan}', normal_text),
            Paragraph(f'<font size="14" color="#0A192F"><b>TAX RECEIPT</b></font><br/><br/><b>Receipt No:</b> {invoice_number}<br/><b>Receipt Date:</b> {inv_date}<br/><b>Reverse Charge:</b> No', right_meta)
        ]
    ]
    t1 = Table(t1_data, colWidths=[310, 230])
    t1.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t1)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # Table 2: Supplier Details vs Bill To
    # -------------------------------------------------------------
    t2_data = [
        [Paragraph('<b>Supplier Details</b>', bold_text), Paragraph('<b>Bill To</b>', bold_text)],
        [
            Paragraph(f'<b>{co_name}</b><br/>{co_address}<br/><b>GSTIN:</b> {co_gstin}<br/><b>Place of Supply:</b> Maharashtra (State Code: 27)', normal_text),
            Paragraph(f'<b>{customer_org}</b><br/>{customer_addr}<br/><b>GSTIN/UIN:</b> {customer_gstin or "Not provided"}<br/><b>State:</b> {customer_state} | <b>State Code:</b> {state_code}', normal_text)
        ]
    ]
    t2 = Table(t2_data, colWidths=[270, 270])
    t2.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t2)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # Table 3: Service Description & Line Items
    # -------------------------------------------------------------
    gst_rate_label = "18%" if is_domestic else "0%"
    t3_data = [
        [
            Paragraph('<b>#</b>', center_bold),
            Paragraph('<b>Description of Service</b>', bold_text),
            Paragraph('<b>SAC</b>', center_bold),
            Paragraph('<b>Qty</b>', center_bold),
            Paragraph('<b>Unit</b>', center_bold),
            Paragraph('<b>Taxable Value</b>', right_cell_bold),
            Paragraph('<b>GST</b>', center_bold),
            Paragraph('<b>Line Total</b>', right_cell_bold)
        ],
        [
            Paragraph('1', center_text),
            Paragraph(f'E-Learning Certification Course: {payment_order.course.title}', normal_text),
            Paragraph(str(sac_code), center_text),
            Paragraph('1', center_text),
            Paragraph('Course', center_text),
            Paragraph(f'{currency} {taxable_value:.2f}', right_cell),
            Paragraph(gst_rate_label, center_text),
            Paragraph(f'{currency} {taxable_value:.2f}', right_cell)
        ]
    ]
    t3 = Table(t3_data, colWidths=[24, 186, 45, 30, 45, 75, 45, 90])
    t3.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t3)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # Table 4: Tax Calculation Breakdown & Amount in Words
    # -------------------------------------------------------------
    t4_data = [
        [Paragraph('Taxable Value', bold_text), Paragraph(f'{currency} {taxable_value:.2f}', right_cell)],
        [Paragraph('CGST @ 9%', normal_text), Paragraph(f'{currency} {cgst_amt:.2f}', right_cell)],
        [Paragraph('SGST @ 9%', normal_text), Paragraph(f'{currency} {sgst_amt:.2f}', right_cell)],
        [Paragraph('IGST @ 18%' if igst_amt > 0 else 'IGST @ 0%', normal_text), Paragraph(f'{currency} {igst_amt:.2f}', right_cell)],
        [Paragraph('<b>Grand Total</b>', title_bold), Paragraph(f'<b>{currency} {total_amount:.2f}</b>', ParagraphStyle('GT', parent=right_cell_bold, fontSize=10, textColor=colors.HexColor('#00AEEF')))],
        [Paragraph('<b>Amount in Words:</b>', bold_text), Paragraph(amt_words, ParagraphStyle('AW', parent=right_cell_bold, fontSize=8.5, textColor=colors.HexColor('#1E293B')))]
    ]
    t4 = Table(t4_data, colWidths=[270, 270])
    t4.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('BACKGROUND', (0,4), (-1,4), colors.HexColor('#F8FAFC')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t4)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # Table 5: Declaration & Authorized Signatory
    # -------------------------------------------------------------
    sign_img_path = os.path.join(current_app.root_path, 'static', 'elearning', 'img', 'authorized_signatory.png')
    right_cell_elements = [
        Paragraph('<b>Authorized Signatory</b>', ParagraphStyle('SigHeader', parent=center_text, fontSize=9, spaceAfter=2))
    ]
    if os.path.exists(sign_img_path):
        right_cell_elements.append(RLImage(sign_img_path, width=1.5*inch, height=0.51*inch, kind='proportional'))
    else:
        right_cell_elements.append(Spacer(1, 20))
    right_cell_elements.append(Paragraph('____________________', ParagraphStyle('SigLine', parent=center_text, fontSize=9, spaceBefore=2)))

    t5_data = [
        [Paragraph('<b>Declaration</b>', bold_text), Paragraph('<b>For Ytal Tech Solutions & Services LLP</b>', bold_text)],
        [
            Paragraph('<b>Declaration:</b> We declare that this receipt shows the actual price of the services described and that all particulars are true and correct.', normal_text),
            right_cell_elements
        ]
    ]
    t5 = Table(t5_data, colWidths=[330, 210])
    t5.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t5)
    story.append(Spacer(1, 10))

    # Footer note
    story.append(Paragraph(f'If you have any questions about this receipt, please reach out on {co_email}', ParagraphStyle('InvFooter', parent=center_text, fontSize=8, textColor=colors.HexColor('#64748B'))))

    doc.build(story)
    return pdf_path

def parse_pptx_slides(pptx_path):
    """
    Parses a PowerPoint (.pptx) file using python-pptx and returns a list of slide dicts:
    [{'title': str, 'content_html': str, 'slide_number': int}]
    """
    try:
        from pptx import Presentation
        prs = Presentation(pptx_path)
        extracted = []
        for idx, slide in enumerate(prs.slides, start=1):
            title = ""
            paragraphs = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        text = p.text.strip()
                        if text:
                            if not title and len(text) < 100:
                                title = text
                            else:
                                paragraphs.append(f"<p>{text}</p>")
            if not title:
                title = f"Slide {idx}"
            content_html = "\n".join(paragraphs) if paragraphs else "<p>Slide content details.</p>"
            extracted.append({
                'slide_number': idx,
                'title': title,
                'content_html': content_html
            })
        return extracted, None
    except Exception as e:
        return [], str(e)
