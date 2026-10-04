from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, CheckConstraint
from app.v2.core.clock import utcnow
from app.v2.core.database import Base, ID


class Child(Base):
    __tablename__ = 'children'
    id = Column(ID, primary_key=True, autoincrement=True)
    family_id = Column(ID, ForeignKey('families.id'), nullable=False, index=True)
    nickname = Column(String(80), nullable=False)
    birthday = Column(Date)
    age_months = Column(Integer)
    age_recorded_on = Column(Date)
    skin_tone = Column(String(16))
    archived_at = Column(DateTime)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ChildMeasurement(Base):
    __tablename__ = 'child_measurements'
    __table_args__ = (
        CheckConstraint('height_cm IS NOT NULL OR weight_kg IS NOT NULL', name='has_value'),
        CheckConstraint('height_cm IS NULL OR height_cm > 0', name='positive_height'),
        CheckConstraint('weight_kg IS NULL OR weight_kg > 0', name='positive_weight'),
    )
    id = Column(ID, primary_key=True, autoincrement=True)
    child_id = Column(ID, ForeignKey('children.id'), nullable=False, index=True)
    height_cm = Column(Numeric(8, 2))
    weight_kg = Column(Numeric(8, 2))
    measured_on = Column(Date, nullable=False)
