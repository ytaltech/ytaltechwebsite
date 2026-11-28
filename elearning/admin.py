import io
import csv
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, current_app, Response, send_from_directory, abort
)
from elearning.models import (
    db, User, Course, Slide, MCQ, Enrolment,
    PaymentOrder, Certificate, CertificateComplaint,
    AuditLog, SystemSetting
)
from elearning.auth import login_required, role_required, get_current_user
from elearning.utils import (
    save_uploaded_file, parse_pptx_slides, log_audit_event,
    send_transactional_email, generate_pdf_certificate
)
from elearning.certificates import issue_certificate_if_eligible

admin_bp = Blueprint('admin', __name__, url_prefix='/elearning/admin')

@admin_bp.route('/')
@role_required('super_admin', 'course_admin', 'content_editor', 'finance_admin', 'certificate_admin', 'support_agent')
def dashboard():
    user = get_current_user()
    
    # Calculate key metrics
    total_users = User.query.count()
    total_enrolments = Enrolment.query.count()
    completed_courses = Enrolment.query.filter_by(slides_completed=True).count()
    
    pending_payments = PaymentOrder.query.filter_by(status='under_review').count()
    approved_payments = PaymentOrder.query.filter(
        PaymentOrder.status.in_(['verified_approved', 'certificate_issued', 'certificate_dispatched', 'certificate_delivered'])
    ).all()
    
    total_revenue_inr = sum(p.expected_amount for p in approved_payments if p.currency == 'INR')
    total_revenue_usd = sum(p.expected_amount for p in approved_payments if p.currency == 'USD')
    
    total_certificates = Certificate.query.filter_by(status='valid').count()
    pending_dispatch = Certificate.query.filter_by(dispatch_status='pending_dispatch').count()
    open_complaints = CertificateComplaint.query.filter_by(status='open').count()
    
    recent_payments = PaymentOrder.query.order_by(PaymentOrder.id.desc()).limit(5).all()
    recent_audit_logs = AuditLog.query.order_by(AuditLog.id.desc()).limit(10).all()
    
    return render_template(
        'elearning/admin/dashboard.html',
        user=user,
        total_users=total_users,
        total_enrolments=total_enrolments,
        completed_courses=completed_courses,
        pending_payments=pending_payments,
        total_revenue_inr=total_revenue_inr,
        total_revenue_usd=total_revenue_usd,
        total_certificates=total_certificates,
        pending_dispatch=pending_dispatch,
        open_complaints=open_complaints,
        recent_payments=recent_payments,
        recent_audit_logs=recent_audit_logs
    )


# ==========================================
# 1. Manual Payment Verification
# ==========================================
@admin_bp.route('/payments')
@role_required('super_admin', 'finance_admin')
def payments_list():
    status_filter = request.args.get('status', '')
    course_filter = request.args.get('course_id', '')
    search_query = request.args.get('q', '').strip()
    
    query = PaymentOrder.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if course_filter:
        query = query.filter_by(course_id=int(course_filter))
    if search_query:
        query = query.join(User, PaymentOrder.user_id == User.id).filter(
            (PaymentOrder.order_reference.ilike(f"%{search_query}%")) |
            (PaymentOrder.transaction_reference.ilike(f"%{search_query}%")) |
            (User.email.ilike(f"%{search_query}%")) |
            (User.first_name.ilike(f"%{search_query}%")) |
            (User.last_name.ilike(f"%{search_query}%"))
        )
        
    orders = query.order_by(PaymentOrder.id.desc()).all()
    courses = Course.query.all()
    
    return render_template(
        'elearning/admin/payments.html',
        orders=orders,
        courses=courses,
        status_filter=status_filter,
        course_filter=course_filter,
        search_query=search_query
    )


@admin_bp.route('/payments/<int:order_id>')
@role_required('super_admin', 'finance_admin')
def payment_detail(order_id):
    order = PaymentOrder.query.get_or_404(order_id)
    enrolment = order.enrolment
    user = get_current_user()
    
    # Check if duplicate UTR exists
    duplicate_orders = []
    if order.transaction_reference:
        duplicate_orders = PaymentOrder.query.filter(
            PaymentOrder.transaction_reference == order.transaction_reference,
            PaymentOrder.id != order.id
        ).all()
        
    return render_template(
        'elearning/admin/payment_detail.html',
        order=order,
        enrolment=enrolment,
        user=user,
        duplicate_orders=duplicate_orders
    )


