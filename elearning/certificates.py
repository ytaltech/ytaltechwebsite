import os
from datetime import datetime, date, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, current_app, send_file
)
from elearning.models import (
    db, Certificate, Course, Enrolment, PaymentOrder,
    User, CertificateComplaint
)
from elearning.auth import login_required, get_current_user
from elearning.utils import (
    generate_certificate_id, generate_digital_signature,
    generate_pdf_certificate, save_uploaded_file,
    log_audit_event, send_transactional_email, check_rate_limit
)

cert_bp = Blueprint('certificates', __name__, url_prefix='')

def issue_certificate_if_eligible(enrolment):
    """
    Checks all preconditions and issues digital certificate if all are met:
    1. Slides completed
    2. Test passed with >= 80%
    3. Payment status is explicitly 'verified_approved' (or higher)
    """
    if not enrolment.slides_completed:
        return None, "Course slides have not been completed."
        
    latest_passed = enrolment.latest_passed_attempt
    if not latest_passed:
        return None, "Final examination has not been passed (80% score required)."
        
    # Check payment order
    order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
    if not order or order.status not in ['verified_approved', 'certificate_issued', 'certificate_dispatched', 'certificate_delivered']:
        return None, "Manual payment has not been verified/approved by Finance Administrator."
        
    # Check if certificate already exists
    existing = Certificate.query.filter_by(enrolment_id=enrolment.id).first()
    if existing:
        return existing, None
        
    # Generate new certificate
    cert_id = generate_certificate_id(enrolment.course.slug)
    today = date.today()
    sig_hash = generate_digital_signature(
        cert_id,
        enrolment.user.full_name,
        enrolment.course.title,
        today.isoformat()
    )
    
    cert = Certificate(
        certificate_id=cert_id,
        enrolment_id=enrolment.id,
        user_id=enrolment.user_id,
        course_id=enrolment.course_id,
        payment_order_id=order.id,
        issue_date=today,
        score_percentage=latest_passed.percentage,
        course_version=enrolment.course.version,
        status='valid',
        digital_signature_hash=sig_hash,
        dispatch_status='pending_dispatch'
    )
    db.session.add(cert)
    
    # Update payment order status to certificate_issued
    order.status = 'certificate_issued'
    db.session.commit()
    
    # Generate PDF and QR code
    base_url = request.host_url.rstrip('/') if request else "https://www.ytaltech.com"
    generate_pdf_certificate(cert, base_url=base_url)
    
    log_audit_event(
        enrolment.user_id,
        "CERTIFICATE_ISSUED",
        "Certificate",
        cert.id,
        f"Certificate ID: {cert_id}, Course: {enrolment.course.title}"
    )
    
    # Send transactional email to learner
    email_body = f"""
    <h3>Congratulations! Your Official Certificate is Ready</h3>
    <p>Dear {enrolment.user.full_name},</p>
    <p>We are pleased to inform you that following successful completion of your course and verification of your payment, your official Certificate of Completion for <strong>{enrolment.course.title}</strong> has been issued!</p>
    <p><strong>Certificate ID:</strong> {cert.certificate_id}<br/>
    <strong>Issue Date:</strong> {cert.issue_date.strftime('%d-%B-%Y')}<br/>
    <strong>Verification Hash:</strong> {cert.digital_signature_hash[:16]}...</p>
    <p>You can download your PDF certificate and verify its authenticity anytime from your learner dashboard.</p>
    """
    send_transactional_email(enrolment.user.email, f"Certificate Issued: {enrolment.course.title}", email_body)
    
    return cert, None


@cert_bp.route('/elearning/certificate/<cert_id>')
@login_required
def view_certificate(cert_id):
    user = get_current_user()
    cert = Certificate.query.filter_by(certificate_id=cert_id).first_or_404()
    
    is_admin = user.has_role('super_admin', 'certificate_admin', 'finance_admin')
    if cert.user_id != user.id and not is_admin:
        flash("Unauthorized to view this certificate.", "danger")
        return redirect(url_for('elearning.courses_list'))

    # Verify payment confirmation by finance or admin
    if not is_admin:
        order = PaymentOrder.query.filter_by(enrolment_id=cert.enrolment_id).order_by(PaymentOrder.id.desc()).first()
        if not order or order.status not in ['verified_approved', 'certificate_issued', 'certificate_dispatched', 'certificate_delivered']:
            flash("The certificate will appear and be available to download only after confirmation of payment by Finance or Admin.", "warning")
            return redirect(url_for('payments.payment_status', order_ref=order.order_reference if order else ''))
        
    return render_template('elearning/certificate_view.html', certificate=cert)


