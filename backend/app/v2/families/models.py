from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, CheckConstraint
from app.v2.core.clock import utcnow
from app.v2.core.database import Base, ID


class Family(Base):
    __tablename__ = 'families'
    id = Column(ID, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    city = Column(String(120))
    personal_owner_id = Column(ID, ForeignKey('users.id'), unique=True)
    timezone = Column(String(64), nullable=False, default='Asia/Shanghai')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(ID, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (
        UniqueConstraint('family_id', 'user_id'),
        CheckConstraint("role IN ('admin','editor','viewer')", name='role'),
        CheckConstraint("status IN ('active','removed')", name='status'),
    )
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    user_id = Column(ID, ForeignKey('users.id'), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default='active')
    joined_at = Column(DateTime, nullable=False, default=utcnow)


class Invitation(Base):
    __tablename__ = 'invitations'
    __table_args__ = (CheckConstraint("role IN ('editor','viewer')", name='role'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    role = Column(String(16), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime)
    accepted_by = Column(ID, ForeignKey('users.id'))
    accepted_at = Column(DateTime)
    created_by = Column(ID, ForeignKey('users.id'), nullable=False)


class MutationReceipt(Base):
    __tablename__ = 'mutation_receipts'
    __table_args__ = (UniqueConstraint('actor_id', 'operation', 'idempotency_key'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    actor_id = Column(ID, ForeignKey('users.id'), nullable=False)
    operation = Column(String(160), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_body = Column(JSON, nullable=False)
    status_code = Column(Integer, nullable=False)
