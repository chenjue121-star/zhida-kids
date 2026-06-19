import atexit
import os
import tempfile

# 必须在导入 app 之前设置：让 database.engine 指向临时 SQLite 文件
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".sqlite3")
os.close(_DB_FD)
atexit.register(lambda: os.path.exists(_DB_PATH) and os.unlink(_DB_PATH))
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_DB_PATH}"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["DEV_WECHAT_MOCK"] = "true"

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import Base, SessionLocal, engine, get_db
from app.main import create_app
from app.models import Child, Clothing, User


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed(db_session):
    """建一个 user + child + 两件 clothing，返回字典方便断言。"""
    for model in (Clothing, Child, User):
        db_session.query(model).delete()
    db_session.commit()

    user = User(openid="test-openid", nickname="测试家长")
    db_session.add(user)
    db_session.flush()

    child = Child(
        user_id=user.id, nickname="宝宝", gender="boy",
        birthday=date(2022, 1, 1), height=90.0,
    )
    db_session.add(child)
    db_session.flush()

    top = Clothing(
        child_id=child.id, type="top", main_color="white",
        thickness="normal", pattern="solid", season=["all"], style_tags=["casual"],
    )
    pants = Clothing(
        child_id=child.id, type="pants", main_color="navy",
        thickness="normal", pattern="solid", season=["all"], style_tags=["casual"],
    )
    db_session.add_all([top, pants])
    db_session.commit()
    return {"user_id": user.id, "child_id": child.id,
            "top_id": top.id, "pants_id": pants.id}


@pytest.fixture
def client(seed, db_session):
    """已认证 TestClient：覆盖 get_current_user 返回 seed 用户。"""
    app = create_app()

    def _override_user():
        return db_session.get(User, seed["user_id"])

    app.dependency_overrides[get_current_user] = _override_user
    with TestClient(app) as c:
        c.seed = seed
        yield c
    app.dependency_overrides.clear()
