from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.v2.core.config import V2Settings
from app.v2.core.database import build_engine, load_metadata, session_factory
from app.v2.core.errors import fail, install_errors


def create_app(settings=None, engine=None, wechat_exchange=None, storage=None, recognition_provider=None,
               outfit_provider=None, forecast_provider=None):
    settings = settings if settings is not None else V2Settings()
    engine = engine if engine is not None else build_engine(settings.database_url)
    load_metadata()
    app = FastAPI(title='Zhida V2')
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)
    app.state.wechat_exchange = wechat_exchange
    from app.v2.media.storage import FileStorage
    app.state.storage = storage if storage is not None else FileStorage(settings.private_storage_dir)
    app.state.recognition_provider = recognition_provider
    from app.v2.integrations.outfits import OutfitProvider
    app.state.outfit_provider = outfit_provider if outfit_provider is not None else OutfitProvider(settings)
    app.state.forecast_provider = forecast_provider
    from app.v2.core.clock import utcnow
    app.state.clock = utcnow
    install_errors(app)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/ready')
    def ready():
        try:
            with engine.connect() as connection:
                revisions = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
            if revisions != ['0005_personalization_calendar']:
                fail(503, 'NOT_READY', 'Database migration is not current')
        except SQLAlchemyError:
            fail(503, 'NOT_READY', 'Database is unavailable or not migrated')
        return {'status': 'ready'}

    from app.v2.identity.router import router as identity
    from app.v2.families.router import router as families
    from app.v2.children.router import router as children
    from app.v2.children.onboarding import router as onboarding
    from app.v2.preferences.router import router as preferences
    from app.v2.weather.router import router as weather
    from app.v2.wardrobe.router import router as wardrobe
    from app.v2.recognition.router import router as recognition
    from app.v2.media.router import router as media
    from app.v2.outfits.router import router as outfits
    for router in (identity, families, children, onboarding, preferences, weather, wardrobe, recognition, media, outfits):
        app.include_router(router, prefix='/v2')
    return app
