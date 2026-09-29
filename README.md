# Luke's Command Center - FNMS Assignment 1

Luke's Command Center is a local full-stack account foundation for future personal tools. It provides registration, login, a protected home screen, and account editing/deletion through a React frontend and FastAPI JSON API backed by MongoDB Atlas.

## Architecture and decisions

- **Frontend:** React + Vite, running locally on port 5173.
- **Backend:** FastAPI, running locally on port 8000.
- **Database:** MongoDB Atlas. User accounts map naturally to documents and remain available across backend restarts. Atlas adds a network dependency, but avoids requiring graders to install a database server.
- **Passwords:** Argon2id. The hash is stored only in MongoDB and is never returned by any endpoint.
- **Authentication:** Expiring JWT bearer tokens. The signing key is generated locally on first startup and is not committed.
- **Authorization:** Every cross-account GET, PATCH, or DELETE returns **403 Forbidden**. The token is valid, but it does not authorize access to the other account.
- **CORS:** Only the two local Vite origins are allowed.

## Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+
- Internet access for MongoDB Atlas

## Environment setup

Open `backend/.env` and replace the placeholder after `MONGODB_URI=` with the complete connection string for the throwaway Atlas database. Leave the other values unchanged. The submitted copy must contain the working throwaway connection string required by the assignment.

A working `backend/.env` for the throwaway MongoDB Atlas database is included as required by the assignment. No database configuration should be necessary before starting the backend.

The submitted environment contains:

```dotenv
MONGODB_URI=<working throwaway MongoDB Atlas connection string>
MONGODB_DATABASE=lukes_command_center
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ACCESS_TOKEN_MINUTES=60

The Atlas project must allow the grader's network. For this throwaway assignment database, add `0.0.0.0/0` to Atlas Network Access. Do not reuse its credentials elsewhere.

## Start the backend - Terminal 1

From the project root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-exclude ".venv/*"
```

The backend starts at http://127.0.0.1:8000. Check:

- http://127.0.0.1:8000/healthz
- http://127.0.0.1:8000/docs

On startup, the app pings Atlas, creates unique indexes, and creates the required grader account if it does not exist.

## Start the frontend - Terminal 2

From the project root:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Required grader account

- Username: `NYUgrader`
- Password: `Courant2026!`

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | No | Returns `{ "status": "ok" }` |
| POST | `/api/auth/register` | No | Create an account |
| POST | `/api/auth/login` | No | Return a bearer token |
| GET | `/api/auth/me` | Yes | Return the logged-in user |
| GET | `/api/users/{id}` | Yes | Read your own account |
| PATCH | `/api/users/{id}` | Yes | Change your email/password |
| DELETE | `/api/users/{id}` | Yes | Delete your account |

Protected requests use `Authorization: Bearer <token>`. Missing, malformed, invalid, and expired tokens return 401. Password hashes are removed by an explicit public-user serializer and response models.

## Automated verification

Keep the backend running. In Terminal 3:

```bash
cd backend
source .venv/bin/activate
python verify_api.py
```

The script checks every required endpoint, the token rules, password-field leakage, and consistent 403 responses for all three cross-account operations.

## Persistence and frontend build tests

1. Register through the frontend.
2. Stop the backend with `Ctrl+C`.
3. Restart it with the same `uvicorn` command.
4. Log in again. The account remains in Atlas.
5. In `frontend`, run `npm run build` and confirm it succeeds.