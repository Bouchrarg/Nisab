"""
routes_auth.py — Endpoints d'authentification.

/auth/register : crée une nouvelle organisation + son premier utilisateur
                  (admin_cabinet). Pour ajouter des collègues à une
                  organisation existante, prévoir plus tard un flux
                  d'invitation distinct .
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
from app.db_session import get_tenant_db
from app.models import Acces, Dossier, Organisation, RoleUtilisateur, TypeOrganisation, Utilisateur

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
    created_at: str


class MesAccesInfo(BaseModel):
    dossier_id: str
    raison_sociale: str
    niveau_droit: str


# ── endpoints ────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # SÉCURITÉ : ce endpoint public ne crée jamais que des admin_cabinet
    # (auto-inscription d'un cabinet/PME cliente). Le rôle admin_plateforme
    # (accès au corpus fiscal partagé, à la veille, au pipeline) n'est
    # JAMAIS attribuable via une route publique — voir scripts/create_platform_admin.py.
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
    if not user.actif:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce compte a été désactivé. Contactez votre administrateur.")

    return TokenResponse(
        access_token=create_access_token(str(user.id), str(user.organisation_id), user.role.value),
        refresh_token=create_refresh_token(str(user.id), str(user.organisation_id), user.role.value),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(req.refresh_token, expected_type="refresh")
    # Contrairement à l'access token (courte durée, vérification stateless
    # suffisante), le refresh token vit 14 jours : sans ce contrôle, un
    # compte désactivé pourrait continuer à renouveler indéfiniment son
    # accès. C'est le seul point du flux d'auth qui retouche la base.
    user = db.get(Utilisateur, uuid.UUID(payload.sub))
    if not user or not user.actif:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalide.")
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
        created_at=user.created_at.isoformat(),
    )


@router.get("/me/acces", response_model=list[MesAccesInfo])
def mes_acces(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_tenant_db)):
    """
    Les dossiers accessibles au compte courant, pour que ProfilePage les
    affiche sans passer par un admin. get_tenant_db (pas get_db) : Acces et
    Dossier sont protégées par RLS, cf. list_membres (routes_invitations.py)
    qui a le même besoin côté admin.

    Un admin_cabinet n'a typiquement AUCUNE ligne Acces explicite — son accès
    à tous les dossiers de l'organisation vient de son rôle (tenant_guard.py),
    pas de cette table. Liste vide pour ce rôle n'est donc pas une anomalie ;
    le frontend l'affiche différemment (cf. ProfilePage.jsx).
    """
    rows = db.execute(
        select(Acces, Dossier)
        .join(Dossier, Dossier.id == Acces.dossier_id)
        .where(Acces.utilisateur_id == uuid.UUID(current.id))
    ).all()
    return [
        MesAccesInfo(dossier_id=str(d.id), raison_sociale=d.raison_sociale, niveau_droit=a.niveau_droit.value)
        for a, d in rows
    ]


class UpdateProfileRequest(BaseModel):
    nom_complet: str


class ChangePasswordRequest(BaseModel):
    mot_de_passe_actuel: str
    nouveau_mot_de_passe: str


@router.patch("/me", response_model=UserResponse)
def update_me(req: UpdateProfileRequest, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(Utilisateur, uuid.UUID(current.id))
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    user.nom_complet = req.nom_complet
    db.commit()
    org = db.get(Organisation, user.organisation_id)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        nom_complet=user.nom_complet,
        role=user.role.value,
        organisation_id=str(user.organisation_id),
        organisation_nom=org.nom if org else "",
        created_at=user.created_at.isoformat(),
    )


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(req: ChangePasswordRequest, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(Utilisateur, uuid.UUID(current.id))
    if not user or not verify_password(req.mot_de_passe_actuel, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mot de passe actuel incorrect.")
    if len(req.nouveau_mot_de_passe) < 8:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit faire au moins 8 caractères.")
    user.password_hash = hash_password(req.nouveau_mot_de_passe)
    db.commit()
