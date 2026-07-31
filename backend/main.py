from config import settings

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routes.monitors import router as monitors_router

app = FastAPI(title="Is My Website Down API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

init_db()
app.include_router(monitors_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
