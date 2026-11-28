import os
from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, jsonify, current_app, send_file, send_from_directory, abort
)
from elearning.models import db, Course, Enrolment, PaymentOrder, User, SystemSetting
from elearning.auth import login_required, get_current_user
from elearning.utils import (
    save_uploaded_file, generate_order_reference, generate_qr_code_image,
    log_audit_event, send_transactional_email, generate_pdf_invoice
)

payments_bp = Blueprint('payments', __name__, url_prefix='/elearning/payment')

@payments_bp.route('/order/<order_ref>', methods=['GET'])
@login_required
def payment_page(order_ref):
    user = get_current_user()
    order = PaymentOrder.query.filter_by(order_reference=order_ref).first_or_404()
    
    # Authorize access
    if order.user_id != user.id and not user.has_role('super_admin', 'finance_admin'):
        flash("You are not authorized to view this payment order.", "danger")
        return redirect(url_for('elearning.courses_list'))
        
    # Get system settings for bank details and UPI ID
    bank_name = SystemSetting.get('bank_name', current_app.config['BANK_NAME'])
    bank_branch = SystemSetting.get('bank_branch', current_app.config['BANK_BRANCH'])
    account_name = SystemSetting.get('bank_account_name', current_app.config['BANK_ACCOUNT_NAME'])
    account_num = SystemSetting.get('bank_account_number', current_app.config['BANK_ACCOUNT_NUMBER'])
    ifsc = SystemSetting.get('bank_ifsc', current_app.config['BANK_IFSC'])
    account_type = SystemSetting.get('bank_account_type', current_app.config['BANK_ACCOUNT_TYPE'])
    upi_id = SystemSetting.get('upi_id', current_app.config['UPI_ID'])
    timeline = SystemSetting.get('payment_verification_timeline', 'Within 12-24 business hours')
    
    # Generate UPI QR code for this specific order
    # UPI URI format: upi://pay?pa=upi_id&pn=Name&am=Amount&cu=INR&tr=OrderRef&tn=YtalTech+OrderRef
    upi_uri = f"upi://pay?pa={upi_id}&pn=Ytal+Tech+Solutions&am={order.expected_amount:.2f}&cu={order.currency}&tr={order.order_reference}&tn=CertFee+{order.order_reference}"
    qr_filename = f"upi_qr_{order.order_reference}.png"
    qr_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'receipts', qr_filename)
    generate_qr_code_image(upi_uri, qr_path)
    
    # Official SBI UPI QR code image from SystemSetting
    sbi_qr_setting = SystemSetting.get('upi_qr_image', 'elearning/img/sbi_upi_qr_poster.png')
    qr_relative_url = sbi_qr_setting if sbi_qr_setting else f"uploads/receipts/{qr_filename}"
    
    return render_template(
        'elearning/payment.html',
        order=order,
        bank_name=bank_name,
        bank_branch=bank_branch,
        account_name=account_name,
        account_num=account_num,
        ifsc=ifsc,
        account_type=account_type,
        upi_id=upi_id,
        timeline=timeline,
        qr_image_url=qr_relative_url,
        upi_uri=upi_uri
    )


