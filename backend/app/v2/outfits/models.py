from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.v2.core.database import Base, ID
from app.v2.core.clock import utcnow


class Recommendation(Base):
    __tablename__ = 'outfit_recommendations'
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False)
    actor_id = Column(ID, ForeignKey('users.id'), nullable=False)
    target_date = Column(Date, nullable=False)
    input_version = Column(String(64), nullable=False, index=True)
    visibility = Column(String(16), nullable=False)
    response = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class RecommendationRequest(Base):
    __tablename__ = 'outfit_recommendation_requests'
    __table_args__ = (UniqueConstraint('family_id', 'actor_id', 'request_id'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False)
    actor_id = Column(ID, ForeignKey('users.id'), nullable=False)
    request_id = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    input_version = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    response = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class OutfitPlan(Base):
    __tablename__ = 'outfit_plans'
    __table_args__ = (UniqueConstraint('family_id', 'child_id', 'target_date', 'sequence'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False)
    target_date = Column(Date, nullable=False)
    sequence = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default='selected')
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(ID, ForeignKey('users.id'), nullable=False)
    updated_by = Column(ID, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class PlanRevision(Base):
    __tablename__ = 'outfit_plan_revisions'
    __table_args__ = (UniqueConstraint('plan_id', 'version'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    plan_id = Column(ID, ForeignKey('outfit_plans.id'), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_by = Column(ID, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Reservation(Base):
    __tablename__ = 'outfit_reservations'
    __table_args__ = (UniqueConstraint('plan_id', 'garment_id', 'usage'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    target_date = Column(Date, nullable=False, index=True)
    plan_id = Column(ID, ForeignKey('outfit_plans.id'), nullable=False)
    revision_id = Column(ID, ForeignKey('outfit_plan_revisions.id'), nullable=False)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False)
    garment_id = Column(ID, ForeignKey('clothing.id'), nullable=False, index=True)
    usage = Column(String(16), nullable=False)
    arrangement = Column(JSON)
