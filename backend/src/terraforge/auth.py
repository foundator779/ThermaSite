from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.cloud import firestore
from pydantic import BaseModel, Field, model_validator

from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings

SESSION_DAYS = 30
DEMO_EMAIL = "judge@thermasite.demo"


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserAccount(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    email: str
    name: str
    password_salt: str | None = None
    password_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    is_demo: bool = False


class PublicUser(BaseModel):
    id: UUID
    email: str
    name: str
    is_demo: bool

    @classmethod
    def from_account(cls, account: UserAccount):
        return cls.model_validate(account.model_dump())


class AuthSession(BaseModel):
    token_hash: str
    user_id: UUID
    expires_at: datetime


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def valid_email(self):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.email):
            raise ValueError("Enter a valid email address")
        return self


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: PublicUser


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


class AuthStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._users: dict[UUID, UserAccount] = {}
        self._email_index: dict[str, UUID] = {}
        self._sessions: dict[str, AuthSession] = {}
        self._lock = asyncio.Lock()
        self._path = (settings.terraforge_data_dir / "thermasite-auth.json").resolve()
        self._firestore = (
            firestore.AsyncClient(
                project=settings.gcp_project_id, database=settings.firestore_database
            )
            if settings.cloud_enabled
            else None
        )

    async def initialize(self) -> None:
        if self._firestore:
            async for snapshot in self._firestore.collection("thermasite_users").stream():
                account = UserAccount.model_validate(snapshot.to_dict())
                self._index(account)
        elif self._path.exists():
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            for item in payload.get("users", []):
                self._index(UserAccount.model_validate(item))
            for item in payload.get("sessions", []):
                session = AuthSession.model_validate(item)
                if session.expires_at > utc_now():
                    self._sessions[session.token_hash] = session
        if DEMO_EMAIL not in self._email_index:
            demo = UserAccount(
                email=DEMO_EMAIL,
                name="Hackathon Judge",
                is_demo=True,
            )
            self._index(demo)
            await self._save_user(demo)
            await self._persist_local()

    def _index(self, account: UserAccount) -> None:
        self._users[account.id] = account
        self._email_index[account.email.lower()] = account.id

    async def register(self, payload: RegisterRequest) -> UserAccount:
        async with self._lock:
            email = payload.email.strip().lower()
            if email in self._email_index:
                raise ValueError("An account with this email already exists")
            salt = secrets.token_bytes(16)
            account = UserAccount(
                email=email,
                name=payload.name.strip(),
                password_salt=salt.hex(),
                password_hash=_password_hash(payload.password, salt),
            )
            self._index(account)
            await self._save_user(account)
            await self._persist_local()
            return account

    async def verify(self, email: str, password: str) -> UserAccount | None:
        user_id = self._email_index.get(email.strip().lower())
        account = self._users.get(user_id) if user_id else None
        if not account or not account.password_hash or not account.password_salt:
            return None
        calculated = _password_hash(password, bytes.fromhex(account.password_salt))
        return account if hmac.compare_digest(calculated, account.password_hash) else None

    async def demo_user(self) -> UserAccount:
        return self._users[self._email_index[DEMO_EMAIL]]

    async def create_session(self, account: UserAccount) -> tuple[str, AuthSession]:
        token = secrets.token_urlsafe(32)
        session = AuthSession(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_id=account.id,
            expires_at=utc_now() + timedelta(days=SESSION_DAYS),
        )
        self._sessions[session.token_hash] = session
        if self._firestore:
            await (
                self._firestore.collection("thermasite_sessions")
                .document(session.token_hash)
                .set(session.model_dump(mode="json"))
            )
        await self._persist_local()
        return token, session

    async def authenticate(self, token: str) -> UserAccount | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        session = self._sessions.get(token_hash)
        if session is None and self._firestore:
            snapshot = (
                await self._firestore.collection("thermasite_sessions").document(token_hash).get()
            )
            if snapshot.exists:
                session = AuthSession.model_validate(snapshot.to_dict())
                self._sessions[token_hash] = session
        if session is None or session.expires_at <= utc_now():
            if session:
                await self.revoke(token)
            return None
        account = self._users.get(session.user_id)
        if account is None and self._firestore:
            snapshot = (
                await self._firestore.collection("thermasite_users")
                .document(str(session.user_id))
                .get()
            )
            if snapshot.exists:
                account = UserAccount.model_validate(snapshot.to_dict())
                self._index(account)
        return account

    async def revoke(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        self._sessions.pop(token_hash, None)
        if self._firestore:
            await self._firestore.collection("thermasite_sessions").document(token_hash).delete()
        await self._persist_local()

    async def _save_user(self, account: UserAccount) -> None:
        if self._firestore:
            await (
                self._firestore.collection("thermasite_users")
                .document(str(account.id))
                .set(account.model_dump(mode="json"))
            )

    async def _persist_local(self) -> None:
        if self._firestore:
            return
        await atomic_write_text(
            self._path,
            json.dumps(
                {
                    "users": [item.model_dump(mode="json") for item in self._users.values()],
                    "sessions": [item.model_dump(mode="json") for item in self._sessions.values()],
                },
                indent=2,
                default=str,
            ),
        )


bearer = HTTPBearer(auto_error=False)


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    thermasite_session: Annotated[str | None, Cookie()] = None,
) -> PublicUser:
    token = credentials.credentials if credentials else thermasite_session
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to access this screening")
    account = await request.app.state.auth.authenticate(token)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The session is invalid or expired")
    return PublicUser.from_account(account)


CurrentUser = Annotated[PublicUser, Depends(require_user)]


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        "thermasite_session",
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.terraforge_env == "production",
        samesite="lax",
        path="/",
    )


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, response: Response, request: Request):
    try:
        account = await request.app.state.auth.register(payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    token, _ = await request.app.state.auth.create_session(account)
    _set_session_cookie(response, token, request.app.state.settings)
    return AuthResponse(token=token, user=PublicUser.from_account(account))


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, response: Response, request: Request):
    account = await request.app.state.auth.verify(payload.email, payload.password)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")
    token, _ = await request.app.state.auth.create_session(account)
    _set_session_cookie(response, token, request.app.state.settings)
    return AuthResponse(token=token, user=PublicUser.from_account(account))


@router.post("/demo", response_model=AuthResponse)
async def demo(response: Response, request: Request):
    account = await request.app.state.auth.demo_user()
    token, _ = await request.app.state.auth.create_session(account)
    _set_session_cookie(response, token, request.app.state.settings)
    return AuthResponse(token=token, user=PublicUser.from_account(account))


@router.get("/me", response_model=PublicUser)
async def me(user: CurrentUser):
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    thermasite_session: Annotated[str | None, Cookie()] = None,
):
    token = credentials.credentials if credentials else thermasite_session
    if token:
        await request.app.state.auth.revoke(token)
    response.delete_cookie("thermasite_session", path="/")