@admin_bp.route('/payments/<int:order_id>/action', methods=['POST'])
@role_required('super_admin', 'finance_admin')
def process_payment_action(order_id):
    order = PaymentOrder.query.get_or_404(order_id)
    user = get_current_user()
    
    # Security Rule 4.5: Prevent admin from approving their own payment
    if order.user_id == user.id and not user.role == 'super_admin':
        flash("Separation of duties violation: You cannot verify or approve your own payment submission.", "danger")
        return redirect(url_for('admin.payment_detail', order_id=order.id))
        
    action = request.form.get('action')
    admin_notes = request.form.get('admin_notes', '').strip()
    rejection_reason = request.form.get('rejection_reason', '').strip()
    add_info_notes = request.form.get('additional_info_notes', '').strip()
    
    old_status = order.status
    
    if action == 'approve':
        order.status = 'verified_approved'
        order.verified_by_user_id = user.id
        order.verified_at = datetime.now(timezone.utc)
        order.admin_notes = admin_notes
        db.session.commit()
        
        log_audit_event(
            user.id,
            "PAYMENT_APPROVED",
            "PaymentOrder",
            order.id,
            f"Approved payment {order.order_reference} for {order.expected_amount} {order.currency}"
        )
        
        # Check if learner is already eligible for certificate
        cert, err = issue_certificate_if_eligible(order.enrolment)
        
        # Send approval notification email
        email_body = f"""
        <h3>Payment Verified & Approved - Order: {order.order_reference}</h3>
        <p>Dear {order.user.first_name},</p>
        <p>Your payment of <strong>{order.expected_amount:.2f} {order.currency}</strong> for <strong>{order.course.title}</strong> has been successfully verified and approved.</p>
        <p>Transaction Reference: {order.transaction_reference}</p>
        <p>You can now download your official Tax Invoice and Certificate from your learner dashboard.</p>
        """
        send_transactional_email(order.user.email, f"Payment Verified: {order.course.title}", email_body)
        flash(f"Payment {order.order_reference} has been approved!", "success")
        
    elif action == 'reject':
        if not rejection_reason:
            flash("A clear reason for rejection is mandatory.", "danger")
            return redirect(url_for('admin.payment_detail', order_id=order.id))
            
        order.status = 'rejected'
        order.rejection_reason = rejection_reason
        order.admin_notes = admin_notes
        order.verified_by_user_id = user.id
        order.verified_at = datetime.now(timezone.utc)
        db.session.commit()
        
        log_audit_event(
            user.id,
            "PAYMENT_REJECTED",
            "PaymentOrder",
            order.id,
            f"Rejected payment {order.order_reference}. Reason: {rejection_reason}"
        )
        
        email_body = f"""
        <h3>Payment Verification Update - Order: {order.order_reference}</h3>
        <p>Dear {order.user.first_name},</p>
        <p>We were unable to verify your manual payment submission for <strong>{order.course.title}</strong>.</p>
        <p><strong>Reason for rejection:</strong> {rejection_reason}</p>
        <p>Please log in to your dashboard to review details or submit corrected payment information.</p>
        """
        send_transactional_email(order.user.email, f"Payment Update: {order.order_reference}", email_body)
        flash("Payment has been marked as rejected.", "warning")
        
    elif action == 'request_info':
        if not add_info_notes:
            flash("Please specify what additional information or clearer proof is required.", "danger")
            return redirect(url_for('admin.payment_detail', order_id=order.id))
            
        order.status = 'additional_info_required'
        order.additional_info_notes = add_info_notes
        order.admin_notes = admin_notes
        db.session.commit()
        
        log_audit_event(
            user.id,
            "PAYMENT_INFO_REQUESTED",
            "PaymentOrder",
            order.id,
            f"Requested info for order {order.order_reference}: {add_info_notes}"
        )
        
        email_body = f"""
        <h3>Action Required: Additional Information for Order {order.order_reference}</h3>
        <p>Dear {order.user.first_name},</p>
        <p>Our Finance Administrator has reviewed your payment proof for <strong>{order.course.title}</strong> and requires additional clarification before approving:</p>
        <p><strong>Admin Request:</strong> {add_info_notes}</p>
        <p>Please log in to your account and re-upload your receipt or update your transaction reference.</p>
        """
        send_transactional_email(order.user.email, f"Action Required: Payment Order {order.order_reference}", email_body)
        flash("Additional information request sent to learner.", "info")
        
    elif action == 'refund':
        order.status = 'refund_processed'
        order.admin_notes = f"{order.admin_notes or ''}\n[Refund Processed] {admin_notes}"
        db.session.commit()
        log_audit_event(user.id, "PAYMENT_REFUND_RECORDED", "PaymentOrder", order.id, f"Refund recorded: {admin_notes}")
        flash("Refund has been recorded.", "info")
        
    return redirect(url_for('admin.payment_detail', order_id=order.id))


