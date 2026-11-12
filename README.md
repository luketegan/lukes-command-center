# Luke's Command Center — Festival Connectivity Tracker

Luke's Command Center is a local React and FastAPI application backed by MongoDB Atlas. Assignment 1B added a hand-written research agent that tracks technologies and festival pilots that help friends communicate or find each other when cellular networks are congested or unavailable. **Assignment 2 (Agentic Orchestration)** turns that agent into a team of three HTTP services: a researcher, a verifier deployed on Render, and a plain-code orchestrator. Its setup is in the [Agentic Orchestration](#agentic-orchestration-assignment-researcher-verifier-orchestrator) section, and its design write-up is `ORCHESTRATION.md`.

## Prerequisites

- Python 3.11+
- Node.js 20+ and npm 10+
- Internet access
- A MongoDB Atlas throwaway database
- A Groq API key
- A Tavily Search API key

The backend and frontend run locally. MongoDB Atlas, Groq, and Tavily are external services.

## 1. Environment files

`backend/.env` must contain the working throwaway MongoDB connection string required by the course. Do not put Groq or Tavily keys here.

```dotenv
MONGODB_URI=mongodb+srv://USERNAME:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=lukes_command_center
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ACCESS_TOKEN_MINUTES=60
```

Create the tracker environment file:

```bash
cp tracker/.env.example tracker/.env
```

Open `tracker/.env` and replace the two API-key placeholders. Assignment 2 also needs `RESEARCHER_TOKEN` in this file (see the Agentic Orchestration section). This file is ignored by Git.

```dotenv
GROQ_API_KEY=your_real_groq_key
TAVILY_API_KEY=your_real_tavily_key
TRACKER_USERNAME=NYUgrader
TRACKER_PASSWORD=Courant2026!
BACKEND_URL=http://127.0.0.1:8000
RESEARCHER_TOKEN=a_long_random_value
```

## 2. Start the backend — Terminal 1

From the project root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-exclude ".venv/*"
```

Windows PowerShell activation: `.venv\Scripts\Activate.ps1`

Check http://127.0.0.1:8000/healthz. The backend must remain running before the tracker starts.

## 3. Start the frontend — Terminal 2

From the project root:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and log in with username `NYUgrader` and password `Courant2026!`.

## 4. Install and run the tracker — Terminal 3

From the project root:

```bash
python3 -m venv .tracker-venv
source .tracker-venv/bin/activate
python -m pip install --upgrade pip
pip install -r tracker/requirements.txt
python -m tracker run
```

Windows PowerShell activation: `.tracker-venv\Scripts\Activate.ps1`

The first run creates `reports/run1.md` and `traces/run1.jsonl`, then saves the run and memory through the authenticated FastAPI backend. Refresh the Festival Tracker screen in the browser.

## 5. Test each tool without the model

From the project root with `.tracker-venv` active:

```bash
python -m tracker.tools search_web "festival offline friend finding mesh technology"
python -m tracker.tools fetch_article "https://www.theverge.com/"
python -m tracker.tools finish '{"developments":[]}'
```

The article URL must use HTTPS and an allowed host from `tracker/config.yaml`.

## 6. Required second run

Wait at least 24 hours after the first run. Keep run 1 files. Then, with the backend running:

```bash
source .tracker-venv/bin/activate
python -m tracker run
```

This creates `reports/run2.md` and `traces/run2.jsonl`. It loads memory through the backend, skips previously fetched URLs, merges duplicate developments, and labels results New, Still tracking, or Dropped from the Top K.

## 7. Reset tracker state

This permanently removes this user's saved tracker runs and memory from MongoDB. It does not delete local report/trace files.

```bash
source .tracker-venv/bin/activate
python -m tracker reset
```

Run numbers are never reused while report or trace files exist, so a reset cannot overwrite earlier reports. To start again at run 1, delete or archive the local `reports/run*.md` and `traces/run*.jsonl` files too.

## 8. Tests and builds

With the backend running:

```bash
cd backend
source .venv/bin/activate
python verify_api.py
```

From the project root with the tracker environment active:

```bash
python -m pytest -q
```

These tests make no network calls and use no API credits.

Frontend production build:

```bash
cd frontend
npm run build
```

## Agentic Orchestration assignment: researcher, verifier, orchestrator

Three separate processes talk only over HTTP:

| Service | Runs where | Port | Started with |
| --- | --- | --- | --- |
| Researcher (the A2 tracker as a service) | your machine | 8101 | `python -m services.researcher` |
| Verifier (checks each claim against its page) | Render free tier | Render's `$PORT` | `python -m services.verifier` |
| Orchestrator (plain code, owns all saved state) | your machine | none | `python -m orchestrator run` |

Contract details are in `shared/contract.py`; design notes are in `ORCHESTRATION.md`.

The deployed verifier is at `https://festival-verifier.onrender.com` (`/healthz` needs no token; `/verify` needs `VERIFIER_TOKEN`, which is kept in Render's environment settings, not in this repo). To run everything yourself, the simplest path is to run the verifier locally (option A below).

