from sqlalchemy import Column, DateTime, String
from app.v2.core.clock import utcnow
from app.v2.core.database import Base, ID


class User(Base):
    __tablename__ = 'users'
    id = Column(ID, primary_key=True, autoincrement=True)
    openid = Column(String(128), unique=True, nullable=False)
    nickname = Column(String(80), nullable=False, default='')
    created_at = Column(DateTime, nullable=False, default=utcnow)