@admin_bp.route('/payments/export-csv')
@role_required('super_admin', 'finance_admin')
def export_payments_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Order Reference', 'Learner Name', 'Learner Email', 'Course Title',
        'Region', 'Currency', 'Base Amount', 'GST Amount', 'Total Amount',
        'Customer GSTIN', 'Status', 'Payment Mode',
        'Transaction Ref / UTR', 'Payment Date', 'Submission Date',
        'Verified By', 'Verified Date'
    ])
    
    orders = PaymentOrder.query.order_by(PaymentOrder.id.desc()).all()
    for o in orders:
        verifier_name = o.verifier.full_name if o.verifier else ''
        writer.writerow([
            o.order_reference,
            o.user.full_name,
            o.user.email,
            o.course.title,
            o.region_label,
            o.currency,
            f"{o.base_amount:.2f}",
            f"{(o.gst_amount or 0.0):.2f}",
            f"{o.total_amount:.2f}",
            o.customer_gstin or '',
            o.status,
            o.payment_mode or '',
            o.transaction_reference or '',
            o.payment_date.strftime('%Y-%m-%d %H:%M') if o.payment_date else '',
            o.submitted_at.strftime('%Y-%m-%d %H:%M') if o.submitted_at else '',
            verifier_name,
            o.verified_at.strftime('%Y-%m-%d %H:%M') if o.verified_at else ''
        ])
        
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=YtalTech_Payments_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


# ==========================================
# 2. Course & Slide CMS
# ==========================================
@admin_bp.route('/courses')
@role_required('super_admin', 'course_admin', 'content_editor')
def courses_cms():
    courses = Course.query.all()
    return render_template('elearning/admin/courses.html', courses=courses)


@admin_bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@role_required('super_admin', 'course_admin')
def edit_course(course_id):
    course = Course.query.get_or_404(course_id)
    user = get_current_user()
    
    if request.method == 'POST':
        course.title = request.form.get('title', course.title).strip()
        course.short_description = request.form.get('short_description', course.short_description).strip()
        course.overview = request.form.get('overview', course.overview).strip()
        course.estimated_duration = request.form.get('estimated_duration', course.estimated_duration).strip()
        course.language = request.form.get('language', course.language).strip()
        
        try:
            course.price_inr = float(request.form.get('price_inr', course.price_inr))
            course.gst_rate = float(request.form.get('gst_rate', course.gst_rate))
            course.price_usd = float(request.form.get('price_usd', course.price_usd))
        except ValueError:
            flash("Invalid numeric pricing values.", "danger")
            return redirect(url_for('admin.edit_course', course_id=course.id))
            
        course.version = request.form.get('version', course.version).strip()
        course.is_active = bool(request.form.get('is_active'))
        
        db.session.commit()
        log_audit_event(user.id, "COURSE_UPDATED", "Course", course.id, f"Updated course metadata {course.title}")
        flash("Course details updated successfully.", "success")
        return redirect(url_for('admin.courses_cms'))
        
    return render_template('elearning/admin/course_edit.html', course=course)


