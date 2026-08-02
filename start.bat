@echo off
setlocal

rem Every-day use: start the app server in the foreground (so you can see
rem verification/reset links printed to this terminal - there's no real
rem email sending locally, see app/email/sender.py) and open the browser
rem once the server is actually responding.

call venv\Scripts\activate.bat

start "" /b venv\Scripts\python.exe scripts\open_browser_when_ready.py

rem Excluded so ordinary database writes (every essay submission, WAL
rem checkpoints, etc.) don't register as source changes and trigger an
rem unnecessary worker restart - app.db lives inside the watched project
rem directory and WatchFiles has no notion of .gitignore. Uses --flag=value
rem (one token) rather than "--flag value" - Python 3.13+'s venv launcher on
rem Windows glob-expands a bare argument containing "*" against real files
rem in the cwd (app.db-wal/app.db-shm exist), which silently turns the
rem pattern into literal filenames and breaks uvicorn's own arg parsing.
venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-exclude=app.db* --reload-exclude=*.db-wal --reload-exclude=*.db-shm
