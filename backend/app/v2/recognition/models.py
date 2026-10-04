from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Boolean, UniqueConstraint
from app.v2.core.database import Base, ID
from app.v2.core.clock import utcnow


class IntakeBatch(Base):
    __tablename__ = 'intake_batches'
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    created_by = Column(ID, ForeignKey('users.id'), nullable=False, index=True)
    default_child_id = Column(ID, ForeignKey('children.id'), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class IntakeItem(Base):
    __tablename__ = 'intake_items'
    __table_args__ = (UniqueConstraint('batch_id', 'client_id'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    batch_id = Column(ID, ForeignKey('intake_batches.id'), nullable=False, index=True)
    client_id = Column(String(128), nullable=False)
    source = Column(String(20), nullable=False)
    asset_id = Column(ID, ForeignKey('media_assets.id'))
    status = Column(String(20), nullable=False, default='manual')
    version = Column(Integer, nullable=False, default=1)
    discarded = Column(Boolean, nullable=False, default=False)
    error = Column(JSON)
    generation = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class RecognitionAttempt(Base):
    __tablename__ = 'recognition_attempts'
    __table_args__ = (UniqueConstraint('item_id', 'generation'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    item_id = Column(ID, ForeignKey('intake_items.id'), nullable=False, index=True)
    generation = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='queued', index=True)
    claim_token = Column(String(64))
    lease_until = Column(DateTime)
    available_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    tries = Column(Integer, nullable=False, default=0)
    request_id = Column(String(64), nullable=False)
    error = Column(JSON)
    result = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Candidate(Base):
    __tablename__ = 'intake_candidates'
    __table_args__ = (UniqueConstraint('batch_id', 'client_id'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    batch_id = Column(ID, ForeignKey('intake_batches.id'), nullable=False, index=True)
    item_id = Column(ID, ForeignKey('intake_items.id'), nullable=False, index=True)
    client_id = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    attempt_id = Column(ID, ForeignKey('recognition_attempts.id'))
    version = Column(Integer, nullable=False, default=1)
    name = Column(String(80), nullable=False, default='')
    category = Column(String(20))
    colors = Column(JSON, nullable=False, default=list)
    pattern = Column(String(20), nullable=False, default='unknown')
    thickness = Column(String(20), nullable=False, default='unknown')
    state = Column(String(20), nullable=False, default='ready')
    owners = Column(JSON, nullable=False, default=list)
    selected = Column(Boolean, nullable=False, default=False)
    discarded = Column(Boolean, nullable=False, default=False)
    ownership_exception = Column(Boolean, nullable=False, default=False)
    dirty_fields = Column(JSON, nullable=False, default=list)
    bbox = Column(JSON)
    confirmed_garment_id = Column(ID, ForeignKey('clothing.id'))
    confirmation_kind = Column(String(20))
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Operation(Base):
    __tablename__ = 'wardrobe_operations'
    __table_args__ = (UniqueConstraint('family_id', 'actor_id', 'scope', 'operation_id'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    actor_id = Column(ID, ForeignKey('users.id'), nullable=False)
    scope = Column(String(128), nullable=False)
    operation_id = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
