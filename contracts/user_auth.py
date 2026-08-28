from __future__ import annotations

from typing import Literal

from pydantic import Field

from contracts.auth import _StrictModel


class UserRegisterRequest(_StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class UserLoginRequest(_StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RegisteredUserView(_StrictModel):
    id: str
    email: str
    display_name: str
    role: Literal["user", "admin"]
    enabled: bool
    created_at: str
    last_login_at: str | None = None


class UserSessionView(_StrictModel):
    authenticated: bool = True
    access_token: str
    user: RegisteredUserView


class UserProfileView(_StrictModel):
    user: RegisteredUserView
