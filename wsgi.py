"""
Ytal Tech Solutions & Services LLP - Production WSGI Application Entrypoint
--------------------------------------------------------------------------
Production-ready server launcher compatible with:
  - Linux: Gunicorn / uWSGI / Waitress
  - Windows: Waitress multi-threaded production WSGI server
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    _env_file = os.path.join(BASE_DIR, '.env')
    if os.path.exists(_env_file):
        try:
            with open(_env_file, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith('#') and '=' in _line:
                        _k, _v = _line.split('=', 1)
                        _k, _v = _k.strip(), _v.strip()
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v.strip('"').strip("'")
        except Exception:
            pass

from app import app

# Expose WSGI application callable
application = app

if __name__ == "__main__":
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    threads = int(os.environ.get('WSGI_THREADS', 6))

    try:
        from waitress import serve
        print(f"===========================================================")
        print(f"Starting Ytal Tech Production Server via Waitress WSGI")
        print(f"Host: http://{host}:{port} | Threads: {threads} | Debug: OFF")
        print(f"===========================================================")
        serve(app, host=host, port=port, threads=threads, channel_timeout=60)
    except ImportError:
        print("Waitress not found. Falling back to WSGI runner with debug=False...")
        app.run(host=host, port=port, debug=False)
