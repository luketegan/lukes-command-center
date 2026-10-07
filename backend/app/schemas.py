import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 254 or not EMAIL_PATTERN.match(normalized):
        raise ValueError("Enter a valid email address")
    return normalized


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: str) -> str:
        return validate_email(value)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def email_is_valid(cls, value: Optional[str]) -> Optional[str]:
        return validate_email(value) if value is not None else None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TrackerRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=100)
    started_at: str
    completed_at: str
    status: Literal["complete", "partial", "failed"]
    topic: str = Field(min_length=1, max_length=1000)
    k: int = Field(ge=3, le=10)
    model: str
    new_items: list[dict[str, Any]] = Field(default_factory=list)
    still_items: list[dict[str, Any]] = Field(default_factory=list)
    dropped_items: list[dict[str, Any]] = Field(default_factory=list)
    articles: list[dict[str, Any]] = Field(default_factory=list)
    budget_usage: dict[str, Any] = Field(default_factory=dict)
    report_markdown: str
    stop_reason: Optional[str] = None


class TrackerStatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str
    seen_urls: list[str] = Field(default_factory=list)
    developments: list[dict[str, Any]] = Field(default_factory=list)
    last_top_k: list[str] = Field(default_factory=list)
    updated_at: str


class TrackerSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run: TrackerRunPayload
    state: TrackerStatePayload
