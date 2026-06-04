# Outlook Management

Local Outlook mailbox manager MVP.

## Stack

- Frontend: Vue 3 + Vite
- Backend: Python FastAPI
- Database: SQLite
- Mail provider: Microsoft Graph OAuth

## Backend

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Copy `.env.example` to `.env` and fill Microsoft OAuth values before using Graph login.

## Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open the Vite URL shown in the terminal.

Run frontend end-to-end tests:

```powershell
cd frontend
npm.cmd run test:e2e
```

## Import Format

```text
email@example.com----password----totp-secret
email2@example.com----password----totp-secret
```

Passwords and TOTP secrets are stored as plain text in SQLite for this MVP, per current project decision.