@admin_bp.route('/courses/<int:course_id>/slides')
@role_required('super_admin', 'course_admin', 'content_editor')
def course_slides(course_id):
    course = Course.query.get_or_404(course_id)
    slides = Slide.query.filter_by(course_id=course.id).order_by(Slide.slide_number).all()
    return render_template('elearning/admin/slides.html', course=course, slides=slides)


@admin_bp.route('/courses/<int:course_id>/slides/add', methods=['GET', 'POST'])
@role_required('super_admin', 'course_admin', 'content_editor')
def add_slide(course_id):
    course = Course.query.get_or_404(course_id)
    user = get_current_user()
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content_html', '').strip()
        dwell = int(request.form.get('minimum_dwell_seconds', 60))
        
        max_num = db.session.query(db.func.max(Slide.slide_number)).filter_by(course_id=course.id).scalar() or 0
        new_slide = Slide(
            course_id=course.id,
            slide_number=max_num + 1,
            title=title,
            content_html=content,
            minimum_dwell_seconds=dwell,
            is_active=True
        )
        db.session.add(new_slide)
        db.session.commit()
        
        log_audit_event(user.id, "SLIDE_CREATED", "Slide", new_slide.id, f"Added slide #{new_slide.slide_number} to {course.title}")
        flash("New slide added successfully.", "success")
        return redirect(url_for('admin.course_slides', course_id=course.id))
        
    return render_template('elearning/admin/slide_edit.html', course=course, slide=None)


@admin_bp.route('/slides/<int:slide_id>/edit', methods=['GET', 'POST'])
@role_required('super_admin', 'course_admin', 'content_editor')
def edit_slide(slide_id):
    slide = Slide.query.get_or_404(slide_id)
    user = get_current_user()
    
    if request.method == 'POST':
        slide.title = request.form.get('title', slide.title).strip()
        slide.content_html = request.form.get('content_html', slide.content_html).strip()
        slide.minimum_dwell_seconds = int(request.form.get('minimum_dwell_seconds', slide.minimum_dwell_seconds))
        slide.is_active = bool(request.form.get('is_active'))
        
        db.session.commit()
        log_audit_event(user.id, "SLIDE_UPDATED", "Slide", slide.id, f"Updated slide #{slide.slide_number}")
        flash("Slide updated successfully.", "success")
        return redirect(url_for('admin.course_slides', course_id=slide.course_id))
        
    return render_template('elearning/admin/slide_edit.html', course=slide.course, slide=slide)


@admin_bp.route('/courses/<int:course_id>/upload-pptx', methods=['POST'])
@role_required('super_admin', 'course_admin', 'content_editor')
def upload_course_pptx(course_id):
    """
    Parses an uploaded PowerPoint (.pptx) file and imports slides automatically.
    """
    course = Course.query.get_or_404(course_id)
    user = get_current_user()
    ppt_file = request.files.get('pptx_file')
    
    if not ppt_file or not ppt_file.filename:
        flash("Please select a PowerPoint (.pptx) file to upload.", "danger")
        return redirect(url_for('admin.course_slides', course_id=course.id))
        
    filename, err = save_uploaded_file(
        ppt_file,
        current_app.config['SLIDES_UPLOAD_FOLDER'],
        {'pptx', 'ppt'}
    )
    if err:
        flash(err, "danger")
        return redirect(url_for('admin.course_slides', course_id=course.id))
        
    full_path = os.path.join(current_app.config['SLIDES_UPLOAD_FOLDER'], filename)
    parsed_slides, parse_err = parse_pptx_slides(full_path)
    
    if parse_err:
        flash(f"Error parsing PPT file: {parse_err}", "danger")
        return redirect(url_for('admin.course_slides', course_id=course.id))
        
    # Append or replace option
    mode = request.form.get('mode', 'append')
    if mode == 'replace':
        Slide.query.filter_by(course_id=course.id).delete()
        db.session.commit()
        start_idx = 1
    else:
        max_num = db.session.query(db.func.max(Slide.slide_number)).filter_by(course_id=course.id).scalar() or 0
        start_idx = max_num + 1
        
    imported_count = 0
    for s in parsed_slides:
        new_slide = Slide(
            course_id=course.id,
            slide_number=start_idx,
            title=s['title'],
            content_html=s['content_html'],
            minimum_dwell_seconds=60,
            is_active=True
        )
        db.session.add(new_slide)
        start_idx += 1
        imported_count += 1
        
    db.session.commit()
    log_audit_event(user.id, "PPTX_UPLOADED", "Course", course.id, f"Imported {imported_count} slides from PPT")
    flash(f"Successfully imported {imported_count} slides from presentation!", "success")
    return redirect(url_for('admin.course_slides', course_id=course.id))


