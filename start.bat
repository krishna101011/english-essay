@echo off
setlocal

rem Every-day use: start the app server in the foreground (so you can see
rem verification/reset links printed to this terminal - there's no real
rem email sending locally, see app/email/sender.py) and open the browser
rem once the server is actually responding.

call venv\Scripts\activate.bat

start "" /b venv\Scripts\python.exe scripts\open_browser_when_ready.py

venv\Scripts\python.exe -m uvicorn app.main:app --reload