@cert_bp.route('/elearning/certificate/<cert_id>/download')
@login_required
def download_certificate_pdf(cert_id):
    user = get_current_user()
    cert = Certificate.query.filter_by(certificate_id=cert_id).first_or_404()
    
    is_admin = user.has_role('super_admin', 'certificate_admin', 'finance_admin')
    if cert.user_id != user.id and not is_admin:
        flash("Unauthorized.", "danger")
        return redirect(url_for('elearning.courses_list'))

    # Verify payment confirmation by finance or admin
    if not is_admin:
        order = PaymentOrder.query.filter_by(enrolment_id=cert.enrolment_id).order_by(PaymentOrder.id.desc()).first()
        if not order or order.status not in ['verified_approved', 'certificate_issued', 'certificate_dispatched', 'certificate_delivered']:
            flash("The certificate can be downloaded only after confirmation of payment by Finance or Admin.", "warning")
            return redirect(url_for('payments.payment_status', order_ref=order.order_reference if order else ''))
        
    pdf_full_path = os.path.join(current_app.config['CERTIFICATES_FOLDER'], f"{cert.certificate_id}.pdf")
    if not os.path.exists(pdf_full_path):
        base_url = request.host_url.rstrip('/')
        generate_pdf_certificate(cert, base_url=base_url)
        
    return send_file(
        pdf_full_path,
        as_attachment=True,
        download_name=f"Certificate_{cert.certificate_id}.pdf",
        mimetype='application/pdf'
    )


@cert_bp.route('/verify-certificate')
def verify_certificate():
    """
    Public QR verification page.
    https://www.ytaltech.com/verify-certificate?cert=UNIQUE_ID
    """
    cert_id = request.args.get('cert', '').strip()
    cert = None
    is_valid = False
    
    if cert_id:
        cert = Certificate.query.filter_by(certificate_id=cert_id).first()
        if cert and cert.status == 'valid':
            is_valid = True
            
    return render_template(
        'elearning/verify.html',
        cert_id=cert_id,
        certificate=cert,
        is_valid=is_valid
    )


@cert_bp.route('/verify-certificate/complaint', methods=['POST'])
def submit_certificate_complaint():
    """
    Report or complaint submission for fake, altered, or unverified certificates.
    """
    cert_id = request.form.get('certificate_id', '').strip()
    client_ip = request.remote_addr or '127.0.0.1'
    if not check_rate_limit(f"complaint_{client_ip}", max_attempts=4, window_seconds=120):
        flash("Too many requests submitted. Please wait a couple of minutes before submitting another inquiry.", "warning")
        return redirect(url_for('certificates.verify_certificate', cert=cert_id))

    name = request.form.get('reporter_name', '').strip()
    email = request.form.get('reporter_email', '').strip()
    phone = request.form.get('reporter_phone', '').strip()
    desc = request.form.get('issue_description', '').strip()
    consent = request.form.get('consent_given')
    file = request.files.get('attachment')
    
    if not name or not email or not desc:
        flash("Name, email, and description are required to submit an inquiry/complaint.", "danger")
        return redirect(url_for('certificates.verify_certificate', cert=cert_id))
        
    attachment_path = None
    if file and file.filename:
        filename, err = save_uploaded_file(
            file,
            current_app.config['RECEIPTS_UPLOAD_FOLDER'],
            current_app.config['ALLOWED_PROOF_EXTENSIONS']
        )
        if not err:
            attachment_path = f"uploads/receipts/{filename}"
            
    complaint = CertificateComplaint(
        certificate_id_reported=cert_id,
        reporter_name=name,
        reporter_email=email,
        reporter_phone=phone,
        issue_description=desc,
        attachment_path=attachment_path,
        consent_given=bool(consent),
        status='open'
    )
    db.session.add(complaint)
    db.session.commit()
    
    # Notify admin
    admin_body = f"""
    <h3>New Certificate Verification Query / Report Submitted</h3>
    <p><strong>Reported Certificate ID:</strong> {cert_id or 'None'}<br/>
    <strong>Reporter Name:</strong> {name}<br/>
    <strong>Reporter Email:</strong> {email}<br/>
    <strong>Phone:</strong> {phone or 'N/A'}</p>
    <p><strong>Description:</strong><br/>{desc}</p>
    """
    send_transactional_email("support@ytaltech.com", f"New Certificate Complaint: {cert_id}", admin_body)
    
    # Acknowledge reporter
    user_body = f"""
    <h3>Inquiry / Complaint Received - Ytal Tech Solutions</h3>
    <p>Dear {name},</p>
    <p>Thank you for reaching out to Ytal Tech Solutions & Services LLP regarding certificate ID <strong>{cert_id or 'N/A'}</strong>.</p>
    <p>Our compliance team has received your submission and will review the case against our verified registry records. We will contact you at this email address if further details are required.</p>
    """
    send_transactional_email(email, "Certificate Verification Query Received", user_body)
    
    flash("Your report / query has been submitted successfully to the Ytal Tech Compliance Team.", "success")
    return redirect(url_for('certificates.verify_certificate', cert=cert_id))