# ==========================================
# 3. MCQ Bank Management
# ==========================================
@admin_bp.route('/mcqs')
@role_required('super_admin', 'course_admin', 'content_editor')
def mcqs_list():
    course_filter = request.args.get('course_id', '')
    type_filter = request.args.get('type', '')
    search_query = request.args.get('q', '').strip()
    
    query = MCQ.query
    if course_filter:
        query = query.filter_by(course_id=int(course_filter))
    if type_filter:
        query = query.filter_by(type=type_filter)
    if search_query:
        query = query.filter(MCQ.question_text.ilike(f'%{search_query}%') | MCQ.explanation.ilike(f'%{search_query}%'))
        
    mcqs = query.order_by(MCQ.id.desc()).all()
    courses = Course.query.all()
    
    return render_template(
        'elearning/admin/mcqs.html',
        mcqs=mcqs,
        courses=courses,
        course_filter=course_filter,
        type_filter=type_filter,
        search_query=search_query
    )


@admin_bp.route('/mcqs/add', methods=['GET', 'POST'])
@role_required('super_admin', 'course_admin', 'content_editor')
def add_mcq():
    user = get_current_user()
    courses = Course.query.all()
    
    if request.method == 'POST':
        course_id = int(request.form.get('course_id'))
        q_type = request.form.get('type', 'final_test')
        part = request.form.get('part', 'B') if q_type == 'final_test' else None
        slide_id = request.form.get('slide_id')
        slide_id = int(slide_id) if slide_id and slide_id.isdigit() else None
        
        q_text = request.form.get('question_text', '').strip()
        op_a = request.form.get('option_a', '').strip()
        op_b = request.form.get('option_b', '').strip()
        op_c = request.form.get('option_c', '').strip()
        op_d = request.form.get('option_d', '').strip()
        correct = request.form.get('correct_option', 'A').strip().upper()
        explanation = request.form.get('explanation', '').strip()
        difficulty = request.form.get('difficulty', 'medium')
        
        new_mcq = MCQ(
            course_id=course_id,
            slide_id=slide_id,
            type=q_type,
            part=part,
            question_text=q_text,
            option_a=op_a,
            option_b=op_b,
            option_c=op_c,
            option_d=op_d,
            correct_option=correct,
            explanation=explanation,
            difficulty=difficulty,
            marks=1,
            is_active=True
        )
        db.session.add(new_mcq)
        db.session.commit()
        
        log_audit_event(user.id, "MCQ_CREATED", "MCQ", new_mcq.id, f"Created {q_type} MCQ")
        flash("Question added to question bank successfully.", "success")
        return redirect(url_for('admin.mcqs_list', course_id=course_id))
        
    return render_template('elearning/admin/mcq_edit.html', courses=courses, mcq=None)


