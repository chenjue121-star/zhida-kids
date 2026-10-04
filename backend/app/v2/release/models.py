from sqlalchemy import Column, DateTime, JSON, String, UniqueConstraint, event

from app.v2.core.clock import utcnow
from app.v2.core.database import Base, ID


class LegacySourceRecord(Base):
    """Immutable source provenance and unique import mapping, never a wear fact."""
    __tablename__ = 'legacy_source_records'
    __table_args__ = (UniqueConstraint('source_namespace', 'entity', 'source_id'),)
    id = Column(ID, primary_key=True, autoincrement=True)
    source_namespace = Column(String(64), nullable=False)
    entity = Column(String(24), nullable=False)
    source_id = Column(String(128), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    target_table = Column(String(64))
    target_id = Column(ID)
    imported_at = Column(DateTime, nullable=False, default=utcnow)


@event.listens_for(LegacySourceRecord, 'before_update')
@event.listens_for(LegacySourceRecord, 'before_delete')
def immutable_source_record(mapper, connection, target):
    raise ValueError('Legacy source provenance is immutable')
