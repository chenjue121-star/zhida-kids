"""Daily suggestions, append-only plan revisions and current reservation references."""
from alembic import op
import sqlalchemy as sa

revision = '0004_daily_outfits'
down_revision = '0003_wardrobe_intake'
branch_labels = None
depends_on = None


def identifier(name, target=None, primary=False):
    column = sa.Column(name, sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                       primary_key=primary, autoincrement=primary, nullable=False)
    return column


def fk(table, column, target):
    return sa.ForeignKeyConstraint([column], [target + '.id'], name=op.f(f'fk_{table}_{column}_{target}'))


def upgrade():
    table = 'outfit_recommendations'
    op.create_table(table, identifier('id', primary=True), identifier('family_id'), identifier('child_id'), identifier('actor_id'),
        sa.Column('target_date', sa.Date(), nullable=False), sa.Column('input_version', sa.String(64), nullable=False),
        sa.Column('visibility', sa.String(16), nullable=False), sa.Column('response', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), fk(table, 'family_id', 'families'),
        fk(table, 'child_id', 'children'), fk(table, 'actor_id', 'users'))
    op.create_index(op.f('ix_outfit_recommendations_family_id'), table, ['family_id'])
    op.create_index(op.f('ix_outfit_recommendations_input_version'), table, ['input_version'])
    table = 'outfit_recommendation_requests'
    op.create_table(table, identifier('id', primary=True), identifier('family_id'), identifier('actor_id'),
        sa.Column('request_id', sa.String(128), nullable=False), sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('input_version', sa.String(64), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('response', sa.JSON()), sa.Column('created_at', sa.DateTime(), nullable=False),
        fk(table, 'family_id', 'families'), fk(table, 'actor_id', 'users'),
        sa.UniqueConstraint('family_id', 'actor_id', 'request_id', name=op.f('uq_outfit_recommendation_requests_family_id')))
    table = 'outfit_plans'
    op.create_table(table, identifier('id', primary=True), identifier('family_id'), identifier('child_id'),
        sa.Column('target_date', sa.Date(), nullable=False), sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), identifier('created_by'), identifier('updated_by'),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        fk(table, 'family_id', 'families'), fk(table, 'child_id', 'children'), fk(table, 'created_by', 'users'),
        fk(table, 'updated_by', 'users'), sa.UniqueConstraint('family_id', 'child_id', 'target_date', 'sequence',
            name=op.f('uq_outfit_plans_family_id')))
    op.create_index(op.f('ix_outfit_plans_family_id'), table, ['family_id'])
    table = 'outfit_plan_revisions'
    op.create_table(table, identifier('id', primary=True), identifier('plan_id'),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False),
        identifier('created_by'), sa.Column('created_at', sa.DateTime(), nullable=False),
        fk(table, 'plan_id', 'outfit_plans'), fk(table, 'created_by', 'users'),
        sa.UniqueConstraint('plan_id', 'version', name=op.f('uq_outfit_plan_revisions_plan_id')))
    table = 'outfit_reservations'
    op.create_table(table, identifier('id', primary=True), identifier('family_id'),
        sa.Column('target_date', sa.Date(), nullable=False), identifier('plan_id'), identifier('revision_id'),
        identifier('child_id'), identifier('garment_id'), sa.Column('usage', sa.String(16), nullable=False),
        sa.Column('arrangement', sa.JSON()), fk(table, 'family_id', 'families'), fk(table, 'plan_id', 'outfit_plans'),
        fk(table, 'revision_id', 'outfit_plan_revisions'), fk(table, 'child_id', 'children'), fk(table, 'garment_id', 'clothing'),
        sa.UniqueConstraint('plan_id', 'garment_id', 'usage', name=op.f('uq_outfit_reservations_plan_id')))
    for field in ('family_id', 'target_date', 'garment_id'):
        op.create_index(op.f('ix_outfit_reservations_' + field), table, [field])


def downgrade():
    for table in ('outfit_reservations', 'outfit_plan_revisions', 'outfit_plans',
                  'outfit_recommendation_requests', 'outfit_recommendations'):
        op.drop_table(table)
