import os
import uuid
import secrets
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from elearning.models import db, User
from elearning.utils import (
    validate_password_complexity,
    calculate_password_strength,
    check_rate_limit,
    log_audit_event,
    send_transactional_email,
    get_safe_redirect_url
)

auth_bp = Blueprint('auth', __name__, url_prefix='/elearning')

def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return db.session.get(User, user_id)
    return None

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please sign up or log in to access the e-learning courses.", "warning")
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash("Authentication required.", "warning")
                return redirect(url_for('auth.login', next=request.url))
            user = get_current_user()
            if not user or not user.has_role(*roles):
                flash("You do not have permission to access this administrative resource.", "danger")
                return redirect(url_for('elearning.courses_list'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    next_url = get_safe_redirect_url(request.args.get('next') or request.form.get('next'))
    
    if request.method == 'POST':
        client_ip = request.remote_addr or '127.0.0.1'
        if not check_rate_limit(f"reg_{client_ip}", max_attempts=5, window_seconds=60):
            flash("Too many registration attempts. Please wait a minute before trying again.", "danger")
            return render_template('elearning/register.html', next=next_url)
        
        first_name = request.form.get('first_name', '').strip()
        middle_name = request.form.get('middle_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        age_str = request.form.get('age', '').strip()
        gender = request.form.get('gender', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        dpdp_consent = request.form.get('dpdp_consent')
        
        # Validations
        errors = []
        if not first_name or not last_name:
            errors.append("First Name and Last Name are required.")
        if not email or '@' not in email:
            errors.append("A valid email address is required.")
        
        try:
            age = int(age_str)
            if age < 16 or age > 100:
                errors.append("Please enter a valid age between 16 and 100.")
        except ValueError:
            errors.append("Age must be a valid number.")
            age = None
            
        if not gender:
            errors.append("Please select your gender.")
            
        if password != confirm_password:
            errors.append("Password and Confirm Password do not match.")
            
        is_pwd_valid, pwd_errors = validate_password_complexity(password)
        if not is_pwd_valid:
            errors.extend(pwd_errors)
            
        if not dpdp_consent:
            errors.append("You must agree to the Terms of Use and Privacy Notice (India DPDP & GDPR compliance).")
            
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            errors.append("An account with this email address already exists. Please log in.")
            
        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template('elearning/register.html', 
                                   first_name=first_name, middle_name=middle_name,
                                   last_name=last_name, email=email, age=age_str,
                                   gender=gender, next=next_url)
        
        # Create user
        token = uuid.uuid4().hex
        new_user = User(
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            email=email,
            age=age,
            gender=gender,
            role='learner',
            is_verified=False,
            email_verification_token=token,
            is_active=True
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        log_audit_event(new_user.id, "USER_REGISTERED", "User", new_user.id, f"Registered with email {email}")
        
        # Send verification email
        verify_link = url_for('auth.verify_email', token=token, _external=True)
        email_body = f"""
        <h2>Welcome to Ytal Tech E-Learning, {new_user.first_name}!</h2>
        <p>Thank you for registering on the Ytal Tech Solutions & Services LLP e-learning platform.</p>
        <p>Please click the button below to validate your email ID and activate your account:</p>
        <p><a href="{verify_link}" style="display:inline-block;padding:12px 24px;background:#00AEEF;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;">Validate Email ID & Activate Account</a></p>
        <p>Or copy this link to your browser: {verify_link}</p>
        <br>
        <p>Best regards,<br>Ytal Tech Academic & Clinical Training Team</p>
        """
        send_transactional_email(new_user.email, "Validate your Ytal Tech E-Learning Account", email_body)
        
        # User shall be able to log in post sign up ONLY after validating the email id
        flash("Registration successful! A verification email has been sent to your email address from contact@ytaltech.com. Please validate your email ID by clicking the link in the email before logging in.", "success")
        return redirect(url_for('auth.login', email=email, next=next_url))
        
    return render_template('elearning/register.html', next=next_url)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    next_url = get_safe_redirect_url(request.args.get('next') or request.form.get('next'))
    
    if request.method == 'POST':
        client_ip = request.remote_addr or '127.0.0.1'
        if not check_rate_limit(f"login_{client_ip}", max_attempts=6, window_seconds=60):
            flash("Too many failed login attempts. Please wait 60 seconds before trying again.", "danger")
            return render_template('elearning/login.html', next=next_url)
            
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password. Please check your credentials.", "danger")
            return render_template('elearning/login.html', email=email, next=next_url)
            
        if not user.is_active:
            flash("This account has been deactivated. Please contact support@ytaltech.com.", "danger")
            return render_template('elearning/login.html', next=next_url)
            
        # Enforce email validation: user can only log in post sign-up after validating their email
        if not user.is_verified and not user.has_role('super_admin', 'finance_admin', 'certificate_admin'):
            flash("Your email ID has not been validated yet. Please check your inbox for the email from contact@ytaltech.com and click on validate email ID to activate your account before logging in.", "warning")
            return render_template('elearning/login.html', email=email, unverified=True, next=next_url)

        # Session established
        session.clear()
        session['user_id'] = user.id
        session['user_name'] = user.full_name
        session['user_role'] = user.role
        session.permanent = True
        
        log_audit_event(user.id, "USER_LOGIN", "User", user.id, f"Logged in from {client_ip}")
        flash(f"Welcome back, {user.first_name}!", "success")
        
        # Check if profile is complete (e.g. from Google login)
        if not user.has_complete_profile:
            return redirect(url_for('auth.complete_profile', next=next_url))
            
        return redirect(next_url)
        
    return render_template('elearning/login.html', next=next_url)


@auth_bp.route('/google-login')
def google_login():
    """
    Initiates Google OAuth 2.0 authentication.
    Redirects user to Google's official consent screen when client credentials exist.
    """
    next_url = get_safe_redirect_url(request.args.get('next'))
    
    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET')
    
    # 1. Real Google OAuth 2.0 Flow
    if client_id and client_secret:
        state = secrets.token_urlsafe(32)
        session['google_oauth_state'] = state
        session['google_oauth_next'] = next_url
        
        redirect_uri = current_app.config.get('GOOGLE_REDIRECT_URI') or url_for('auth.google_callback', _external=True)
        
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state,
            'access_type': 'online',
            'prompt': 'select_account'
        }
        google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        return redirect(google_auth_url)
        
    # 2. When unconfigured: strictly disabled (no mock simulation backdoors)
    flash("Google Sign-In is currently disabled on this server. Please register or sign in with your email address and password below.", "info")
    return redirect(url_for('auth.login', next=next_url))


@auth_bp.route('/google-callback')
def google_callback():
    """
    Google OAuth 2.0 authorization callback.
    Exchanges authorization code for verified user profile and establishes session.
    """
    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET')
    
    saved_state = session.pop('google_oauth_state', None)
    next_url = session.pop('google_oauth_next', None) or url_for('elearning.courses_list')
    next_url = get_safe_redirect_url(next_url)
    
    # Check for cancellation or error from Google
    error = request.args.get('error')
    if error:
        flash(f"Google sign-in was cancelled ({error}). Please sign in with your email and password.", "warning")
        return redirect(url_for('auth.login', next=next_url))
        
    code = request.args.get('code')
    state = request.args.get('state')
    
    if not code or not state or state != saved_state:
        flash("Invalid Google authentication session. Please try signing in again.", "danger")
        return redirect(url_for('auth.login', next=next_url))
        
    redirect_uri = current_app.config.get('GOOGLE_REDIRECT_URI') or url_for('auth.google_callback', _external=True)
    
    token_payload = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    user_info = None
    try:
        import requests
        token_res = requests.post('https://oauth2.googleapis.com/token', data=token_payload, timeout=12)
        if token_res.status_code == 200:
            tokens = token_res.json()
            access_token = tokens.get('access_token')
            if access_token:
                profile_res = requests.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo',
                    headers={'Authorization': f'Bearer {access_token}'},
                    timeout=12
                )
                if profile_res.status_code == 200:
                    user_info = profile_res.json()
        else:
            current_app.logger.warning(f"Google token exchange failed ({token_res.status_code}): {token_res.text}")
    except Exception as exc:
        current_app.logger.warning(f"Google OAuth requests exception: {exc}")
        
    # Standard library urllib fallback
    if not user_info:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                'https://oauth2.googleapis.com/token',
                data=urlencode(token_payload).encode('utf-8'),
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                tokens = json.loads(resp.read().decode('utf-8'))
                access_token = tokens.get('access_token')
                if access_token:
                    p_req = urllib.request.Request(
                        'https://www.googleapis.com/oauth2/v3/userinfo',
                        headers={'Authorization': f'Bearer {access_token}'}
                    )
                    with urllib.request.urlopen(p_req, timeout=12) as p_resp:
                        user_info = json.loads(p_resp.read().decode('utf-8'))
        except Exception as urllib_exc:
            current_app.logger.error(f"Google OAuth urllib fallback exception: {urllib_exc}")
            
    if not user_info or not user_info.get('email'):
        flash("Could not retrieve verified profile from Google. Please sign in with your email and password.", "danger")
        return redirect(url_for('auth.login', next=next_url))
        
    email = user_info.get('email').strip().lower()
    google_id = str(user_info.get('sub', ''))
    given_name = user_info.get('given_name') or user_info.get('name') or 'Learner'
    family_name = user_info.get('family_name') or ''
    
    user = User.query.filter((User.google_id == google_id) | (User.email == email)).first()
    if not user:
        user = User(
            email=email,
            first_name=given_name[:100],
            last_name=family_name[:100] if family_name else '.',
            google_id=google_id,
            role='learner',
            is_verified=True,
            is_active=True
        )
        db.session.add(user)
        db.session.commit()
        log_audit_event(user.id, "GOOGLE_SIGNUP", "User", user.id, f"Google account registered: {email}")
    else:
        if not user.google_id:
            user.google_id = google_id
        user.is_verified = True
        db.session.commit()
        log_audit_event(user.id, "GOOGLE_LOGIN", "User", user.id, f"Google account logged in: {email}")
        
    session.clear()
    session['user_id'] = user.id
    session['user_name'] = user.full_name
    session['user_role'] = user.role
    session.permanent = True
    
    flash(f"Welcome back, {user.first_name}! Signed in successfully via Google.", "success")
    
    if not user.has_complete_profile:
        flash("Please complete your profile details (age and gender) to proceed with your course certification.", "info")
        return redirect(url_for('auth.complete_profile', next=next_url))
        
    return redirect(next_url)


@auth_bp.route('/complete-profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    user = get_current_user()
    next_url = get_safe_redirect_url(request.args.get('next'))
    
    if request.method == 'POST':
        user.first_name = request.form.get('first_name', user.first_name).strip()
        user.middle_name = request.form.get('middle_name', user.middle_name or '').strip()
        user.last_name = request.form.get('last_name', user.last_name).strip()
        age_str = request.form.get('age', '').strip()
        user.gender = request.form.get('gender', user.gender)
        
        try:
            user.age = int(age_str)
        except ValueError:
            flash("Please enter a valid age.", "danger")
            return render_template('elearning/complete_profile.html', user=user, next=next_url)
            
        db.session.commit()
        session['user_name'] = user.full_name
        flash("Profile updated successfully.", "success")
        return redirect(next_url)
        
    return render_template('elearning/complete_profile.html', user=user, next=next_url)


@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(email_verification_token=token).first()
    if not user:
        flash("Invalid or expired email verification link.", "danger")
        return redirect(url_for('elearning.courses_list'))
        
    user.is_verified = True
    user.email_verification_token = None
    db.session.commit()
    log_audit_event(user.id, "EMAIL_VERIFIED", "User", user.id, "Email address validated successfully")
    
    # Establish authenticated session post validation
    session.clear()
    session['user_id'] = user.id
    session['user_name'] = user.full_name
    session['user_role'] = user.role
    session.permanent = True
    
    flash("Your email ID has been successfully validated! You are now logged in and have full access to start learning.", "success")
    return redirect(url_for('elearning.courses_list'))


@auth_bp.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    user = get_current_user()
    target_user = None

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if email:
            target_user = User.query.filter_by(email=email).first()
    if not target_user:
        target_user = user

    if not target_user:
        flash("Please log in or specify your registered email address to receive a verification link.", "info")
        return redirect(url_for('auth.login'))

    if target_user.is_verified:
        flash("Your account email address is already verified.", "info")
        return redirect(url_for('elearning.courses_list'))

    if not target_user.email_verification_token:
        target_user.email_verification_token = uuid.uuid4().hex
        db.session.commit()

    verify_link = url_for('auth.verify_email', token=target_user.email_verification_token, _external=True)
    email_body = f"""
    <h2>Welcome to Ytal Tech E-Learning, {target_user.first_name}!</h2>
    <p>Thank you for registering on the Ytal Tech Solutions & Services LLP e-learning platform.</p>
    <p>Please click the link below to verify your email address and activate full course access:</p>
    <p><a href="{verify_link}" style="display:inline-block;padding:10px 20px;background:#00AEEF;color:#fff;text-decoration:none;border-radius:4px;">Verify My Email Address</a></p>
    <p>Or copy this link to your browser: {verify_link}</p>
    <br>
    <p>Best regards,<br>Ytal Tech Academic & Clinical Training Team</p>
    """
    sent = send_transactional_email(target_user.email, "Verify your Ytal Tech E-Learning Account", email_body)
    if sent:
        flash(f"A fresh verification email has been dispatched to {target_user.email}. Please check your inbox and spam/junk folder.", "success")
    else:
        flash("Could not dispatch verification email at this moment. Please try again shortly.", "danger")
    return redirect(url_for('elearning.courses_list'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        client_ip = request.remote_addr or '127.0.0.1'
        if not check_rate_limit(f"pwd_reset_{client_ip}", max_attempts=4, window_seconds=60):
            flash("Too many requests. Please wait a minute before requesting another password reset.", "danger")
            return render_template('elearning/forgot_password.html')
            
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        
        if user:
            reset_token = uuid.uuid4().hex
            user.reset_password_token = reset_token
            user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()
            
            reset_url = url_for('auth.reset_password', token=reset_token, _external=True)
            email_body = f"""
            <h3>Password Reset Request - Ytal Tech E-Learning</h3>
            <p>Dear {user.first_name},</p>
            <p>We received a request to reset your password. Click the link below to set a new password:</p>
            <p><a href="{reset_url}" style="display:inline-block;padding:10px 20px;background:#EC008C;color:#fff;text-decoration:none;border-radius:4px;">Reset My Password</a></p>
            <p>This single-use link is valid for 1 hour. If you did not make this request, you can safely ignore this email.</p>
            """
            send_transactional_email(user.email, "Reset your Ytal Tech Password", email_body)
            log_audit_event(user.id, "PASSWORD_RESET_REQUESTED", "User", user.id, "Reset token generated")
            
        # Always display confirmation message to prevent user enumeration
        flash("If an account exists with that email address, password reset instructions have been sent.", "info")
        return redirect(url_for('auth.login'))
        
    return render_template('elearning/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_password_token=token).first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        flash("This password reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for('auth.forgot_password'))
        
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template('elearning/reset_password.html', token=token)
            
        is_valid, errors = validate_password_complexity(password)
        if not is_valid:
            for err in errors:
                flash(err, "danger")
            return render_template('elearning/reset_password.html', token=token)
            
        user.set_password(password)
        user.reset_password_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        log_audit_event(user.id, "PASSWORD_RESET_COMPLETED", "User", user.id, "Password reset successfully")
        flash("Your password has been reset successfully! Please log in with your new password.", "success")
        return redirect(url_for('auth.login'))
        
    return render_template('elearning/reset_password.html', token=token)


@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        log_audit_event(user_id, "USER_LOGOUT", "User", user_id, "User logged out")
    session.clear()
    flash("You have been logged out securely.", "info")
    return redirect(url_for('elearning.courses_list'))


@auth_bp.route('/api/password-strength', methods=['POST'])
def check_password_strength():
    """Real-time password strength endpoint."""
    data = request.get_json() or {}
    password = data.get('password', '')
    score, label = calculate_password_strength(password)
    is_valid, errors = validate_password_complexity(password)
    return jsonify({
        'score': score,
        'label': label,
        'is_valid': is_valid,
        'errors': errors
    })
