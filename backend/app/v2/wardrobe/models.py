from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, CheckConstraint
from app.v2.core.database import Base, ID
from app.v2.core.clock import utcnow


class Clothing(Base):
    """A family-owned physical object, independently of its child users."""
    __tablename__ = 'clothing'
    __table_args__ = (CheckConstraint("state IN ('ready','washing','missing')", name='state'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    created_by = Column(ID, ForeignKey('users.id'), nullable=False)
    # Unique origin is the second fence against confirmation with another key.
    source_candidate_id = Column(ID, nullable=True, unique=True)
    name = Column(String(80), nullable=False)
    category = Column(String(20), nullable=False)
    colors = Column(JSON, nullable=False, default=list)
    pattern = Column(String(20), nullable=False, default='unknown')
    thickness = Column(String(20), nullable=False, default='unknown')
    state = Column(String(20), nullable=False, default='ready')
    asset_id = Column(ID, ForeignKey('media_assets.id'))
    archived_at = Column(DateTime)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ChildClothing(Base):
    __tablename__ = 'child_clothing'
    __table_args__ = (UniqueConstraint('clothing_id', 'child_id'),
                      CheckConstraint("fit IN ('small','fit','large','unknown')", name='fit'))
    id = Column(ID, primary_key=True, autoincrement=True)
    clothing_id = Column(ID, ForeignKey('clothing.id'), nullable=False, index=True)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False, index=True)
    fit = Column(String(20), nullable=False)
    ended_at = Column(DateTime)


class ClothingRemoval(Base):
    __tablename__ = 'clothing_removals'
    id = Column(ID, primary_key=True, autoincrement=True)
    clothing_id = Column(ID, ForeignKey('clothing.id'), nullable=False, index=True)
    removed_by = Column(ID, ForeignKey('users.id'), nullable=False)
    owners = Column(JSON, nullable=False)
    removed_at = Column(DateTime, nullable=False, default=utcnow)
