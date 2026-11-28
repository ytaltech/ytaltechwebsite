"""
Ytal Tech Solutions & Services LLP - Production WSGI Application Entrypoint
--------------------------------------------------------------------------
Production WSGI callable for Gunicorn:
  gunicorn wsgi:application
"""

from app import app

# Expose WSGI application callable for Gunicorn / systemd service
application = app

if __name__ == "__main__":
    app.run()
