from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import router as admin_router
from app.api import router as api_router
from app.auth import decode_token
from app.journal_acces import enregistrer_acces
from app.routes_auth import router as auth_router
from app.routes_corrections import router as corrections_router
from app.routes_dossiers import router as dossiers_router
from app.routes_ingestion import router as ingestion_router
from app.routes_invitations import router as invitations_router
from app.routes_roi import router as roi_router
from app.routes_simulation import router as simulation_router
from app.routes_veille import router as veille_router

load_dotenv()

app = FastAPI(title='Nisab API', version='0.5.0')


# .strip() par élément : sans lui, "http://a,http://b" fonctionne mais
# "http://a, http://b" (espace après la virgule — la forme la plus naturelle
# à taper dans un champ de variables d'environnement Render/Railway) laissait
# passer " http://b" avec un espace en tête, qu'aucune origine de navigateur
# ne peut jamais égaler : la deuxième origine ne matchait donc jamais, en
# silence (aucune erreur au démarrage, juste des requêtes bloquées par CORS
# depuis le deuxième domaine).
_allowed_origins = [
    o.strip() for o in os.environ.get("NISAB_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

#: Préfixes de routes touchant des données personnelles/comptables — exigence
#: CNDP (cf. cahier-des-charges.md, loi 09-08). Volontairement PAS tout
#: endpoint (santé, docs, auth) : journaliser un GET de polling frontend ou
#: un OPTIONS CORS gonflerait l'écriture sans rien apporter à l'intention
#: réelle du texte (tracer l'accès aux données comptables/fiscales d'un
#: dossier), et alourdirait chaque requête d'un aller-retour DB de plus.
_PREFIXES_JOURNALISES = ("/dossiers", "/admin", "/invitations")


@app.middleware("http")
async def journaliser_acces(request, call_next):
    response = await call_next(request)

    if request.url.path.startswith(_PREFIXES_JOURNALISES):
        organisation_id = None
        utilisateur_id = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            try:
                payload = decode_token(auth_header[7:], expected_type="access")
                organisation_id = payload.organisation_id
                utilisateur_id = payload.sub
            except Exception:
                # Jeton absent, expiré ou invalide : on journalise quand même
                # la TENTATIVE d'accès (avec organisation/utilisateur à None),
                # jamais bloquant — cf. journal_acces.py.
                pass
        enregistrer_acces(organisation_id, utilisateur_id, request.url.path)

    return response


app.include_router(auth_router)
app.include_router(invitations_router)
app.include_router(dossiers_router)
app.include_router(ingestion_router)
app.include_router(corrections_router)
app.include_router(veille_router)
app.include_router(simulation_router)
app.include_router(roi_router)
app.include_router(api_router)
app.include_router(admin_router)
