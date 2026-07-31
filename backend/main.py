import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routes.monitors import router as monitors_router

app = FastAPI(title="Is My Website Down API", version="1.0.0")

allowed_origins = os.getenv(
    "FRONTEND_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

init_db()
app.include_router(monitors_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
