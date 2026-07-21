from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    # Renders the main single-page website
    return render_template('index.html')

# Placeholder for future Healthcare API endpoints (e.g., EMR integration)
@app.route('/api/healthdesk/status', methods=['GET'])
def healthdesk_status():
    return {"status": "operational", "service": "HealthDesk API"}

if __name__ == "__main__":
    app.run(port=5000)