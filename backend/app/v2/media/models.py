from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from app.v2.core.database import Base, ID
from app.v2.core.clock import utcnow


class MediaAsset(Base):
    __tablename__ = 'media_assets'
    __table_args__ = (UniqueConstraint('family_id', 'sha256'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    sha256 = Column(String(64), nullable=False)
    object_key = Column(String(240), nullable=False)
    content_type = Column(String(40), nullable=False, default='image/jpeg')
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
