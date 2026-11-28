import os
from flask import Flask, render_template, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from elearning import init_elearning
from elearning.models import db
from elearning.seed_data import seed_database

app = Flask(__name__)
app.config.from_object(Config)

# Support reverse proxy headers (Nginx, AWS ALB, Cloudflare) for real IP and HTTPS detection
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Initialize E-Learning module (database, blueprints, context processors)
init_elearning(app)

# Initialize database migration engine (Flask-Migrate / Alembic) if installed
try:
    from flask_migrate import Migrate
    migrate = Migrate(app, db)
except ImportError:
    migrate = None

# Ensure storage directories exist (supports external STORAGE_ROOT volume mounts)
for folder in [
    app.config.get('UPLOAD_FOLDER'),
    app.config.get('RECEIPTS_UPLOAD_FOLDER'),
    app.config.get('SLIDES_UPLOAD_FOLDER'),
    app.config.get('CERTIFICATES_FOLDER'),
    app.config.get('INVOICES_FOLDER')
]:
    if folder:
        os.makedirs(folder, exist_ok=True)

# Ensure database tables are created and initial seed data is populated
# Protected by concurrency guard to prevent race conditions during multi-worker WSGI boot
init_db_startup = os.environ.get('INIT_DB_ON_STARTUP', 'true').lower() in ['true', '1', 'yes']
if init_db_startup:
    with app.app_context():
        try:
            db.create_all()
            from elearning.models import Course, Slide
            if Course.query.count() == 0 or Slide.query.count() < 100:
                seed_database()
        except Exception as e:
            db.session.rollback()
            app.logger.warning(f"[DB Init Notice] Skipped or handled concurrent startup init: {e}")

@app.route('/')
def home():
    # Renders the main single-page website with E-Learning links
    return render_template('index.html')

# Existing Healthcare API endpoint (EMR integration)
@app.route('/api/healthdesk/status', methods=['GET'])
def healthdesk_status():
    return {"status": "operational", "service": "HealthDesk API"}

# Custom production error handlers (information disclosure prevention)
@app.errorhandler(404)
def handle_not_found(e):
    return render_template('elearning/404.html'), 404

@app.errorhandler(500)
def handle_server_error(e):
    db.session.rollback()
    return render_template('elearning/500.html'), 500

if __name__ == "__main__":
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 'yes']
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
