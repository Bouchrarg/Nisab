"""
auth.py — Authentification JWT + gestion des mots de passe.

Flux :
  1. login -> vérifie email/password -> émet un access_token (courte durée)
     et un refresh_token (longue durée).
  2. chaque requête protégée passe par get_current_user, qui décode le
     access_token et retourne (utilisateur_id, organisation_id, role).
  3. le routeur (api.py/admin.py) utilise ensuite ces infos pour appeler
     set_tenant_context() sur la session DB (voir db_session.py) et pour
     vérifier les droits via require_role().
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

load_dotenv()

# ── config ──────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET manquant dans .env — générer une valeur aléatoire forte "
        "(ex: python -c \"import secrets; print(secrets.token_urlsafe(64))\")."
    )
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 14

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── mots de passe ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


# ── JWT ─────────────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    sub: str  # utilisateur_id
    organisation_id: str
    role: str
    type: str  # "access" | "refresh"


def _create_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(utilisateur_id: str, organisation_id: str, role: str) -> str:
    return _create_token(
        {"sub": utilisateur_id, "organisation_id": organisation_id, "role": role, "type": "access"},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(utilisateur_id: str, organisation_id: str, role: str) -> str:
    return _create_token(
        {"sub": utilisateur_id, "organisation_id": organisation_id, "role": role, "type": "refresh"},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str = "access") -> TokenPayload:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide ou expiré")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Type de token incorrect")

    return TokenPayload(**payload)


# ── dependency FastAPI ──────────────────────────────────────────────────

class CurrentUser(BaseModel):
    id: str
    organisation_id: str
    role: str


def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    payload = decode_token(token, expected_type="access")
    return CurrentUser(id=payload.sub, organisation_id=payload.organisation_id, role=payload.role)


def require_role(*allowed_roles: str):
    """
    Dependency factory : `Depends(require_role("admin_cabinet"))` sur une route
    pour la réserver à un ou plusieurs rôles.
    """

    def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle '{user.role}' non autorisé pour cette action.",
            )
        return user

    return _checker