@payments_bp.route('/order/<order_ref>/submit', methods=['POST'])
@login_required
def submit_payment(order_ref):
    user = get_current_user()
    order = PaymentOrder.query.filter_by(order_reference=order_ref).first_or_404()
    
    if order.user_id != user.id:
        flash("Unauthorized.", "danger")
        return redirect(url_for('elearning.courses_list'))
        
    is_draft = request.form.get('action') == 'save_draft'
    
    amount_str = request.form.get('amount_paid', '').strip()
    payment_mode = request.form.get('payment_mode', '').strip()
    date_str = request.form.get('payment_date', '').strip()
    txn_ref = request.form.get('transaction_reference', '').strip()
    payer_name = request.form.get('payer_name', '').strip()
    payer_upi = request.form.get('payer_account_upi', '').strip()
    remarks = request.form.get('learner_remarks', '').strip()
    customer_gstin = request.form.get('customer_gstin', '').strip().upper()
    customer_org_name = request.form.get('customer_org_name', '').strip()
    customer_billing_address = request.form.get('customer_billing_address', '').strip()
    customer_state = request.form.get('customer_state', '').strip()
    proof_file = request.files.get('proof_file')
    
    errors = []
    
    # Parse amount
    amount_paid = None
    if amount_str:
        try:
            amount_paid = float(amount_str)
        except ValueError:
            errors.append("Please enter a valid numeric amount.")
            
    # Parse date
    payment_date = None
    if date_str:
        try:
            payment_date = datetime.fromisoformat(date_str)
        except Exception:
            try:
                payment_date = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                payment_date = datetime.now(timezone.utc)
                
    # Handle proof file upload
    if proof_file and proof_file.filename:
        filename, err = save_uploaded_file(
            proof_file,
            current_app.config['RECEIPTS_UPLOAD_FOLDER'],
            current_app.config['ALLOWED_PROOF_EXTENSIONS']
        )
        if err:
            errors.append(err)
        else:
            order.proof_file_path = f"uploads/receipts/{filename}"

    # Strict validations if final submission (not draft)
    if not is_draft:
        if not amount_paid or amount_paid <= 0:
            errors.append("Amount paid is mandatory.")
        elif abs(amount_paid - order.expected_amount) > 5.0:  # Allow minimal currency rounding margin
            errors.append(f"Amount entered ({amount_paid}) does not match expected fee ({order.expected_amount:.2f} {order.currency}).")
            
        if not payment_mode:
            errors.append("Payment Mode is required.")
        if not payment_date:
            errors.append("Payment Date & Time is required.")
        if not txn_ref:
            errors.append("Transaction Reference / UTR Number is required.")
        elif len(txn_ref) < 6:
            errors.append("Transaction Reference / UTR must be at least 6 characters.")
            
        if not payer_name:
            errors.append("Payer Name is required.")
            
        if not order.proof_file_path:
            errors.append("Payment screenshot or receipt proof upload is mandatory.")
            
        # Duplicate UTR / transaction reference check across all orders
        if txn_ref:
            duplicate = PaymentOrder.query.filter(
                PaymentOrder.transaction_reference == txn_ref,
                PaymentOrder.id != order.id,
                PaymentOrder.status.in_(['under_review', 'verified_approved', 'certificate_issued', 'certificate_dispatched', 'certificate_delivered'])
            ).first()
            if duplicate:
                errors.append(f"Transaction reference '{txn_ref}' has already been submitted for another order ({duplicate.order_reference}). Duplicate submissions are not permitted.")

    if errors:
        for err in errors:
            flash(err, "danger")
        return redirect(url_for('payments.payment_page', order_ref=order_ref))
        
    # Update order record
    order.amount_paid = amount_paid
    order.payment_mode = payment_mode
    order.payment_date = payment_date or datetime.now(timezone.utc)
    order.transaction_reference = txn_ref
    order.payer_name = payer_name
    order.payer_account_upi = payer_upi
    order.learner_remarks = remarks
    order.customer_gstin = customer_gstin or None
    order.customer_org_name = customer_org_name or None
    order.customer_billing_address = customer_billing_address or None
    order.customer_state = customer_state or None
    
    # Save to user profile for future invoices if provided
    if customer_gstin:
        user.gstin = customer_gstin
    if customer_org_name:
        user.organization_name = customer_org_name
    if customer_billing_address:
        user.billing_address = customer_billing_address
    if customer_state:
        user.state = customer_state
    
    if is_draft:
        order.status = 'pending_submission'
        db.session.commit()
        flash("Payment details saved as draft. You can complete submission at your convenience.", "info")
    else:
        order.status = 'under_review'
        order.submitted_at = datetime.now(timezone.utc)
        db.session.commit()
        
        log_audit_event(
            user.id,
            "PAYMENT_SUBMITTED",
            "PaymentOrder",
            order.id,
            f"Submitted UTR: {txn_ref}, Amount: {amount_paid} {order.currency}"
        )
        
        # Send confirmation email to learner
        email_body = f"""
        <h3>Payment Submission Received - Order Ref: {order.order_reference}</h3>
        <p>Dear {user.first_name},</p>
        <p>Thank you for submitting your payment proof for <strong>{order.course.title}</strong>.</p>
        <p><strong>Claimed Amount:</strong> {order.amount_paid:.2f} {order.currency}<br/>
        <strong>Transaction Reference / UTR:</strong> {order.transaction_reference}<br/>
        <strong>Payment Mode:</strong> {order.payment_mode}</p>
        <p>Our Finance Team will independently verify this transaction against company bank/UPI statements. This verification typically completes within 12 to 24 business hours.</p>
        <p>Once verified, your digital certificate and tax invoice will be generated and available for immediate download.</p>
        """
        send_transactional_email(user.email, f"Payment Proof Received: {order.order_reference}", email_body)
        
        flash("Payment submission received! Your payment is now under review by our finance team.", "success")
        
    return redirect(url_for('payments.payment_status', order_ref=order_ref))


