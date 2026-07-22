"""
FastAPI entrypoint — BIZON Command Center backend.

Mounts all routers under /api/v1 and exposes a health probe at /.
Run with:
    uvicorn main:app --reload --port 8000
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat import router as chat_router
from api.leads import router as leads_router
from api.rag import router as rag_router
from api.reports import router as reports_router
from api.tenants import router as tenants_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="BIZON — Command Center API",
    description="Autonomous AI sales platform — multi-tenant backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_V1 = "/api/v1"
app.include_router(tenants_router, prefix=_V1)
app.include_router(leads_router, prefix=_V1)
app.include_router(rag_router, prefix=_V1)
app.include_router(reports_router, prefix=_V1)
app.include_router(chat_router, prefix=_V1)


@app.get("/", tags=["health"])
def health():
    return {"status": "ok", "service": "bizon-backend"}
