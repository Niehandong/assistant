"""init_kb

Revision ID: 0001
Revises: 
Create Date: 2026-11-11 16:18:40.109921
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.halfvec
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS kb')
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('ai_model',
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('model_type', sa.String(length=16), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('api_key_encrypted', sa.Text(), nullable=True),
    sa.Column('api_key_hint', sa.String(length=16), nullable=True),
    sa.Column('dimension', sa.Integer(), nullable=True),
    sa.Column('max_input_tokens', sa.Integer(), server_default=sa.text('512'), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='disabled', nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('last_test_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_test_ok', sa.Boolean(), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('uq_ai_model_default', 'ai_model', ['model_type'], unique=True, schema='kb', postgresql_where=sa.text('is_default AND is_deleted = false'))
    op.create_index('uq_ai_model_name', 'ai_model', ['name'], unique=True, schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('child_chunk',
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('segment_id', sa.BigInteger(), nullable=False),
    sa.Column('generation', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('pending_content', sa.Text(), nullable=True),
    sa.Column('char_count', sa.Integer(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('edited', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('index_status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('index_error', sa.String(length=300), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.halfvec.HALFVEC(), nullable=True),
    sa.Column('tsv', postgresql.TSVECTOR(), nullable=True),
    sa.Column('search_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_child_chunk_document_id', 'child_chunk', ['document_id'], unique=False, schema='kb')
    op.create_index('ix_child_chunk_segment_gen_pos', 'child_chunk', ['segment_id', 'generation', 'position'], unique=False, schema='kb')
    op.create_index('ix_child_chunk_tsv', 'child_chunk', ['tsv'], unique=False, schema='kb', postgresql_using='gin', postgresql_where=sa.text('search_enabled'))
    op.create_index('ix_child_search', 'child_chunk', ['dataset_id'], unique=False, schema='kb', postgresql_where=sa.text('search_enabled'))
    op.create_table('dataset',
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=400), nullable=True),
    sa.Column('icon', sa.String(length=50), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.BigInteger(), nullable=False),
    sa.Column('dept_id', sa.BigInteger(), nullable=False),
    sa.Column('embedding_model_id', sa.BigInteger(), nullable=False),
    sa.Column('chunk_mode', sa.String(length=16), nullable=True),
    sa.Column('indexing_technique', sa.String(length=16), server_default='high_quality', nullable=False),
    sa.Column('retrieval_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text('\'{"search_method": "vector", "top_k": 3, "score_threshold_enabled": false, "score_threshold": 0.5, "reranking_enable": false, "reranking_model_id": null, "hybrid_mode": "weighted", "vector_weight": 0.7}\'::jsonb'), nullable=False),
    sa.Column('last_process_rule', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('doc_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('processing_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('failed_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('available_doc_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('segment_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('child_segment_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('char_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_dataset_company_id', 'dataset', ['company_id'], unique=False, schema='kb')
    op.create_index('ix_dataset_dept_id', 'dataset', ['dept_id'], unique=False, schema='kb')
    op.create_index('ix_dataset_embedding_model_id', 'dataset', ['embedding_model_id'], unique=False, schema='kb')
    op.create_index('ix_dataset_owner_id', 'dataset', ['owner_id'], unique=False, schema='kb')
    op.create_index('ix_dataset_updated', 'dataset', [sa.literal_column('updated_at DESC')], unique=False, schema='kb')
    op.create_index('uq_dataset_owner_name', 'dataset', ['owner_id', 'name'], unique=True, schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('dataset_assignment',
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('target_type', sa.String(length=16), nullable=False),
    sa.Column('target_id', sa.BigInteger(), nullable=False),
    sa.Column('include_children', sa.Boolean(), nullable=False),
    sa.Column('permission', sa.String(length=8), server_default='read', nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_dataset_assignment_dataset_id', 'dataset_assignment', ['dataset_id'], unique=False, schema='kb')
    op.create_index('ix_dataset_assignment_target', 'dataset_assignment', ['target_type', 'target_id'], unique=False, schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('uq_dataset_assignment_target', 'dataset_assignment', ['dataset_id', 'target_type', 'target_id'], unique=True, schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('document',
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('upload_file_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('file_ext', sa.String(length=10), nullable=False),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('file_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=300), nullable=False),
    sa.Column('parsed_key', sa.String(length=300), nullable=True),
    sa.Column('chunk_mode', sa.String(length=16), nullable=False),
    sa.Column('process_rule', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
    sa.Column('failed_stage', sa.String(length=8), nullable=True),
    sa.Column('error_code', sa.String(length=32), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('progress_done', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('progress_total', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('progress_updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('process_attempt', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('char_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('segment_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('child_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('hit_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_document_dataset_created', 'document', ['dataset_id', sa.literal_column('created_at DESC')], unique=False, schema='kb')
    op.create_index('ix_document_dataset_status', 'document', ['dataset_id', 'status'], unique=False, schema='kb')
    op.create_index('uq_document_dataset_hash', 'document', ['dataset_id', 'file_hash'], unique=True, schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('uq_document_upload_file_id', 'document', ['upload_file_id'], unique=True, schema='kb')
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
    schema='kb'
    )
    op.create_index('ix_org_ref_company_id', 'org_ref', ['company_id'], unique=False, schema='kb')
    op.create_index('ix_org_ref_parent_id', 'org_ref', ['parent_id'], unique=False, schema='kb')
    op.create_table('retrieval_record',
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('query', sa.String(length=500), nullable=False),
    sa.Column('retrieval_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_retrieval_record_user', 'retrieval_record', ['dataset_id', 'created_by', sa.literal_column('created_at DESC')], unique=False, schema='kb')
    op.create_table('segment',
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('segment_type', sa.String(length=8), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('pending_content', sa.Text(), nullable=True),
    sa.Column('keywords', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('pending_keywords', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('char_count', sa.Integer(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('edited', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('hit_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('index_status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('index_error', sa.String(length=300), nullable=True),
    sa.Column('child_generation', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.halfvec.HALFVEC(), nullable=True),
    sa.Column('tsv', postgresql.TSVECTOR(), nullable=True),
    sa.Column('search_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_seg_search', 'segment', ['dataset_id'], unique=False, schema='kb', postgresql_where=sa.text('search_enabled'))
    op.create_index('ix_segment_document_position', 'segment', ['document_id', 'position'], unique=False, schema='kb')
    op.create_index('ix_segment_tsv', 'segment', ['tsv'], unique=False, schema='kb', postgresql_using='gin', postgresql_where=sa.text('search_enabled'))
    op.create_table('upload_file',
    sa.Column('dataset_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('file_ext', sa.String(length=10), nullable=False),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('file_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=300), nullable=False),
    sa.Column('parsed_key', sa.String(length=300), nullable=True),
    sa.Column('doc_token_count', sa.Integer(), nullable=True),
    sa.Column('consumed_document_id', sa.BigInteger(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_by', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='kb'
    )
    op.create_index('ix_upload_file_dataset_id', 'upload_file', ['dataset_id'], unique=False, schema='kb')
    op.create_index('ix_upload_file_expires_at', 'upload_file', ['expires_at'], unique=False, schema='kb')
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
    schema='kb'
    )
    op.create_index('ix_user_ref_company_id', 'user_ref', ['company_id'], unique=False, schema='kb')
    op.create_index('ix_user_ref_name', 'user_ref', ['name'], unique=False, schema='kb')
    op.create_index('ix_user_ref_org_id', 'user_ref', ['org_id'], unique=False, schema='kb')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_user_ref_org_id', table_name='user_ref', schema='kb')
    op.drop_index('ix_user_ref_name', table_name='user_ref', schema='kb')
    op.drop_index('ix_user_ref_company_id', table_name='user_ref', schema='kb')
    op.drop_table('user_ref', schema='kb')
    op.drop_index('ix_upload_file_expires_at', table_name='upload_file', schema='kb')
    op.drop_index('ix_upload_file_dataset_id', table_name='upload_file', schema='kb')
    op.drop_table('upload_file', schema='kb')
    op.drop_index('ix_segment_tsv', table_name='segment', schema='kb', postgresql_using='gin', postgresql_where=sa.text('search_enabled'))
    op.drop_index('ix_segment_document_position', table_name='segment', schema='kb')
    op.drop_index('ix_seg_search', table_name='segment', schema='kb', postgresql_where=sa.text('search_enabled'))
    op.drop_table('segment', schema='kb')
    op.drop_index('ix_retrieval_record_user', table_name='retrieval_record', schema='kb')
    op.drop_table('retrieval_record', schema='kb')
    op.drop_index('ix_org_ref_parent_id', table_name='org_ref', schema='kb')
    op.drop_index('ix_org_ref_company_id', table_name='org_ref', schema='kb')
    op.drop_table('org_ref', schema='kb')
    op.drop_index('uq_document_upload_file_id', table_name='document', schema='kb')
    op.drop_index('uq_document_dataset_hash', table_name='document', schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_document_dataset_status', table_name='document', schema='kb')
    op.drop_index('ix_document_dataset_created', table_name='document', schema='kb')
    op.drop_table('document', schema='kb')
    op.drop_index('uq_dataset_assignment_target', table_name='dataset_assignment', schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_dataset_assignment_target', table_name='dataset_assignment', schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_dataset_assignment_dataset_id', table_name='dataset_assignment', schema='kb')
    op.drop_table('dataset_assignment', schema='kb')
    op.drop_index('uq_dataset_owner_name', table_name='dataset', schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_dataset_updated', table_name='dataset', schema='kb')
    op.drop_index('ix_dataset_owner_id', table_name='dataset', schema='kb')
    op.drop_index('ix_dataset_embedding_model_id', table_name='dataset', schema='kb')
    op.drop_index('ix_dataset_dept_id', table_name='dataset', schema='kb')
    op.drop_index('ix_dataset_company_id', table_name='dataset', schema='kb')
    op.drop_table('dataset', schema='kb')
    op.drop_index('ix_child_search', table_name='child_chunk', schema='kb', postgresql_where=sa.text('search_enabled'))
    op.drop_index('ix_child_chunk_tsv', table_name='child_chunk', schema='kb', postgresql_using='gin', postgresql_where=sa.text('search_enabled'))
    op.drop_index('ix_child_chunk_segment_gen_pos', table_name='child_chunk', schema='kb')
    op.drop_index('ix_child_chunk_document_id', table_name='child_chunk', schema='kb')
    op.drop_table('child_chunk', schema='kb')
    op.drop_index('uq_ai_model_name', table_name='ai_model', schema='kb', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('uq_ai_model_default', table_name='ai_model', schema='kb', postgresql_where=sa.text('is_default AND is_deleted = false'))
    op.drop_table('ai_model', schema='kb')
    # ### end Alembic commands ###