@admin_bp.route('/mcqs/<int:mcq_id>/edit', methods=['GET', 'POST'])
@role_required('super_admin', 'course_admin', 'content_editor')
def edit_mcq(mcq_id):
    """Allows full editing and saving of question text, options, correct answers, and explanations."""
    user = get_current_user()
    mcq = MCQ.query.get_or_404(mcq_id)
    courses = Course.query.all()
    
    if request.method == 'POST':
        course_id = int(request.form.get('course_id'))
        q_type = request.form.get('type', 'final_test')
        part = request.form.get('part', 'B') if q_type == 'final_test' else None
        q_text = request.form.get('question_text', '').strip()
        op_a = request.form.get('option_a', '').strip()
        op_b = request.form.get('option_b', '').strip()
        op_c = request.form.get('option_c', '').strip()
        op_d = request.form.get('option_d', '').strip()
        correct = request.form.get('correct_option', 'A').strip().upper()
        explanation = request.form.get('explanation', '').strip()
        difficulty = request.form.get('difficulty', 'medium')
        is_active = (request.form.get('is_active') == '1')
        
        if not all([course_id, q_text, op_a, op_b, op_c, op_d, correct]):
            flash("All question fields and options are mandatory.", "danger")
            return render_template('elearning/admin/mcq_edit.html', courses=courses, mcq=mcq)
            
        mcq.course_id = course_id
        mcq.type = q_type
        mcq.part = part
        mcq.question_text = q_text
        mcq.option_a = op_a
        mcq.option_b = op_b
        mcq.option_c = op_c
        mcq.option_d = op_d
        mcq.correct_option = correct
        mcq.explanation = explanation
        mcq.difficulty = difficulty
        mcq.is_active = is_active
        
        db.session.commit()
        log_audit_event(user.id, "MCQ_UPDATED", "MCQ", mcq.id, f"Updated {q_type} MCQ #{mcq.id}")
        flash(f"Question #{mcq.id} updated and saved successfully!", "success")
        return redirect(url_for('admin.mcqs_list', course_id=course_id))
        
    return render_template('elearning/admin/mcq_edit.html', courses=courses, mcq=mcq)


# ==========================================
# 4. Certificates & Dispatch Management
# ==========================================
@admin_bp.route('/certificates')
@role_required('super_admin', 'certificate_admin')
def certificates_list():
    certs = Certificate.query.order_by(Certificate.id.desc()).all()
    return render_template('elearning/admin/certificates.html', certificates=certs)


@admin_bp.route('/certificates/<int:cert_id>/dispatch', methods=['POST'])
@role_required('super_admin', 'certificate_admin')
def update_certificate_dispatch(cert_id):
    cert = Certificate.query.get_or_404(cert_id)
    user = get_current_user()
    
    dispatch_status = request.form.get('dispatch_status', cert.dispatch_status)
    courier = request.form.get('courier_name', cert.courier_name)
    tracking = request.form.get('tracking_number', cert.tracking_number)
    
    cert.dispatch_status = dispatch_status
    cert.courier_name = courier
    cert.tracking_number = tracking
    
    if dispatch_status == 'dispatched' and not cert.dispatched_at:
        cert.dispatched_at = datetime.now(timezone.utc)
    elif dispatch_status == 'delivered' and not cert.delivered_at:
        cert.delivered_at = datetime.now(timezone.utc)
        
    # Also update payment order status
    if cert.payment_order:
        if dispatch_status == 'dispatched':
            cert.payment_order.status = 'certificate_dispatched'
        elif dispatch_status == 'delivered':
            cert.payment_order.status = 'certificate_delivered'
            
    db.session.commit()
    log_audit_event(
        user.id,
        "CERTIFICATE_DISPATCH_UPDATED",
        "Certificate",
        cert.id,
        f"Status: {dispatch_status}, Courier: {courier}, Tracking: {tracking}"
    )
    
    # Notify learner
    email_body = f"""
    <h3>Physical Certificate Dispatch Update</h3>
    <p>Dear {cert.user.full_name},</p>
    <p>We have an update regarding the physical delivery of your Certificate for <strong>{cert.course.title}</strong>:</p>
    <p><strong>Dispatch Status:</strong> {dispatch_status.replace('_', ' ').title()}<br/>
    <strong>Courier Partner:</strong> {courier or 'Standard Postal Delivery'}<br/>
    <strong>Tracking Number:</strong> {tracking or 'Assigned upon pickup'}</p>
    <p>You can track the live status anytime through your learner portal.</p>
    """
    send_transactional_email(cert.user.email, f"Certificate Dispatch Update: {cert.certificate_id}", email_body)
    
    flash("Certificate dispatch details updated.", "success")
    return redirect(url_for('admin.certificates_list'))


@admin_bp.route('/certificates/<int:cert_id>/revoke', methods=['POST'])
@role_required('super_admin', 'certificate_admin')
def revoke_certificate(cert_id):
    cert = Certificate.query.get_or_404(cert_id)
    user = get_current_user()
    reason = request.form.get('revocation_reason', '').strip()
    
    if not reason:
        flash("A reason for revocation is required.", "danger")
        return redirect(url_for('admin.certificates_list'))
        
    cert.status = 'revoked'
    cert.revocation_reason = reason
    db.session.commit()
    
    log_audit_event(user.id, "CERTIFICATE_REVOKED", "Certificate", cert.id, f"Revoked: {reason}")
    flash(f"Certificate {cert.certificate_id} has been revoked.", "warning")
    return redirect(url_for('admin.certificates_list'))


