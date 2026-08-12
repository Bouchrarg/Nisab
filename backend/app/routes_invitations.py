"""
routes_invitations.py — Un admin_cabinet invite un collègue dans son
organisation ; la personne invitée crée son compte via un lien à usage
unique plutôt que par auto-inscription (qui créerait sinon une nouvelle
organisation séparée — voir /auth/register).

Pas d'envoi d'e-mail réel pour l'instant (SMTP arrive en Phase 6 avec la
veille) : POST /invitations retourne directement le lien à copier/coller
et transmettre manuellement à la personne invitée. C'est un choix
d'MVP assumé, pas un oubli — à remplacer par un envoi automatique plus tard.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    require_role,
)
from app.db import get_db
from app.db_session import get_tenant_db, set_tenant_context
from app.models import Acces, Dossier, Invitation, NiveauDroit, RoleUtilisateur, StatutInvitation, Utilisateur

router = APIRouter(prefix="/invitations", tags=["Invitations"])

INVITATION_VALIDITY_DAYS = 7

# Un admin_cabinet ne peut inviter que ces deux rôles — jamais admin_cabinet
# (ambigu : deux admins d'un même cabinet, pas de cas d'usage clair pour le
# MVP) ni admin_plateforme (voir scripts/create_platform_admin.py, jamais
# via une route HTTP).
ROLES_INVITABLES = {RoleUtilisateur.collaborateur, RoleUtilisateur.dirigeant_pme}


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: RoleUtilisateur
    dossier_id: str | None = None  # accès direct à un dossier précis (ex. dirigeant_pme)
    niveau_droit: NiveauDroit = NiveauDroit.ecriture


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    statut: str
    dossier_id: str | None
    niveau_droit: str
    created_at: str
    expires_at: str
    lien: str | None = None  # présent seulement à la création (pas exposé sur GET /invitations)


class InvitationAcceptRequest(BaseModel):
    token: str
    nom_complet: str
    password: str


class MembreAccesInfo(BaseModel):
    dossier_id: str
    raison_sociale: str
    niveau_droit: str


class MembreResponse(BaseModel):
    id: str
    email: str
    nom_complet: str
    role: str
    actif: bool
    created_at: str
    acces: list[MembreAccesInfo] = []


class MembreStatusRequest(BaseModel):
    actif: bool


class MembreAccesRequest(BaseModel):
    dossier_id: str
    niveau_droit: NiveauDroit = NiveauDroit.ecriture


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
def create_invitation(
    req: InvitationCreateRequest,
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_tenant_db),
):
    if req.role not in ROLES_INVITABLES:
        raise HTTPException(status_code=400, detail="Rôle non invitable (collaborateur ou dirigeant_pme uniquement).")

    if req.dossier_id:
        dossier = db.get(Dossier, uuid.UUID(req.dossier_id))
        if not dossier or str(dossier.organisation_id) != user.organisation_id:
            raise HTTPException(status_code=404, detail="Dossier introuvable dans votre organisation.")

    existing_user = db.execute(select(Utilisateur).where(Utilisateur.email == req.email)).scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")

    # dirigeant_pme = client final en lecture seule par conception (voir
    # DirigeantShell) : on ignore toute autre valeur choisie par erreur dans
    # le formulaire plutôt que de laisser un client obtenir des droits
    # d'écriture sur ses propres données comptables.
    niveau_droit = NiveauDroit.lecture if req.role == RoleUtilisateur.dirigeant_pme else req.niveau_droit

    invitation = Invitation(
        id=uuid.uuid4(),
        organisation_id=uuid.UUID(user.organisation_id),
        email=req.email,
        role=req.role,
        dossier_id=uuid.UUID(req.dossier_id) if req.dossier_id else None,
        niveau_droit=niveau_droit,
        token=secrets.token_urlsafe(32),
        statut=StatutInvitation.en_attente,
        invite_par_id=uuid.UUID(user.id),
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITATION_VALIDITY_DAYS),
    )
    db.add(invitation)
    db.commit()

    return InvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role.value,
        statut=invitation.statut.value,
        dossier_id=str(invitation.dossier_id) if invitation.dossier_id else None,
        niveau_droit=invitation.niveau_droit.value,
        created_at=invitation.created_at.isoformat(),
        expires_at=invitation.expires_at.isoformat(),
        lien=f"/accepter-invitation?token={invitation.token}",  # à préfixer par l'URL du frontend côté appelant
    )


@router.get("", response_model=list[InvitationResponse])
def list_invitations(
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_db),
):
    # Pas de RLS sur invitation : filtrage explicite ici, volontairement,
    # par l'organisation de l'admin_cabinet qui appelle.
    invitations = db.execute(
        select(Invitation).where(Invitation.organisation_id == uuid.UUID(user.organisation_id)).order_by(Invitation.created_at.desc())
    ).scalars().all()
    return [
        InvitationResponse(
            id=str(i.id),
            email=i.email,
            role=i.role.value,
            statut=i.statut.value,
            dossier_id=str(i.dossier_id) if i.dossier_id else None,
            niveau_droit=i.niveau_droit.value,
            created_at=i.created_at.isoformat(),
            expires_at=i.expires_at.isoformat(),
        )
        for i in invitations
    ]


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    invitation_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_db),
):
    invitation = db.get(Invitation, invitation_id)
    if not invitation or str(invitation.organisation_id) != user.organisation_id:
        raise HTTPException(status_code=404, detail="Invitation introuvable.")
    if invitation.statut == StatutInvitation.acceptee:
        # Révoquer une invitation déjà acceptée ne ferait que relabelliser le
        # lien (déjà consommé) sans rien changer pour le compte créé — ça
        # donnerait l'illusion d'avoir coupé l'accès. La vraie action, c'est
        # de désactiver le compte via /invitations/membres/{id}/status.
        raise HTTPException(
            status_code=400,
            detail="Cette invitation a déjà été acceptée : désactivez le compte du membre depuis l'onglet Équipe plutôt que de révoquer l'invitation.",
        )
    invitation.statut = StatutInvitation.revoquee
    db.commit()


def _membre_response(db: Session, membre: Utilisateur) -> MembreResponse:
    rows = db.execute(
        select(Acces, Dossier).join(Dossier, Dossier.id == Acces.dossier_id).where(Acces.utilisateur_id == membre.id)
    ).all()
    return MembreResponse(
        id=str(membre.id),
        email=membre.email,
        nom_complet=membre.nom_complet,
        role=membre.role.value,
        actif=membre.actif,
        created_at=membre.created_at.isoformat(),
        acces=[
            MembreAccesInfo(dossier_id=str(d.id), raison_sociale=d.raison_sociale, niveau_droit=a.niveau_droit.value)
            for a, d in rows
        ],
    )


@router.get("/membres", response_model=list[MembreResponse])
def list_membres(
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_tenant_db),
):
    """
    Comptes réels de l'organisation (créés via /auth/register ou une
    invitation acceptée) — distinct de la liste des invitations, qui ne
    couvre que les liens envoyés. C'est ici qu'on désactive un accès déjà
    créé, une invitation révoquée n'y suffisant pas (cf. revoke_invitation).
    get_tenant_db (pas get_db) : _membre_response lit Acces/Dossier, qui
    sont protégées par RLS et ont besoin du contexte app.current_org_id.
    """
    membres = db.execute(
        select(Utilisateur).where(Utilisateur.organisation_id == uuid.UUID(user.organisation_id)).order_by(Utilisateur.created_at)
    ).scalars().all()
    return [_membre_response(db, m) for m in membres]


@router.patch("/membres/{utilisateur_id}/status", response_model=MembreResponse)
def set_membre_status(
    utilisateur_id: uuid.UUID,
    req: MembreStatusRequest,
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_tenant_db),
):
    if str(utilisateur_id) == user.id:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas désactiver votre propre compte.")
    membre = db.get(Utilisateur, utilisateur_id)
    if not membre or str(membre.organisation_id) != user.organisation_id:
        raise HTTPException(status_code=404, detail="Membre introuvable dans votre organisation.")
    if membre.role == RoleUtilisateur.admin_cabinet:
        raise HTTPException(status_code=400, detail="Un admin_cabinet ne peut pas être désactivé depuis cet écran.")
    membre.actif = req.actif
    # _membre_response AVANT commit() : set_config(..., true) (posé par
    # get_tenant_db) est scopé à la transaction en cours — un commit() la
    # termine et fait perdre le contexte RLS pour toute requête suivante
    # sur Acces/Dossier (cause exacte du 500 rencontré sur grant_membre_acces).
    response = _membre_response(db, membre)
    db.commit()
    return response


@router.post("/membres/{utilisateur_id}/acces", response_model=MembreResponse, status_code=status.HTTP_201_CREATED)
def grant_membre_acces(
    utilisateur_id: uuid.UUID,
    req: MembreAccesRequest,
    user: CurrentUser = Depends(require_role("admin_cabinet")),
    db: Session = Depends(get_tenant_db),
):
    """
    Donne (ou met à jour) l'accès d'un membre déjà créé à un dossier —
    contrairement à l'invitation, qui ne fixe le dossier qu'une seule fois
    à la création du compte, ceci permet d'ajouter des dossiers après coup.
    """
    membre = db.get(Utilisateur, utilisateur_id)
    if not membre or str(membre.organisation_id) != user.organisation_id:
        raise HTTPException(status_code=404, detail="Membre introuvable dans votre organisation.")
    if membre.role == RoleUtilisateur.admin_cabinet:
        raise HTTPException(status_code=400, detail="Un admin_cabinet a déjà accès à tous les dossiers du cabinet.")

    dossier = db.get(Dossier, uuid.UUID(req.dossier_id))
    if not dossier or str(dossier.organisation_id) != user.organisation_id:
        raise HTTPException(status_code=404, detail="Dossier introuvable dans votre organisation.")

    # dirigeant_pme = lecture seule par conception, même règle qu'à l'invitation.
    niveau_droit = NiveauDroit.lecture if membre.role == RoleUtilisateur.dirigeant_pme else req.niveau_droit

    existing = db.execute(
        select(Acces).where(Acces.utilisateur_id == utilisateur_id, Acces.dossier_id == dossier.id)
    ).scalar_one_or_none()
    if existing:
        existing.niveau_droit = niveau_droit
    else:
        db.add(Acces(id=uuid.uuid4(), utilisateur_id=utilisateur_id, dossier_id=dossier.id, niveau_droit=niveau_droit))
    # Même raison que set_membre_status : construire la réponse avant le
    # commit(), pendant que le contexte RLS de la transaction est encore actif.
    response = _membre_response(db, membre)
    db.commit()
    return response


@router.post("/accept", response_model=TokenResponse)
def accept_invitation(req: InvitationAcceptRequest, db: Session = Depends(get_db)):
    invitation = db.execute(select(Invitation).where(Invitation.token == req.token)).scalar_one_or_none()
    if not invitation or invitation.statut != StatutInvitation.en_attente:
        raise HTTPException(status_code=400, detail="Invitation invalide ou déjà utilisée.")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invitation expirée.")

    existing_user = db.execute(select(Utilisateur).where(Utilisateur.email == invitation.email)).scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")

    new_user = Utilisateur(
        id=uuid.uuid4(),
        organisation_id=invitation.organisation_id,
        email=invitation.email,
        password_hash=hash_password(req.password),
        nom_complet=req.nom_complet,
        role=invitation.role,
    )
    db.add(new_user)
    db.flush()

    if invitation.dossier_id:
        # La policy RLS de `acces` exige que app.current_org_id soit positionné
        # (même en INSERT, faute de WITH CHECK explicite elle hérite de USING).
        # Contexte légitime ici : on vient de vérifier que l'invitation, son
        # organisation et son dossier sont cohérents entre eux.
        set_tenant_context(db, str(invitation.organisation_id))
        db.add(Acces(id=uuid.uuid4(), utilisateur_id=new_user.id, dossier_id=invitation.dossier_id, niveau_droit=invitation.niveau_droit))

    invitation.statut = StatutInvitation.acceptee
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(new_user.id), str(new_user.organisation_id), new_user.role.value),
        refresh_token=create_refresh_token(str(new_user.id), str(new_user.organisation_id), new_user.role.value),
    )
