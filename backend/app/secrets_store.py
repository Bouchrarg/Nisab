"""
secrets_store.py — Chiffrement des identifiants ERP stockés en base.

## Pourquoi ça existe

Pousser un brouillon de correction dans Odoo suppose de se reconnecter à Odoo
au moment de la validation, donc de disposer des identifiants après la session
de synchronisation initiale. La colonne `ConnexionComptable.identifiants_chiffres`
était prévue depuis la Phase 1 et n'avait jamais été écrite.

Stocker un mot de passe ERP en clair dans une base multi-tenant serait
indéfendable — c'est le mot de passe de la comptabilité d'un client du cabinet.
D'où Fernet (AES-128-CBC + HMAC-SHA256, chiffrement authentifié) : un contenu
altéré est rejeté au déchiffrement plutôt que de produire des données fausses.

## Pourquoi une clé distincte de JWT_SECRET

`NISAB_SECRET_KEY` est volontairement séparée de `JWT_SECRET`, et non dérivée
de lui. Faire tourner le secret JWT est une opération de sécurité normale et
souhaitable (fuite suspectée, rotation périodique) : si les deux étaient liés,
cette rotation rendrait **silencieusement illisibles** tous les identifiants ERP
déjà stockés. On ne s'en apercevrait qu'à la première tentative de push, chez
un client, sans comprendre pourquoi.

## Ce qui n'est pas résolu ici, et qu'il faut dire

Une clé unique pour toute la plateforme : quiconque a la clé et un accès base
peut déchiffrer les identifiants de tous les cabinets. La vraie réponse serait
un gestionnaire de secrets externe (Vault, KMS) avec une clé par organisation.
C'est hors périmètre d'un MVP de stage, mais c'est une limite à énoncer plutôt
qu'à laisser croire résolue.
"""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

_fernet_cache: Fernet | None = None

_MESSAGE_CLE_ABSENTE = (
    "NISAB_SECRET_KEY absente de l'environnement — impossible de chiffrer ou de "
    "déchiffrer les identifiants ERP.\n"
    "Générez une clé avec :\n"
    '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
    "puis ajoutez-la au fichier backend/.env sous la forme NISAB_SECRET_KEY=...\n"
    "Attention : changer cette clé rend illisibles les identifiants déjà stockés."
)


def _fernet() -> Fernet:
    """
    Instance Fernet, construite à la première utilisation réelle.

    Volontairement paresseux : le backend doit démarrer sans NISAB_SECRET_KEY.
    Seul le workflow de correction en a besoin, et un projet qui ne s'en sert
    pas encore ne doit pas être bloqué au lancement. Même patron que
    JWT_SECRET dans auth.py.
    """
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache

    cle = os.environ.get("NISAB_SECRET_KEY")
    if not cle:
        raise RuntimeError(_MESSAGE_CLE_ABSENTE)
    try:
        _fernet_cache = Fernet(cle.encode() if isinstance(cle, str) else cle)
    except Exception as exc:
        raise RuntimeError(
            f"NISAB_SECRET_KEY invalide ({exc}). Elle doit être une clé Fernet "
            "base64-urlsafe de 32 octets, générée par Fernet.generate_key()."
        ) from exc
    return _fernet_cache


def cle_disponible() -> bool:
    """
    Le chiffrement est-il utilisable ?

    Permet à une route de répondre « fonctionnalité non configurée » avec un
    message clair, plutôt que de laisser remonter une RuntimeError en 500.
    """
    try:
        _fernet()
        return True
    except RuntimeError:
        return False


def chiffrer(donnees: dict) -> str:
    """Chiffre un dict d'identifiants en une chaîne stockable en base."""
    brut = json.dumps(donnees, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(brut).decode("ascii")


def dechiffrer(jeton: str) -> dict:
    """
    Déchiffre des identifiants précédemment stockés.

    Un InvalidToken signifie presque toujours que NISAB_SECRET_KEY a changé
    depuis le chiffrement. Le message le dit, parce que le symptôme brut
    (« signature invalide ») n'oriente vers rien.
    """
    try:
        return json.loads(_fernet().decrypt(jeton.encode("ascii")).decode("utf-8"))
    except InvalidToken as exc:
        raise RuntimeError(
            "Identifiants ERP illisibles : ils ont été chiffrés avec une autre "
            "NISAB_SECRET_KEY. Reconnectez le dossier à Odoo pour les réenregistrer."
        ) from exc
