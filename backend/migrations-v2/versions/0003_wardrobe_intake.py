"""Family physical wardrobe, private assets and durable intake recognition."""
from alembic import op
import sqlalchemy as sa

revision = '0003_wardrobe_intake'
down_revision = '0002_simplified_onboarding'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('media_assets',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('object_key', sa.String(length=240), nullable=False),
    sa.Column('content_type', sa.String(length=40), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_media_assets_family_id_families')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_assets')),
    sa.UniqueConstraint('family_id', 'sha256', name=op.f('uq_media_assets_family_id'))
    )
    op.create_index(op.f('ix_media_assets_family_id'), 'media_assets', ['family_id'], unique=False)
    op.create_table('wardrobe_operations',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('actor_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('scope', sa.String(length=128), nullable=False),
    sa.Column('operation_id', sa.String(length=128), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_wardrobe_operations_actor_id_users')),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_wardrobe_operations_family_id_families')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_wardrobe_operations')),
    sa.UniqueConstraint('family_id', 'actor_id', 'scope', 'operation_id', name=op.f('uq_wardrobe_operations_family_id'))
    )
    op.create_index(op.f('ix_wardrobe_operations_family_id'), 'wardrobe_operations', ['family_id'], unique=False)
    op.create_table('clothing',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('source_candidate_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('colors', sa.JSON(), nullable=False),
    sa.Column('pattern', sa.String(length=20), nullable=False),
    sa.Column('thickness', sa.String(length=20), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('asset_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("state IN ('ready','washing','missing')", name=op.f('ck_clothing_state')),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_clothing_asset_id_media_assets')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_clothing_created_by_users')),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_clothing_family_id_families')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clothing')),
    sa.UniqueConstraint('source_candidate_id', name=op.f('uq_clothing_source_candidate_id'))
    )
    op.create_index(op.f('ix_clothing_family_id'), 'clothing', ['family_id'], unique=False)
    op.create_table('intake_batches',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('family_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('created_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('default_child_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_intake_batches_created_by_users')),
    sa.ForeignKeyConstraint(['default_child_id'], ['children.id'], name=op.f('fk_intake_batches_default_child_id_children')),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], name=op.f('fk_intake_batches_family_id_families')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intake_batches'))
    )
    op.create_index(op.f('ix_intake_batches_created_by'), 'intake_batches', ['created_by'], unique=False)
    op.create_index(op.f('ix_intake_batches_family_id'), 'intake_batches', ['family_id'], unique=False)
    op.create_table('child_clothing',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('clothing_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('child_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('fit', sa.String(length=20), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("fit IN ('small','fit','large','unknown')", name=op.f('ck_child_clothing_fit')),
    sa.ForeignKeyConstraint(['child_id'], ['children.id'], name=op.f('fk_child_clothing_child_id_children')),
    sa.ForeignKeyConstraint(['clothing_id'], ['clothing.id'], name=op.f('fk_child_clothing_clothing_id_clothing')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_child_clothing')),
    sa.UniqueConstraint('clothing_id', 'child_id', name=op.f('uq_child_clothing_clothing_id'))
    )
    op.create_index(op.f('ix_child_clothing_child_id'), 'child_clothing', ['child_id'], unique=False)
    op.create_index(op.f('ix_child_clothing_clothing_id'), 'child_clothing', ['clothing_id'], unique=False)
    op.create_table('clothing_removals',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('clothing_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('removed_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('owners', sa.JSON(), nullable=False),
    sa.Column('removed_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['clothing_id'], ['clothing.id'], name=op.f('fk_clothing_removals_clothing_id_clothing')),
    sa.ForeignKeyConstraint(['removed_by'], ['users.id'], name=op.f('fk_clothing_removals_removed_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clothing_removals'))
    )
    op.create_index(op.f('ix_clothing_removals_clothing_id'), 'clothing_removals', ['clothing_id'], unique=False)
    op.create_table('intake_items',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('batch_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('client_id', sa.String(length=128), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('asset_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('discarded', sa.Boolean(), nullable=False),
    sa.Column('error', sa.JSON(), nullable=True),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_intake_items_asset_id_media_assets')),
    sa.ForeignKeyConstraint(['batch_id'], ['intake_batches.id'], name=op.f('fk_intake_items_batch_id_intake_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intake_items')),
    sa.UniqueConstraint('batch_id', 'client_id', name=op.f('uq_intake_items_batch_id'))
    )
    op.create_index(op.f('ix_intake_items_batch_id'), 'intake_items', ['batch_id'], unique=False)
    op.create_table('recognition_attempts',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('item_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('claim_token', sa.String(length=64), nullable=True),
    sa.Column('lease_until', sa.DateTime(), nullable=True),
    sa.Column('available_at', sa.DateTime(), nullable=False),
    sa.Column('tries', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('error', sa.JSON(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['intake_items.id'], name=op.f('fk_recognition_attempts_item_id_intake_items')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recognition_attempts')),
    sa.UniqueConstraint('item_id', 'generation', name=op.f('uq_recognition_attempts_item_id'))
    )
    op.create_index(op.f('ix_recognition_attempts_available_at'), 'recognition_attempts', ['available_at'], unique=False)
    op.create_index(op.f('ix_recognition_attempts_item_id'), 'recognition_attempts', ['item_id'], unique=False)
    op.create_index(op.f('ix_recognition_attempts_status'), 'recognition_attempts', ['status'], unique=False)
    op.create_table('intake_candidates',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('batch_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('item_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('client_id', sa.String(length=128), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('attempt_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=True),
    sa.Column('colors', sa.JSON(), nullable=False),
    sa.Column('pattern', sa.String(length=20), nullable=False),
    sa.Column('thickness', sa.String(length=20), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('owners', sa.JSON(), nullable=False),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('discarded', sa.Boolean(), nullable=False),
    sa.Column('ownership_exception', sa.Boolean(), nullable=False),
    sa.Column('dirty_fields', sa.JSON(), nullable=False),
    sa.Column('bbox', sa.JSON(), nullable=True),
    sa.Column('confirmed_garment_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('confirmation_kind', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['recognition_attempts.id'], name=op.f('fk_intake_candidates_attempt_id_recognition_attempts')),
    sa.ForeignKeyConstraint(['batch_id'], ['intake_batches.id'], name=op.f('fk_intake_candidates_batch_id_intake_batches')),
    sa.ForeignKeyConstraint(['confirmed_garment_id'], ['clothing.id'], name=op.f('fk_intake_candidates_confirmed_garment_id_clothing')),
    sa.ForeignKeyConstraint(['item_id'], ['intake_items.id'], name=op.f('fk_intake_candidates_item_id_intake_items')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intake_candidates')),
    sa.UniqueConstraint('batch_id', 'client_id', name=op.f('uq_intake_candidates_batch_id'))
    )
    op.create_index(op.f('ix_intake_candidates_batch_id'), 'intake_candidates', ['batch_id'], unique=False)
    op.create_index(op.f('ix_intake_candidates_item_id'), 'intake_candidates', ['item_id'], unique=False)


def downgrade():
    # MySQL FK-supporting indexes are removed with their table, never first.
    op.drop_table('intake_candidates')
    op.drop_table('recognition_attempts')
    op.drop_table('intake_items')
    op.drop_table('clothing_removals')
    op.drop_table('child_clothing')
    op.drop_table('intake_batches')
    op.drop_table('clothing')
    op.drop_table('wardrobe_operations')
    op.drop_table('media_assets')
