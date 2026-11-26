from flask import Blueprint, session
from elearning.models import db, User, Course, SystemSetting
from elearning.auth import auth_bp, get_current_user
from elearning.courses import courses_bp
from elearning.tests import tests_bp
from elearning.payments import payments_bp
from elearning.certificates import cert_bp
from elearning.admin import admin_bp

def init_elearning(app):
    """Initializes the database and registers all e-learning sub-blueprints with the main Flask app."""
    db.init_app(app)
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(cert_bp)
    app.register_blueprint(admin_bp)
    
    # Global context processors for templates
    @app.context_processor
    def inject_elearning_globals():
        current_user = get_current_user()
        return {
            'current_user': current_user,
            'is_logged_in': bool(current_user is not None),
            'system_bank_name': SystemSetting.get('bank_name', app.config.get('BANK_NAME')),
            'system_upi_id': SystemSetting.get('upi_id', app.config.get('UPI_ID')),
            'price_inr_base': app.config.get('PRICE_INR_BASE', 499.00),
            'price_inr_total': app.config.get('PRICE_INR_TOTAL', 588.82),
            'price_usd': app.config.get('PRICE_USD', 9.49)
        }
        
    # HTTP Security Headers (Defensive Hardening)
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # When served over HTTPS, enforce Strict-Transport-Security
        from flask import request
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response
