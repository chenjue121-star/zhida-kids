"""Age-only child setup and optional family location.

Revision ID: 0002_simplified_onboarding
Revises: 0001_family_children
"""

from alembic import op
import sqlalchemy as sa

revision = '0002_simplified_onboarding'
down_revision = '0001_family_children'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('families') as batch:
        batch.alter_column('city', existing_type=sa.String(length=120), nullable=True)
        batch.add_column(sa.Column('personal_owner_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite')))
        batch.create_unique_constraint('uq_families_personal_owner_id', ['personal_owner_id'])
        batch.create_foreign_key('fk_families_personal_owner_id_users', 'users', ['personal_owner_id'], ['id'])
    with op.batch_alter_table('children') as batch:
        batch.alter_column('birthday', existing_type=sa.Date(), nullable=True)
        batch.add_column(sa.Column('age_months', sa.Integer()))
        batch.add_column(sa.Column('age_recorded_on', sa.Date()))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT COUNT(*) FROM children WHERE birthday IS NULL')).scalar_one():
        raise RuntimeError('Cannot downgrade while age-only child records exist')
    if connection.execute(sa.text('SELECT COUNT(*) FROM families WHERE city IS NULL')).scalar_one():
        raise RuntimeError('Cannot downgrade while families without a city exist')
    with op.batch_alter_table('children') as batch:
        batch.drop_column('age_recorded_on')
        batch.drop_column('age_months')
        batch.alter_column('birthday', existing_type=sa.Date(), nullable=False)
    with op.batch_alter_table('families') as batch:
        batch.drop_constraint('fk_families_personal_owner_id_users', type_='foreignkey')
        batch.drop_constraint('uq_families_personal_owner_id', type_='unique')
        batch.drop_column('personal_owner_id')
        batch.alter_column('city', existing_type=sa.String(length=120), nullable=False)
