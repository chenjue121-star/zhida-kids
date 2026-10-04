from __future__ import annotations

from sqlalchemy import BigInteger, Integer, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from fastapi import Request


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        'ix': 'ix_%(column_0_label)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s',
        'ck': 'ck_%(table_name)s_%(constraint_name)s',
        'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
        'pk': 'pk_%(table_name)s',
    })


ID = BigInteger().with_variant(Integer, 'sqlite')


def load_metadata():
    from app.v2.identity import models as identity_models
    from app.v2.families import models as family_models
    from app.v2.children import models as child_models
    from app.v2.preferences import models as preference_models
    from app.v2.media import models as media_models
    from app.v2.wardrobe import models as wardrobe_models
    from app.v2.recognition import models as recognition_models
    from app.v2.outfits import models as outfit_models
    from app.v2.release import models as release_models
    return Base.metadata


def build_engine(url):
    return create_engine(url, pool_pre_ping=True)


def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
