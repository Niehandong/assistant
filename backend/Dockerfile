# 后端生产镜像（iam / kb / open 共用，按 SERVICE 构建；kb-worker 使用 kb 镜像并覆盖 command）
# 构建（上下文为 backend/）：docker build --build-arg SERVICE=iam -t kbp-iam:<ver> backend
# 运行：监听地址、端口、数据库等全部由环境变量注入（见 deploy/.env.prod.example），镜像内不含任何密钥。

# ---------- 构建阶段：安装依赖到独立 venv ----------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY libs/platform_common ./libs/platform_common
RUN pip install ./libs/platform_common

# ---------- 运行阶段 ----------
FROM python:3.12-slim
ARG SERVICE
RUN test -n "${SERVICE}" || (echo "必须指定 --build-arg SERVICE=iam|kb|open" >&2; exit 1)
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE=${SERVICE} \
    HOST=0.0.0.0

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app services/${SERVICE} /app
WORKDIR /app
USER app

# 端口取各服务配置默认值（iam 8301 / kb 8302 / open 8303），PORT 环境变量覆盖时同样生效；kb-worker 在编排中关闭该检查
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; from app.core.config import get_settings as g; u.urlopen(f'http://127.0.0.1:{g().PORT}/healthz', timeout=3)"]

CMD ["python", "main.py"]
