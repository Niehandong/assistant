"""init_open

Revision ID: 0001
Revises: 
Create Date: 2026-11-12 21:08:30.709809
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table('api_call_log',
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('api_key_id', sa.BigInteger(), nullable=True),
    sa.Column('key_name', sa.String(length=50), nullable=True),
    sa.Column('key_prefix', sa.String(length=16), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=True),
    sa.Column('dept_id', sa.BigInteger(), nullable=True),
    sa.Column('dataset_id', sa.BigInteger(), nullable=True),
    sa.Column('dataset_name', sa.String(length=50), nullable=True),
    sa.Column('query', sa.Text(), nullable=True),
    sa.Column('result_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('result', sa.String(length=32), nullable=False),
    sa.Column('error_code', sa.Integer(), nullable=True),
    sa.Column('client_ip', sa.String(length=64), nullable=True),
    sa.Column('called_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_id'),
    schema='open'
    )
    op.create_index('ix_call_log_called_at', 'api_call_log', ['called_at'], unique=False, schema='open')
    op.create_index('ix_call_log_company_called', 'api_call_log', ['company_id', sa.literal_column('called_at DESC')], unique=False, schema='open')
    op.create_index('ix_call_log_dept_id', 'api_call_log', ['dept_id'], unique=False, schema='open')
    op.create_index('ix_call_log_key_called', 'api_call_log', ['api_key_id', sa.literal_column('called_at DESC')], unique=False, schema='open')
    op.create_index('ix_call_log_owner_called', 'api_call_log', ['created_by', sa.literal_column('called_at DESC')], unique=False, schema='open')
    op.create_table('api_key',
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=200), nullable=True),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('scope_type', sa.String(length=16), server_default='all', nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_whitelist', postgresql.ARRAY(sa.TEXT()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('rate_limit_per_min', sa.Integer(), server_default=sa.text('60'), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='enabled', nullable=False),
    sa.Column('admin_disabled_by', sa.BigInteger(), nullable=True),
    sa.Column('admin_disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('dept_id', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash'),
    schema='open'
    )
    op.create_index('ix_api_key_company_id', 'api_key', ['company_id'], unique=False, schema='open')
    op.create_index('ix_api_key_created_by', 'api_key', ['created_by'], unique=False, schema='open', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_api_key_dept_id', 'api_key', ['dept_id'], unique=False, schema='open')
    op.create_index('uq_api_key_owner_name', 'api_key', ['created_by', 'name'], unique=True, schema='open', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('api_key_dataset',
    sa.Column('api_key_id', sa.BigInteger(), nullable=False),
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='open'
    )
    op.create_index('uq_api_key_dataset', 'api_key_dataset', ['api_key_id', 'dataset_id'], unique=True, schema='open')
    op.create_table('org_ref',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=False),
    sa.Column('ancestors', sa.String(length=1000), nullable=False),
    sa.Column('org_type', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='open'
    )
    op.create_index('ix_org_ref_company_id', 'org_ref', ['company_id'], unique=False, schema='open')
    op.create_index('ix_org_ref_parent_id', 'org_ref', ['parent_id'], unique=False, schema='open')
    op.create_table('user_ref',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='open'
    )
    op.create_index('ix_user_ref_company_id', 'user_ref', ['company_id'], unique=False, schema='open')
    op.create_index('ix_user_ref_name', 'user_ref', ['name'], unique=False, schema='open')
    op.create_index('ix_user_ref_org_id', 'user_ref', ['org_id'], unique=False, schema='open')



def downgrade() -> None:

    op.drop_index('ix_user_ref_org_id', table_name='user_ref', schema='open')
    op.drop_index('ix_user_ref_name', table_name='user_ref', schema='open')
    op.drop_index('ix_user_ref_company_id', table_name='user_ref', schema='open')
    op.drop_table('user_ref', schema='open')
    op.drop_index('ix_org_ref_parent_id', table_name='org_ref', schema='open')
    op.drop_index('ix_org_ref_company_id', table_name='org_ref', schema='open')
    op.drop_table('org_ref', schema='open')
    op.drop_index('uq_api_key_dataset', table_name='api_key_dataset', schema='open')
    op.drop_table('api_key_dataset', schema='open')
    op.drop_index('uq_api_key_owner_name', table_name='api_key', schema='open', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_api_key_dept_id', table_name='api_key', schema='open')
    op.drop_index('ix_api_key_created_by', table_name='api_key', schema='open', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_api_key_company_id', table_name='api_key', schema='open')
    op.drop_table('api_key', schema='open')
    op.drop_index('ix_call_log_owner_called', table_name='api_call_log', schema='open')
    op.drop_index('ix_call_log_key_called', table_name='api_call_log', schema='open')
    op.drop_index('ix_call_log_dept_id', table_name='api_call_log', schema='open')
    op.drop_index('ix_call_log_company_called', table_name='api_call_log', schema='open')
    op.drop_index('ix_call_log_called_at', table_name='api_call_log', schema='open')
    op.drop_table('api_call_log', schema='open')

