from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .accounts import router as accounts_router
from .db import init_db
from .graph import router as graph_router
from .imap_sync import router as imap_router

app = FastAPI(title="Outlook Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(accounts_router)
app.include_router(graph_router)
app.include_router(imap_router)