@payments_bp.route('/status/<order_ref>')
@login_required
def payment_status(order_ref):
    user = get_current_user()
    order = PaymentOrder.query.filter_by(order_reference=order_ref).first_or_404()
    
    if order.user_id != user.id and not user.has_role('super_admin', 'finance_admin'):
        flash("Unauthorized.", "danger")
        return redirect(url_for('elearning.courses_list'))
        
    return render_template('elearning/payment_status.html', order=order)


@payments_bp.route('/delivery-address/<int:enrolment_id>', methods=['GET', 'POST'])
@login_required
def delivery_address(enrolment_id):
    user = get_current_user()
    enrolment = Enrolment.query.filter_by(id=enrolment_id, user_id=user.id).first_or_404()
    
    if request.method == 'POST':
        user.house_no = request.form.get('house_no', '').strip()
        user.building = request.form.get('building', '').strip()
        user.street = request.form.get('street', '').strip()
        user.area = request.form.get('area', '').strip()
        user.city = request.form.get('city', '').strip()
        user.state = request.form.get('state', '').strip()
        user.country = request.form.get('country', 'India').strip()
        user.pincode = request.form.get('pincode', '').strip()
        user.phone = request.form.get('phone', '').strip()
        
        errors = []
        if not user.house_no or not user.street:
            errors.append("House / Flat Number and Street Address are required.")
        if not user.city or not user.state:
            errors.append("City and State are required.")
        if not user.pincode:
            errors.append("Postal / PIN code is required.")
        if not user.phone:
            errors.append("Phone number is required for courier delivery.")
            
        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template('elearning/address_form.html', enrolment=enrolment, user=user)
            
        db.session.commit()
        log_audit_event(user.id, "DELIVERY_ADDRESS_UPDATED", "User", user.id, "Updated physical certificate dispatch address")
        flash("Delivery address saved successfully!", "success")
        
        # Check if there is an active payment order to proceed with
        order = PaymentOrder.query.filter_by(enrolment_id=enrolment.id).first()
        if order:
            return redirect(url_for('payments.payment_page', order_ref=order.order_reference))
        return redirect(url_for('elearning.course_detail', slug=enrolment.course.slug))
        
    return render_template('elearning/address_form.html', enrolment=enrolment, user=user)


@payments_bp.route('/invoice/<order_ref>')
@login_required
def download_invoice(order_ref):
    user = get_current_user()
    order = PaymentOrder.query.filter_by(order_reference=order_ref).first_or_404()
    
    if order.user_id != user.id and not user.has_role('super_admin', 'finance_admin'):
        flash("Unauthorized.", "danger")
        return redirect(url_for('elearning.courses_list'))
        
    if order.status not in ['verified_approved', 'certificate_issued', 'certificate_dispatched', 'certificate_delivered']:
        flash("Tax invoice is available once payment is verified and approved.", "warning")
        return redirect(url_for('payments.payment_status', order_ref=order_ref))
        
    pdf_path = generate_pdf_invoice(payment_order)
    return send_file(pdf_path, as_attachment=True, download_name=f"Invoice_{order.order_reference}.pdf", mimetype='application/pdf')


@payments_bp.route('/receipt-file/<int:order_id>')
@login_required
def view_proof_file(order_id):
    """
    Secure, authenticated payment proof access.
    Only the order owner or super_admin / finance_admin can view the uploaded payment receipt.
    """
    user = get_current_user()
    order = PaymentOrder.query.get_or_404(order_id)
    
    if order.user_id != user.id and not user.has_role('super_admin', 'finance_admin'):
        flash("Unauthorized access to payment proof.", "danger")
        return redirect(url_for('elearning.courses_list'))
        
    if not order.proof_file_path:
        abort(404)
        
    filename = os.path.basename(order.proof_file_path)
    # Check both storage folder and legacy static uploads
    receipt_dir = current_app.config['RECEIPTS_UPLOAD_FOLDER']
    if not os.path.exists(os.path.join(receipt_dir, filename)):
        receipt_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'receipts')
        
    return send_from_directory(receipt_dir, filename)
