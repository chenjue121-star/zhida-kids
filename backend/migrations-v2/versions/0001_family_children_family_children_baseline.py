"""family children baseline

Revision ID: 0001_family_children
Revises:
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001_family_children'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('openid', sa.String(length=128), nullable=False),
    sa.Column('nickname', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('openid', name=op.f('uq_users_openid'))
    )
    op.create_table('families',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('city', sa.String(length=120), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_families_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_families'))
    )
    op.create_table('mutation_receipts',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('actor_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('operation', sa.String(length=160), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_body', sa.JSON(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_mutation_receipts_actor_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mutation_receipts')),
    sa.UniqueConstraint('actor_id', 'operation', 'idempotency_key', name=op.f('uq_mutation_receipts_actor_id'))
    )
    op.create_table('children',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('nickname', sa.String(length=80), nullable=False),
    sa.Column('birthday', sa.Date(), nullable=False),
    sa.Column('skin_tone', sa.String(length=16), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_children_family_id_families')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_children'))
    )
    op.create_index(op.f('ix_children_family_id'), 'children', ['family_id'], unique=False)
    op.create_table('invitations',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('accepted_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('accepted_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.CheckConstraint("role IN ('editor','viewer')", name=op.f('ck_invitations_role')),
    sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], name=op.f('fk_invitations_accepted_by_users')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_invitations_created_by_users')),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_invitations_family_id_families')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invitations')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invitations_token_hash'))
    )
    op.create_index(op.f('ix_invitations_family_id'), 'invitations', ['family_id'], unique=False)
    op.create_table('memberships',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('joined_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("role IN ('admin','editor','viewer')", name=op.f('ck_memberships_role')),
    sa.CheckConstraint("status IN ('active','removed')", name=op.f('ck_memberships_status')),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_memberships_family_id_families')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships')),
    sa.UniqueConstraint('family_id', 'user_id', name=op.f('uq_memberships_family_id'))
    )
    op.create_index(op.f('ix_memberships_family_id'), 'memberships', ['family_id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)
    op.create_table('child_measurements',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('child_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('height_cm', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('weight_kg', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('measured_on', sa.Date(), nullable=False),
    sa.CheckConstraint('height_cm IS NOT NULL OR weight_kg IS NOT NULL', name=op.f('ck_child_measurements_has_value')),
    sa.CheckConstraint('height_cm IS NULL OR height_cm > 0', name=op.f('ck_child_measurements_positive_height')),
    sa.CheckConstraint('weight_kg IS NULL OR weight_kg > 0', name=op.f('ck_child_measurements_positive_weight')),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], name=op.f('fk_child_measurements_child_id_children')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_child_measurements'))
    )
    op.create_index(op.f('ix_child_measurements_child_id'), 'child_measurements', ['child_id'], unique=False)
    op.create_table('child_preference_settings',
    sa.Column('child_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('mode', sa.String(length=24), nullable=False),
    sa.Column('designated_member_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('thermal_preference', sa.String(length=16), nullable=False),
    sa.Column('fit_preference', sa.String(length=16), nullable=False),
    sa.Column('avoid_high_neck', sa.Boolean(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("(mode = 'designated_member' AND designated_member_id IS NOT NULL) OR (mode IN ('family','current_member') AND designated_member_id IS NULL)", name=op.f('ck_child_preference_settings_mode_member')),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], name=op.f('fk_child_preference_settings_child_id_children')),
    sa.ForeignKeyConstraint(['designated_member_id'], ['memberships.id'], name=op.f('fk_child_preference_settings_designated_member_id_memberships')),
    sa.PrimaryKeyConstraint('child_id', name=op.f('pk_child_preference_settings'))
    )
    op.create_table('preference_profiles',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('child_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('owner_key', sa.String(length=64), nullable=False),
    sa.Column('membership_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('styles', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], name=op.f('fk_preference_profiles_child_id_children')),
    sa.ForeignKeyConstraint(['membership_id'], ['memberships.id'], name=op.f('fk_preference_profiles_membership_id_memberships')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_preference_profiles')),
    sa.UniqueConstraint('child_id', 'owner_key', name=op.f('uq_preference_profiles_child_id'))
    )
    op.create_index(op.f('ix_preference_profiles_child_id'), 'preference_profiles', ['child_id'], unique=False)


def downgrade() -> None:
    # Dropping a table also drops its indexes; MySQL retains FK indexes until then.
    op.drop_table('preference_profiles')
    op.drop_table('child_preference_settings')
    op.drop_table('child_measurements')
    op.drop_table('memberships')
    op.drop_table('invitations')
    op.drop_table('children')
    op.drop_table('mutation_receipts')
    op.drop_table('families')
    op.drop_table('users')
