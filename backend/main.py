from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes.monitors import router as monitors_router

app = FastAPI(title="Is My Website Down API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(monitors_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
