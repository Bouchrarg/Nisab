"""
routes_auth.py — Endpoints d'authentification.

/auth/register : crée une nouvelle organisation + son premier utilisateur
                  (admin_cabinet). Pour ajouter des collègues à une
                  organisation existante, prévoir plus tard un flux
                  d'invitation distinct (hors périmètre Phase 2).
/auth/login     : vérifie email/password, retourne access + refresh token.
/auth/refresh   : échange un refresh_token valide contre un nouveau access_token.
/auth/me        : retourne l'utilisateur courant (utile pour le frontend au démarrage).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db import get_db
from app.models import Organisation, RoleUtilisateur, TypeOrganisation, Utilisateur

router = APIRouter(prefix="/auth", tags=["Authentification"])


# ── schémas ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    nom_organisation: str
    type_organisation: TypeOrganisation
    email: EmailStr
    password: str
    nom_complet: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    nom_complet: str
    role: str
    organisation_id: str
    organisation_nom: str


# ── endpoints ────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.execute(select(Utilisateur).where(Utilisateur.email == req.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")

    org = Organisation(
        id=uuid.uuid4(),
        nom=req.nom_organisation,
        type_organisation=req.type_organisation,
    )
    db.add(org)
    db.flush()  # pour obtenir org.id sans commit complet

    user = Utilisateur(
        id=uuid.uuid4(),
        organisation_id=org.id,
        email=req.email,
        password_hash=hash_password(req.password),
        nom_complet=req.nom_complet,
        role=RoleUtilisateur.admin_cabinet,  # le créateur de l'organisation est admin par défaut
    )
    db.add(user)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id), str(org.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id), str(org.id), user.role.value),
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(Utilisateur).where(Utilisateur.email == req.email)).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")

    return TokenResponse(
        access_token=create_access_token(str(user.id), str(user.organisation_id), user.role.value),
        refresh_token=create_refresh_token(str(user.id), str(user.organisation_id), user.role.value),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest):
    payload = decode_token(req.refresh_token, expected_type="refresh")
    return TokenResponse(
        access_token=create_access_token(payload.sub, payload.organisation_id, payload.role),
        refresh_token=create_refresh_token(payload.sub, payload.organisation_id, payload.role),
    )


@router.get("/me", response_model=UserResponse)
def me(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(Utilisateur, uuid.UUID(current.id))
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    org = db.get(Organisation, user.organisation_id)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        nom_complet=user.nom_complet,
        role=user.role.value,
        organisation_id=str(user.organisation_id),
        organisation_nom=org.nom if org else "",
    )