# ==========================================
# 5. Complaints Management
# ==========================================
@admin_bp.route('/complaints')
@role_required('super_admin', 'support_agent')
def complaints_list():
    complaints = CertificateComplaint.query.order_by(CertificateComplaint.id.desc()).all()
    return render_template('elearning/admin/complaints.html', complaints=complaints)


@admin_bp.route('/complaints/<int:complaint_id>/update', methods=['POST'])
@role_required('super_admin', 'support_agent')
def update_complaint(complaint_id):
    complaint = CertificateComplaint.query.get_or_404(complaint_id)
    user = get_current_user()
    
    status = request.form.get('status', complaint.status)
    notes = request.form.get('admin_notes', complaint.admin_notes)
    
    complaint.status = status
    complaint.admin_notes = notes
    db.session.commit()
    
    log_audit_event(user.id, "COMPLAINT_UPDATED", "CertificateComplaint", complaint.id, f"Status updated to {status}")
    flash("Complaint updated successfully.", "success")
    return redirect(url_for('admin.complaints_list'))


@admin_bp.route('/complaints/<int:complaint_id>/attachment')
@role_required('super_admin', 'certificate_admin', 'support_agent')
def complaint_attachment(complaint_id):
    """Secure, authenticated view of reported certificate complaint attachments."""
    complaint = CertificateComplaint.query.get_or_404(complaint_id)
    if not complaint.attachment_path:
        abort(404)
    filename = os.path.basename(complaint.attachment_path)
    receipt_dir = current_app.config['RECEIPTS_UPLOAD_FOLDER']
    if not os.path.exists(os.path.join(receipt_dir, filename)):
        receipt_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'receipts')
    return send_from_directory(receipt_dir, filename)


# ==========================================
# 6. User Management
# ==========================================
@admin_bp.route('/users')
@role_required('super_admin')
def users_list():
    users = User.query.order_by(User.id.desc()).all()
    return render_template('elearning/admin/users.html', users=users)


@admin_bp.route('/users/<int:user_id>/role', methods=['POST'])
@role_required('super_admin')
def update_user_role(user_id):
    target_user = User.query.get_or_404(user_id)
    user = get_current_user()
    new_role = request.form.get('role')
    
    if user.id == target_user.id and new_role != 'super_admin':
        flash("Action denied: You cannot revoke super_admin privileges from your own active account.", "danger")
        return redirect(url_for('admin.users_list'))

    valid_roles = ['learner', 'super_admin', 'course_admin', 'content_editor', 'finance_admin', 'certificate_admin', 'support_agent']
    if new_role in valid_roles:
        target_user.role = new_role
        db.session.commit()
        log_audit_event(user.id, "ROLE_CHANGED", "User", target_user.id, f"Changed role to {new_role}")
        flash(f"Role updated to {new_role} for {target_user.email}", "success")
        
    return redirect(url_for('admin.users_list'))


# ==========================================
# 7. Audit Logs & System Settings
# ==========================================
@admin_bp.route('/audit-logs')
@role_required('super_admin')
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.id.desc()).limit(150).all()
    return render_template('elearning/admin/audit_logs.html', logs=logs)


@admin_bp.route('/settings', methods=['GET', 'POST'])
@role_required('super_admin')
def system_settings():
    user = get_current_user()
    
    if request.method == 'POST':
        for key in request.form:
            if key != 'csrf_token':
                SystemSetting.set(key, request.form.get(key).strip())
                
        log_audit_event(user.id, "SETTINGS_UPDATED", "SystemSetting", "ALL", "Updated global payment and course configurations")
        flash("System settings saved successfully.", "success")
        return redirect(url_for('admin.system_settings'))
        
    settings = SystemSetting.query.all()
    settings_dict = {s.key: s.value for s in settings}
    return render_template('elearning/admin/settings.html', settings=settings_dict)
