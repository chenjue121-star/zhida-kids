from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .routers import auth, children, clothing, diaries, me, outfits, style_rules, upload, weather
from .style_rules import get_current_ruleset


def create_app() -> FastAPI:
    app = FastAPI(title="智搭儿童穿搭 API", version="0.1.0")

    origins = ["*"] if settings.cors_origins == "*" else [o.strip() for o in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Base.metadata.create_all(bind=engine)
    get_current_ruleset()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(children.router)
    app.include_router(clothing.router)
    app.include_router(diaries.router)
    app.include_router(upload.router)
    app.include_router(weather.router)
    app.include_router(style_rules.router)
    app.include_router(outfits.router)
    return app


app = create_app()
