@echo off
REM ==============================================================================
REM Ytal Tech Solutions & Services LLP - Production Startup Script (Windows)
REM ==============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0\.."

echo ===========================================================
echo Starting Ytal Tech E-Learning Production WSGI Server (Windows)
echo Server Engine: Waitress Multi-Threaded WSGI
echo ===========================================================

REM Run WSGI application via Python Waitress
python wsgi.py

pause
