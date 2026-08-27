from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from services.application_database import (
    DatabaseBase,
    initialize_application_database,
    resolve_database_url,
)


class UserModel(DatabaseBase):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    display_name = Column(String(120), nullable=False)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(16), nullable=False, default="user")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class UserSessionModel(DatabaseBase):
    __tablename__ = "user_sessions"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)


class UserApiKeyModel(DatabaseBase):
    __tablename__ = "user_api_keys"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    key_hash = Column(String(128), unique=True, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class UserRepository:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or resolve_database_url()
        self._ensure_sqlite_parent()
        self.engine = initialize_application_database(self.database_url)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _ensure_sqlite_parent(self) -> None:
        url = make_url(self.database_url)
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            return
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def create_user(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.Session() as session:
            model = UserModel(
                id=user_id,
                email=email,
                display_name=display_name,
                password_hash=password_hash,
                role="user",
                enabled=True,
                created_at=now,
            )
            session.add(model)
            session.commit()
            return self._user_dict(model)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.Session() as session:
            model = session.scalar(select(UserModel).where(UserModel.email == email))
            return self._user_dict(model) if model is not None else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self.Session() as session:
            model = session.get(UserModel, user_id)
            return self._user_dict(model) if model is not None else None

    def list_users(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(
                select(UserModel).order_by(UserModel.created_at.desc()).limit(max(1, min(limit, 500)))
            ).all()
            return [self._user_dict(row) for row in rows]

    def set_user_enabled(self, *, user_id: str, enabled: bool) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.get(UserModel, user_id)
            if row is None:
                return None
            row.enabled = enabled
            session.commit()
            return self._user_dict(row)

    def touch_last_login(self, user_id: str) -> None:
        with self.Session() as session:
            model = session.get(UserModel, user_id)
            if model is None:
                return
            model.last_login_at = _utc_now()
            session.commit()

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        with self.Session() as session:
            session.add(UserSessionModel(
                id=session_id,
                user_id=user_id,
                token_hash=token_hash,
                created_at=_utc_now(),
                expires_at=expires_at,
            ))
            session.commit()

    def get_session_identity(self, token_hash: str) -> dict[str, Any] | None:
        now = _utc_now()
        with self.Session() as session:
            row = session.scalar(
                select(UserSessionModel).where(
                    UserSessionModel.token_hash == token_hash,
                    UserSessionModel.revoked_at.is_(None),
                )
            )
            if row is None or (_as_utc(row.expires_at) or now) <= now:
                return None
            user = session.get(UserModel, row.user_id)
            if user is None or not bool(user.enabled):
                return None
            row.last_seen_at = now
            session.commit()
            return self._user_dict(user)

    def revoke_session(self, token_hash: str) -> bool:
        with self.Session() as session:
            row = session.scalar(
                select(UserSessionModel).where(UserSessionModel.token_hash == token_hash)
            )
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = _utc_now()
            session.commit()
            return True

    def create_api_key(
        self,
        *,
        key_id: str,
        user_id: str,
        name: str,
        key_hash: str,
    ) -> dict[str, Any]:
        with self.Session() as session:
            model = UserApiKeyModel(
                id=key_id,
                user_id=user_id,
                name=name,
                key_hash=key_hash,
                enabled=True,
                created_at=_utc_now(),
            )
            session.add(model)
            session.commit()
            return self._api_key_dict(model)

    def list_api_keys(self, user_id: str) -> list[dict[str, Any]]:
        with self.Session() as session:
            rows = session.scalars(
                select(UserApiKeyModel)
                .where(UserApiKeyModel.user_id == user_id)
                .order_by(UserApiKeyModel.created_at.desc())
            ).all()
            return [self._api_key_dict(row) for row in rows]

    def revoke_api_key(self, *, user_id: str, key_id: str) -> bool:
        with self.Session() as session:
            row = session.scalar(
                select(UserApiKeyModel).where(
                    UserApiKeyModel.id == key_id,
                    UserApiKeyModel.user_id == user_id,
                )
            )
            if row is None or not bool(row.enabled):
                return False
            row.enabled = False
            session.commit()
            return True

    def authenticate_api_key(self, key_hash: str) -> dict[str, Any] | None:
        with self.Session() as session:
            row = session.scalar(
                select(UserApiKeyModel).where(
                    UserApiKeyModel.key_hash == key_hash,
                    UserApiKeyModel.enabled.is_(True),
                )
            )
            if row is None:
                return None
            user = session.get(UserModel, row.user_id)
            if user is None or not bool(user.enabled):
                return None
            row.last_used_at = _utc_now()
            session.commit()
            return {
                **self._user_dict(user),
                "api_key_id": str(row.id),
                "api_key_name": str(row.name),
            }

    @staticmethod
    def _user_dict(model: UserModel) -> dict[str, Any]:
        return {
            "id": str(model.id),
            "email": str(model.email),
            "display_name": str(model.display_name),
            "password_hash": str(model.password_hash),
            "role": str(model.role),
            "enabled": bool(model.enabled),
            "created_at": model.created_at.isoformat(),
            "last_login_at": model.last_login_at.isoformat() if model.last_login_at else None,
        }

    @staticmethod
    def _api_key_dict(model: UserApiKeyModel) -> dict[str, Any]:
        return {
            "id": str(model.id),
            "name": str(model.name),
            "role": "user",
            "enabled": bool(model.enabled),
            "created_at": model.created_at.isoformat(),
            "last_used_at": model.last_used_at.isoformat() if model.last_used_at else None,
        }


user_repository = UserRepository()
