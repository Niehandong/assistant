-- 本地开发初始化：仅在数据卷首次创建时执行
SELECT 'CREATE DATABASE kbp_test OWNER kbp'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'kbp_test')\gexec

\connect kbp
CREATE EXTENSION IF NOT EXISTS vector;

\connect kbp_test
CREATE EXTENSION IF NOT EXISTS vector;
