import os
from flask import Flask, render_template
from config import Config
from elearning import init_elearning
from elearning.models import db
from elearning.seed_data import seed_database

app = Flask(__name__)
app.config.from_object(Config)

# Initialize E-Learning module (database, blueprints, context processors)
init_elearning(app)

# Ensure database tables are created and initial seed data is populated
with app.app_context():
    db.create_all()
    seed_database()
    from elearning.models import Slide
    if Slide.query.count() < 100:
        from elearning.seed_from_pptx import import_pptx_presentations
        import_pptx_presentations()

@app.route('/')
def home():
    # Renders the main single-page website with E-Learning links
    return render_template('index.html')

# Existing Healthcare API endpoint (EMR integration)
@app.route('/api/healthdesk/status', methods=['GET'])
def healthdesk_status():
    return {"status": "operational", "service": "HealthDesk API"}

if __name__ == "__main__":
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 'yes']
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
