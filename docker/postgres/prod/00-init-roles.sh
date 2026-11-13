#!/bin/sh
# 生产 PostgreSQL 初始化：仅在数据卷首次创建时由官方镜像执行（/docker-entrypoint-initdb.d）。
# 每个服务一个登录角色，并作为各自 schema 的 owner（kb 账号须为 kb 表 owner，worker 才能运行时 CREATE/DROP INDEX CONCURRENTLY）。
# 密码来自容器环境变量（由 .env.prod 注入）。
set -eu

: "${IAM_DB_PASSWORD:?}" "${KB_DB_PASSWORD:?}" "${OPEN_DB_PASSWORD:?}"

# vector 扩展需要超级用户创建；迁移里的 CREATE EXTENSION IF NOT EXISTS 因已存在而跳过
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v iam_pw="$IAM_DB_PASSWORD" -v kb_pw="$KB_DB_PASSWORD" -v open_pw="$OPEN_DB_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE kbp_iam  LOGIN PASSWORD :'iam_pw';
CREATE ROLE kbp_kb   LOGIN PASSWORD :'kb_pw';
CREATE ROLE kbp_open LOGIN PASSWORD :'open_pw';

-- 迁移环境会执行 CREATE SCHEMA IF NOT EXISTS，该语句要求库级 CREATE 权限（schema 已存在时不会真正创建）
GRANT CONNECT, CREATE ON DATABASE kbp TO kbp_iam, kbp_kb, kbp_open;

CREATE SCHEMA iam  AUTHORIZATION kbp_iam;
CREATE SCHEMA kb   AUTHORIZATION kbp_kb;
CREATE SCHEMA open AUTHORIZATION kbp_open;

-- 各服务账号只能访问自己的 schema（public 上仅保留扩展类型/函数的使用权）
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kbp_iam, kbp_kb, kbp_open;
SQL
