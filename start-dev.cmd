@echo off
set ROOT=%~dp0

start "Outlook Management API" cmd /k "cd /d %ROOT%backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "Outlook Management Web" cmd /k "cd /d %ROOT%frontend && npm.cmd run dev"

echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
