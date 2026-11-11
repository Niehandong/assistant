"""init_iam

Revision ID: 0001
Revises: 
Create Date: 2026-11-11 12:29:04.221805
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
    op.create_table('sys_login_log',
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('company_id', sa.BigInteger(), nullable=True),
    sa.Column('dept_id', sa.BigInteger(), nullable=True),
    sa.Column('result', sa.String(length=16), nullable=False),
    sa.Column('fail_reason', sa.String(length=32), nullable=True),
    sa.Column('fail_message', sa.String(length=200), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('login_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='iam'
    )
    op.create_index('ix_sys_login_log_company_id', 'sys_login_log', ['company_id'], unique=False, schema='iam')
    op.create_index('ix_sys_login_log_dept_id', 'sys_login_log', ['dept_id'], unique=False, schema='iam')
    op.create_index('ix_sys_login_log_login_at', 'sys_login_log', ['login_at'], unique=False, schema='iam')
    op.create_index('ix_sys_login_log_username', 'sys_login_log', ['username'], unique=False, schema='iam')
    op.create_table('sys_operation_log',
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('service', sa.String(length=16), nullable=False),
    sa.Column('operator_id', sa.BigInteger(), nullable=False),
    sa.Column('operator_username', sa.String(length=32), nullable=False),
    sa.Column('operator_name', sa.String(length=30), nullable=False),
    sa.Column('company_id', sa.BigInteger(), nullable=True),
    sa.Column('dept_id', sa.BigInteger(), nullable=True),
    sa.Column('company_name', sa.String(length=50), nullable=True),
    sa.Column('module', sa.String(length=32), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=False),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('target_name', sa.String(length=200), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('result', sa.String(length=16), nullable=False),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id'),
    schema='iam'
    )
    op.create_index('ix_sys_operation_log_company_id', 'sys_operation_log', ['company_id'], unique=False, schema='iam')
    op.create_index('ix_sys_operation_log_dept_id', 'sys_operation_log', ['dept_id'], unique=False, schema='iam')
    op.create_index('ix_sys_operation_log_occurred_at', 'sys_operation_log', ['occurred_at'], unique=False, schema='iam')
    op.create_index('ix_sys_operation_log_operator_id', 'sys_operation_log', ['operator_id'], unique=False, schema='iam')
    op.create_table('sys_org',
    sa.Column('parent_id', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('ancestors', sa.String(length=1000), server_default='0', nullable=False),
    sa.Column('org_type', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('leader_user_id', sa.BigInteger(), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='enabled', nullable=False),
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
    sa.UniqueConstraint('code'),
    schema='iam'
    )
    op.create_index('ix_sys_org_company_id', 'sys_org', ['company_id'], unique=False, schema='iam')
    op.create_index('ix_sys_org_dept_id', 'sys_org', ['dept_id'], unique=False, schema='iam')
    op.create_index('ix_sys_org_parent_id', 'sys_org', ['parent_id'], unique=False, schema='iam')
    op.create_index('ix_sys_org_parent_sort', 'sys_org', ['parent_id', 'sort_order', 'created_at'], unique=False, schema='iam')
    op.create_index('uq_sys_org_group', 'sys_org', ['org_type'], unique=True, schema='iam', postgresql_where=sa.text("org_type = 'group' AND is_deleted = false"))
    op.create_index('uq_sys_org_parent_name', 'sys_org', ['parent_id', 'name'], unique=True, schema='iam', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('sys_permission',
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('perm_type', sa.String(length=16), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('path', sa.String(length=200), nullable=True),
    sa.Column('icon', sa.String(length=50), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('service', sa.String(length=16), nullable=False),
    sa.Column('super_only', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='iam'
    )
    op.create_index('ix_sys_permission_parent_id', 'sys_permission', ['parent_id'], unique=False, schema='iam')
    op.create_table('sys_role',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=30), nullable=False),
    sa.Column('role_type', sa.String(length=16), nullable=False),
    sa.Column('owner_company_id', sa.BigInteger(), nullable=True),
    sa.Column('data_scope', sa.String(length=32), server_default='SELF', nullable=False),
    sa.Column('status', sa.String(length=16), server_default='enabled', nullable=False),
    sa.Column('remark', sa.String(length=200), nullable=True),
    sa.Column('is_builtin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('builtin_key', sa.String(length=32), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('builtin_key'),
    sa.UniqueConstraint('code'),
    schema='iam'
    )
    op.create_index('ix_sys_role_owner_company_id', 'sys_role', ['owner_company_id'], unique=False, schema='iam')
    op.create_index('uq_sys_role_name', 'sys_role', [sa.literal_column('coalesce(owner_company_id, 0)'), 'name'], unique=True, schema='iam', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('sys_role_org',
    sa.Column('role_id', sa.BigInteger(), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('role_id', 'org_id', name='uq_sys_role_org'),
    schema='iam'
    )
    op.create_index('ix_sys_role_org_org_id', 'sys_role_org', ['org_id'], unique=False, schema='iam')
    op.create_table('sys_role_permission',
    sa.Column('role_id', sa.BigInteger(), nullable=False),
    sa.Column('permission_id', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('role_id', 'permission_id', name='uq_sys_role_permission'),
    schema='iam'
    )
    op.create_index('ix_sys_role_permission_permission_id', 'sys_role_permission', ['permission_id'], unique=False, schema='iam')
    op.create_table('sys_user',
    sa.Column('username', sa.String(length=32), nullable=False),
    sa.Column('password_hash', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=30), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('dept_id', sa.BigInteger(), nullable=False),
    sa.Column('mobile', sa.String(length=11), nullable=True),
    sa.Column('email', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='enabled', nullable=False),
    sa.Column('is_builtin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_ip', sa.String(length=64), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username'),
    schema='iam'
    )
    op.create_index('ix_sys_user_company_id', 'sys_user', ['company_id'], unique=False, schema='iam')
    op.create_index('ix_sys_user_dept_id', 'sys_user', ['dept_id'], unique=False, schema='iam')
    op.create_index('ix_sys_user_org_id', 'sys_user', ['org_id'], unique=False, schema='iam')
    op.create_index('uq_sys_user_mobile', 'sys_user', ['mobile'], unique=True, schema='iam', postgresql_where=sa.text('mobile IS NOT NULL AND is_deleted = false'))
    op.create_table('sys_user_role',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('role_id', sa.BigInteger(), nullable=False),
    sa.Column('org_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'role_id', name='uq_sys_user_role'),
    schema='iam'
    )
    op.create_index('ix_sys_user_role_role_id', 'sys_user_role', ['role_id'], unique=False, schema='iam')
    op.create_index('ix_sys_user_role_user_id', 'sys_user_role', ['user_id'], unique=False, schema='iam')
    op.create_table('sys_user_session',
    sa.Column('sid', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('refresh_token_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoke_reason', sa.String(length=32), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('refresh_token_hash'),
    sa.UniqueConstraint('sid'),
    schema='iam'
    )
    op.create_index('ix_sys_user_session_user_id', 'sys_user_session', ['user_id'], unique=False, schema='iam')


def downgrade() -> None:
    # 索引随表删除。不 DROP SCHEMA：alembic_version 版本表位于 iam schema，
    # 删除后 Alembic 无法更新版本记录；schema 本身保留为空。
    op.drop_table('sys_user_session', schema='iam')
    op.drop_table('sys_user_role', schema='iam')
    op.drop_table('sys_user', schema='iam')
    op.drop_table('sys_role_permission', schema='iam')
    op.drop_table('sys_role_org', schema='iam')
    op.drop_table('sys_role', schema='iam')
    op.drop_table('sys_permission', schema='iam')
    op.drop_table('sys_org', schema='iam')
    op.drop_table('sys_operation_log', schema='iam')
    op.drop_table('sys_login_log', schema='iam')
