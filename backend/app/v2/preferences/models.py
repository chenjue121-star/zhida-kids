from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, CheckConstraint, event
from app.v2.core.database import Base, ID


class PreferenceSettings(Base):
    __tablename__ = 'child_preference_settings'
    __table_args__ = (CheckConstraint(
        "(mode = 'designated_member' AND designated_member_id IS NOT NULL) OR "
        "(mode IN ('family','current_member') AND designated_member_id IS NULL)", name='mode_member'
    ),)
    child_id = Column(ID, ForeignKey('children.id'), primary_key=True)
    mode = Column(String(24), nullable=False, default='family')
    designated_member_id = Column(ID, ForeignKey('memberships.id'))
    thermal_preference = Column(String(16), nullable=False, default='unknown')
    fit_preference = Column(String(16), nullable=False, default='unknown')
    avoid_high_neck = Column(Boolean)
    version = Column(Integer, nullable=False, default=1)


class PreferenceProfile(Base):
    __tablename__ = 'preference_profiles'
    __table_args__ = (UniqueConstraint('child_id', 'owner_key'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False, index=True)
    owner_key = Column(String(64), nullable=False)
    membership_id = Column(ID, ForeignKey('memberships.id'))
    styles = Column(JSON, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    inferred_tags = Column(JSON, nullable=False, default=list)
    suppression_cutoffs = Column(JSON, nullable=False, default=dict)
    learning_version = Column(Integer, nullable=False, default=0)


class FeedbackEvent(Base):
    """Append-only facts; projections and suppression are stored on the profile."""
    __tablename__ = 'preference_feedback_events'
    __table_args__ = (UniqueConstraint('family_id', 'actor_id', 'event_id'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False, index=True)
    actor_id = Column(ID, ForeignKey('users.id'), nullable=False)
    membership_id = Column(ID, ForeignKey('memberships.id'), nullable=False)
    owner_key = Column(String(64), nullable=False)
    event_id = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    plan_id = Column(ID, ForeignKey('outfit_plans.id'), nullable=False)
    plan_version = Column(Integer, nullable=False)
    revision_id = Column(ID, ForeignKey('outfit_plan_revisions.id'), nullable=False)
    source_subject = Column(JSON, nullable=False)
    signal = Column(String(16), nullable=False)
    reason = Column(String(16), nullable=False)
    styles = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


@event.listens_for(FeedbackEvent, 'before_update')
@event.listens_for(FeedbackEvent, 'before_delete')
def immutable_feedback(mapper, connection, target):
    raise ValueError('Feedback events are immutable')
