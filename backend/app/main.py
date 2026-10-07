import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.errors import DuplicateKeyError

from .config import FRONTEND_ORIGINS
from .database import initialize_database, tracker_runs, tracker_states, users
from .schemas import LoginRequest, RegisterRequest, TokenResponse, TrackerSaveRequest, UserResponse, UserUpdateRequest
from .security import create_access_token, decode_access_token, hash_password, verify_password

bearer_scheme = HTTPBearer(auto_error=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_user(user: dict) -> dict:
    return {
        "id": user["_id"],
        "username": user["username"],
        "email": user["email"],
        "created_at": user["created_at"],
    }


def seed_grader_account() -> None:
    if users.find_one({"username_key": "nyugrader"}, {"_id": 1}):
        return
    timestamp = now_iso()
    try:
        users.insert_one({
            "_id": str(uuid.uuid4()),
            "username": "NYUgrader",
            "username_key": "nyugrader",
            "email": "nyugrader@example.com",
            "email_key": "nyugrader@example.com",
            "password_hash": hash_password("Courant2026!"),
            "created_at": timestamp,
            "updated_at": timestamp,
        })
    except DuplicateKeyError:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    seed_grader_account()
    yield


app = FastAPI(title="Luke's Command Center API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    user = users.find_one({"_id": user_id})
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_owner(user_id: str, current_user: dict) -> None:
    if user_id != current_user["_id"]:
        raise HTTPException(status_code=403, detail="You cannot access another account")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest) -> dict:
    timestamp = now_iso()
    user = {
        "_id": str(uuid.uuid4()),
        "username": payload.username,
        "username_key": payload.username.lower(),
        "email": payload.email,
        "email_key": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Username or email is already in use") from None
    return public_user(user)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> dict:
    user = users.find_one({"username_key": payload.username.strip().lower()})
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "access_token": create_access_token(user["_id"]),
        "token_type": "bearer",
        "user": public_user(user),
    }


@app.get("/api/auth/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)) -> dict:
    return public_user(current_user)


@app.get("/api/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    require_owner(user_id, current_user)
    return public_user(current_user)


@app.patch("/api/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    require_owner(user_id, current_user)
    if payload.email is None and payload.password is None:
        raise HTTPException(status_code=400, detail="Provide an email or password to update")
    changes = {"updated_at": now_iso()}
    if payload.email is not None:
        changes.update({"email": payload.email, "email_key": payload.email.lower()})
    if payload.password is not None:
        changes["password_hash"] = hash_password(payload.password)
    try:
        users.update_one({"_id": user_id}, {"$set": changes})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Email is already in use") from None
    return public_user(users.find_one({"_id": user_id}))


@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    require_owner(user_id, current_user)
    users.delete_one({"_id": user_id})
    tracker_states.delete_many({"user_id": user_id})
    tracker_runs.delete_many({"user_id": user_id})
    return {"message": "Account deleted"}


def clean_mongo(document: dict | None) -> dict | None:
    if document is None:
        return None
    result = dict(document)
    result.pop("_id", None)
    return result


@app.get("/api/tracker/state")
def get_tracker_state(current_user: dict = Depends(get_current_user)) -> dict:
    state = tracker_states.find_one({"user_id": current_user["_id"]})
    if state is None:
        return {
            "topic": "",
            "seen_urls": [],
            "developments": [],
            "last_top_k": [],
            "updated_at": None,
        }
    return clean_mongo(state)


@app.post("/api/tracker/runs", status_code=201)
def save_tracker_run(
    payload: TrackerSaveRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    user_id = current_user["_id"]
    run = payload.run.model_dump()
    run["_id"] = run.pop("run_id")
    run["user_id"] = user_id
    state = payload.state.model_dump()
    state["user_id"] = user_id
    try:
        tracker_runs.insert_one(run)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="This tracker run already exists") from None
    tracker_states.update_one({"user_id": user_id}, {"$set": state}, upsert=True)
    return {"message": "Tracker run saved", "run_id": run["_id"]}


@app.get("/api/tracker/reports/latest")
def latest_tracker_report(current_user: dict = Depends(get_current_user)) -> dict:
    run = tracker_runs.find_one(
        {"user_id": current_user["_id"]},
        sort=[("completed_at", -1)],
    )
    if run is None:
        raise HTTPException(status_code=404, detail="No tracker reports yet")
    result = clean_mongo(run)
    result["run_id"] = run["_id"]
    result.pop("user_id", None)
    return result


@app.get("/api/tracker/runs")
def list_tracker_runs(current_user: dict = Depends(get_current_user)) -> list[dict]:
    results = []
    for run in tracker_runs.find({"user_id": current_user["_id"]}).sort("completed_at", -1):
        item = clean_mongo(run)
        item["run_id"] = run["_id"]
        item.pop("user_id", None)
        results.append(item)
    return results


@app.get("/api/tracker/runs/{run_id}")
def get_tracker_run(run_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    run = tracker_runs.find_one({"_id": run_id, "user_id": current_user["_id"]})
    if run is None:
        raise HTTPException(status_code=404, detail="Tracker run not found")
    result = clean_mongo(run)
    result["run_id"] = run["_id"]
    result.pop("user_id", None)
    return result


@app.delete("/api/tracker/state")
def reset_tracker_state(current_user: dict = Depends(get_current_user)) -> dict:
    user_id = current_user["_id"]
    deleted_runs = tracker_runs.delete_many({"user_id": user_id}).deleted_count
    tracker_states.delete_many({"user_id": user_id})
    return {"message": "Tracker state reset", "deleted_runs": deleted_runs}
