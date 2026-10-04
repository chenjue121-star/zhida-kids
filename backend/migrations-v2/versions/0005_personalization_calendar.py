"""Immutable feedback, bounded learning projections, calendar status and import provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0005_personalization_calendar'
down_revision = '0004_daily_outfits'
branch_labels = None
depends_on = None


def identifier(name, primary=False, nullable=False):
    return sa.Column(name, sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                     primary_key=primary, autoincrement=primary, nullable=nullable)


def fk(table, column, target):
    return sa.ForeignKeyConstraint([column], [target + '.id'], name=op.f(f'fk_{table}_{column}_{target}'))


def upgrade():
    op.add_column('outfit_plans', sa.Column('status', sa.String(16), nullable=False, server_default='selected'))
    op.add_column('preference_profiles', sa.Column('inferred_tags', sa.JSON(), nullable=True))
    op.add_column('preference_profiles', sa.Column('suppression_cutoffs', sa.JSON(), nullable=True))
    op.add_column('preference_profiles', sa.Column('learning_version', sa.Integer(), nullable=False, server_default='0'))
    op.execute(sa.text("UPDATE preference_profiles SET inferred_tags = '[]', suppression_cutoffs = '{}'"))
    with op.batch_alter_table('preference_profiles') as batch:
        batch.alter_column('inferred_tags', existing_type=sa.JSON(), nullable=False)
        batch.alter_column('suppression_cutoffs', existing_type=sa.JSON(), nullable=False)
    table = 'preference_feedback_events'
    op.create_table(table, identifier('id', primary=True), identifier('family_id'), identifier('child_id'),
        identifier('actor_id'), identifier('membership_id'), sa.Column('owner_key', sa.String(64), nullable=False),
        sa.Column('event_id', sa.String(128), nullable=False), sa.Column('request_hash', sa.String(64), nullable=False),
        identifier('plan_id'), sa.Column('plan_version', sa.Integer(), nullable=False), identifier('revision_id'),
        sa.Column('source_subject', sa.JSON(), nullable=False), sa.Column('signal', sa.String(16), nullable=False),
        sa.Column('reason', sa.String(16), nullable=False), sa.Column('styles', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        fk(table, 'family_id', 'families'), fk(table, 'child_id', 'children'), fk(table, 'actor_id', 'users'),
        fk(table, 'membership_id', 'memberships'), fk(table, 'plan_id', 'outfit_plans'),
        fk(table, 'revision_id', 'outfit_plan_revisions'),
        sa.UniqueConstraint('family_id', 'actor_id', 'event_id', name=op.f('uq_preference_feedback_events_family_id')))
    op.create_index(op.f('ix_preference_feedback_events_child_id'), table, ['child_id'])
    table = 'legacy_source_records'
    op.create_table(table, identifier('id', primary=True),
        sa.Column('source_namespace', sa.String(64), nullable=False), sa.Column('entity', sa.String(24), nullable=False),
        sa.Column('source_id', sa.String(128), nullable=False), sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('target_table', sa.String(64)),
        identifier('target_id', nullable=True), sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('source_namespace', 'entity', 'source_id', name=op.f('uq_legacy_source_records_source_namespace')))


def downgrade():
    op.drop_table('legacy_source_records')
    op.drop_table('preference_feedback_events')
    with op.batch_alter_table('preference_profiles') as batch:
        for name in ('learning_version', 'suppression_cutoffs', 'inferred_tags'):
            batch.drop_column(name)
    with op.batch_alter_table('outfit_plans') as batch:
        batch.drop_column('status')
