# Luke's Command Center — Festival Connectivity Tracker

Luke's Command Center is a local React and FastAPI application backed by MongoDB Atlas. Assignment 1B adds a hand-written research agent that tracks technologies and festival pilots that help friends communicate or find each other when cellular networks are congested or unavailable.

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

Open `tracker/.env` and replace only the two API-key placeholders. This file is ignored by Git.

```dotenv
GROQ_API_KEY=your_real_groq_key
TAVILY_API_KEY=your_real_tavily_key
TRACKER_USERNAME=NYUgrader
TRACKER_PASSWORD=Courant2026!
BACKEND_URL=http://127.0.0.1:8000
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

Delete or archive local `reports/run*.md` and `traces/run*.jsonl` yourself only if you intentionally want to start numbering over.

## 8. Tests and builds

With the backend running:

```bash
cd backend
source .venv/bin/activate
python verify_api.py
```

From the project root with the tracker environment active:

```bash
pytest -q
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Agent design and safety

- The loop in `tracker/runtime.py` is hand-written and invokes the model and three tools directly.
- `tracker/config.yaml` defines the topic, K=5, model, instructions, tools, budgets, allowed schemes, and allowed hosts.
- Runtime budgets cap steps, searches, fetches, model calls, and total tokens. Exhaustion writes a partial report.
- Temporary failures retry with capped exponential backoff. Invalid credentials, billing/payment failures, and daily-quota errors are terminal.
- The fetcher allows HTTPS only, uses a host allowlist, rejects credentials/nonstandard ports and non-public DNS results, revalidates redirects, and enforces time/size limits.
- Retrieved pages are untrusted evidence. They cannot change instructions, tools, or budgets.
- A development is accepted only when its URL was fetched and its quoted evidence appears in the extracted page text.
- The frontend renders data as React text nodes. It never injects retrieved HTML.
- Every model/tool call is written to JSONL with step, arguments (excluding secrets), status, latency, and tokens/credits.

## Authentication rules retained from Assignment 1

- Password hashes are never returned.
- Missing, bad, and expired tokens return 401.
- Cross-account GET, PATCH, and DELETE consistently return 403.
- Tracker endpoints also require the logged-in bearer token and scope every database query to that user.

## Submission checklist

- [ ] `backend/.env` contains only the assignment's working throwaway MongoDB connection.
- [ ] `tracker/.env` is not tracked.
- [ ] `reports/run1.md` and `reports/run2.md` exist and are at least one day apart.
- [ ] `traces/run1.jsonl` and `traces/run2.jsonl` exist.
- [ ] `AGENT.md` has no bracketed placeholders.
- [ ] `pytest -q` passes.
- [ ] `npm run build` passes.
- [ ] Clean-clone instructions were tested.
- [ ] No Groq or Tavily key appears in Git history.