Before starting: the backend (section 2) must be running, and the tracker environment from section 4 must be installed (`.tracker-venv` with `tracker/requirements.txt`). No other packages are needed: the services use Python's standard HTTP server.

### 1. Secrets

Make two different service tokens (run this twice):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

- `tracker/.env`: set `RESEARCHER_TOKEN=<first token>`.
- `cp orchestrator/.env.example orchestrator/.env`, then set `RESEARCHER_TOKEN` (same first token), `VERIFIER_TOKEN` (second token) and `VERIFIER_URL`.

### 2. Start the verifier (choose one)

**Option A, locally:** from the project root,

```bash
cp services/verifier/.env.example services/verifier/.env
```

Set `VERIFIER_TOKEN=<second token>` and `GROQ_API_KEY=<your Groq key>` in `services/verifier/.env`, and set `VERIFIER_URL=http://127.0.0.1:8102` in `orchestrator/.env`. Then, in a new terminal:

```bash
source .tracker-venv/bin/activate
python -m services.verifier
```

**Option B, on Render:** **New → Blueprint**, pick this repository, and Render reads `render.yaml`. Enter `VERIFIER_TOKEN` and `GROQ_API_KEY` when asked. Check that `https://<your-service>.onrender.com/healthz` returns `{"status":"ok"}`, and put that URL in `orchestrator/.env` as `VERIFIER_URL`. Free instances sleep after 15 idle minutes and take about 20 to 60 seconds to wake. The orchestrator pings `/healthz` at the start of each run so the verifier wakes while the researcher works.

### 3. Start the researcher

In a new terminal, from the project root:

```bash
source .tracker-venv/bin/activate
python -m services.researcher
```

It should print `researcher listening on 127.0.0.1:8101`.

### 4. Test and run

In another terminal, from the project root:

```bash
source .tracker-venv/bin/activate
python -m pytest -q
python -m orchestrator.selftest
python -m orchestrator run
```

- `pytest` makes no network calls and uses no API credits.
- `orchestrator.selftest` sends the assignment's "Test it yourself" requests to both running workers (401, 400, replay, 409, 503 while running, blocked internal URLs, tiny time budget). It uses a few model calls.
- Each `orchestrator run` writes `reports/orchestrated/runN.md` and all three logs to `traces/orchestrated/runN/` (`orchestrator.jsonl`, `researcher.jsonl`, `verifier.jsonl`), and saves the run through the A1 backend. Log in as `NYUgrader` and open **Festival Tracker** to see claim labels, evidence and run history.

### 5. Reset

`python -m tracker reset` (section 7) deletes the saved runs and state for the `NYUgrader` account. Local report and trace files are kept, and run numbers keep counting up.

## Agent design and safety

- Assignment 2's researcher (`tracker/research.py`) makes two model calls per run: one to plan up to three searches and one to write claims from the fetched pages. Code does the searching, ranking and fetching. `ORCHESTRATION.md` explains why.
- The Assignment 1B loop in `tracker/runtime.py` is hand-written and invokes the model and three tools directly.
- `tracker/config.yaml` defines the topic, K=5, model, instructions, tools, budgets, allowed schemes, and allowed hosts.
- Runtime budgets cap steps, searches, fetches, model calls, and total tokens. Exhaustion writes a partial report.
- Temporary failures, including per-minute 429s, retry with a capped number of attempts and wait as long as the service asks. Invalid credentials, payment failures, and daily limits are terminal.
- One unreadable article is logged as failed and the run continues. Malformed tool calls are returned to the model to correct.
- The fetcher allows HTTPS only, uses a host allowlist, rejects credentials/nonstandard ports and non-public DNS results, revalidates redirects, and enforces time/size limits.
- Retrieved pages are untrusted evidence. They cannot change instructions, tools, or budgets.
- A development is accepted only when its URL was fetched, its quoted evidence appears in the extracted page text, and the evidence or page title matches `relevance_terms` in `tracker/config.yaml`.
- The frontend renders data as React text nodes. It never injects retrieved HTML.
- Every model/tool call is written to JSONL with step, arguments (excluding secrets), status, latency, and tokens/credits.

## Authentication rules retained from Assignment 1

- Password hashes are never returned.
- Missing, bad, and expired tokens return 401.
- Cross-account GET, PATCH, and DELETE consistently return 403.
- Tracker endpoints also require the logged-in bearer token and scope every database query to that user.

## Submission contents

- Assignment 2: `orchestrator/`, `services/`, `shared/`, `render.yaml`, `ORCHESTRATION.md`, `reports/orchestrated/` and `traces/orchestrated/` (runs 1–4 partial, runs 5–6 complete).
- Assignment 1B: `tracker/`, `AGENT.md`, `reports/run*.md` and `traces/run*.jsonl`.
- Only `backend/.env` (the throwaway course database) and `frontend/.env` (the local API address) are committed. All model, search and service keys live in ignored `.env` files or in Render's environment settings.
