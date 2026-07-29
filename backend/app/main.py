from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.admin import router as admin_router
from app.api import router as api_router

load_dotenv()

app = FastAPI(title='Nisab API', version='0.4.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(api_router)
app.include_router(admin_router)
