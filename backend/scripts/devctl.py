#!/usr/bin/env python
"""本地开发控制脚本（标准库 + cryptography）。

用法（仓库根目录）::

    .venv/bin/python backend/scripts/devctl.py init
    .venv/bin/python backend/scripts/devctl.py migrate [svc...]
    .venv/bin/python backend/scripts/devctl.py up [-d] [svc...]
    .venv/bin/python backend/scripts/devctl.py down [svc...]
    .venv/bin/python backend/scripts/devctl.py status
    .venv/bin/python backend/scripts/devctl.py --env test migrate|up
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
SERVICES_DIR = BACKEND / "services"
SECRETS_DIR = BACKEND / ".secrets"
RUN_DIR = REPO / ".run"
LOG_DIR = REPO / "logs"
PYTHON = REPO / ".venv" / "bin" / "python"
ALEMBIC = REPO / ".venv" / "bin" / "alembic"


@dataclass(frozen=True)
class Service:
    name: str
    directory: str  # services/ 下的目录名
    entry: str  # 入口脚本
    port: int | None  # 无端口服务为 None


SERVICES: dict[str, Service] = {
    "iam": Service("iam", "iam", "main.py", 8301),
    "kb": Service("kb", "kb", "main.py", 8302),
    "kb-worker": Service("kb-worker", "kb", "worker.py", None),
    "open": Service("open", "open", "main.py", 8303),
}
MIGRATE_ORDER = ["iam", "kb", "open"]

TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://kbp:kbp@localhost:15432/kbp_test",
    "REDIS_URL": "redis://localhost:16379/1",
    "S3_BUCKET": "kbp-test",
    "APP_ENV": "test",
}


def svc_dir(svc: Service) -> Path:
    return SERVICES_DIR / svc.directory


def svc_exists(svc: Service) -> bool:
    return (svc_dir(svc) / svc.entry).is_file()


def select_services(names: list[str]) -> list[Service]:
    """解析 svc 参数；为空则取全部已存在的服务。"""
    if not names:
        return [s for s in SERVICES.values() if svc_exists(s)]
    unknown = [n for n in names if n not in SERVICES]
    if unknown:
        sys.exit(f"未知服务: {', '.join(unknown)}（可选: {' '.join(SERVICES)}）")
    return [SERVICES[n] for n in names]


def child_env(env_name: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if env_name == "test":
        env.update(TEST_ENV)
    return env


# ---------------------------------------------------------------- init
BUCKETS = ["kbp-files", "kbp-test"]


def ensure_buckets() -> int:
    """幂等创建本地 MinIO 桶（连接参数可用 S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY 覆盖）。"""
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:19000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
    )
    try:
        existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
        for name in BUCKETS:
            if name in existing:
                print(f"桶已存在: {name}")
            else:
                client.create_bucket(Bucket=name)
                print(f"已创建桶: {name}")
    except (BotoCoreError, ClientError) as exc:
        print(f"创建桶失败（请先 docker compose up -d）: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_init(_: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_path = SECRETS_DIR / "jwt_private.pem"
    public_path = SECRETS_DIR / "jwt_public.pem"
    if private_path.exists():
        print(f"已存在，跳过密钥生成: {private_path}")
        return ensure_buckets()
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"已生成 JWT 密钥对: {SECRETS_DIR}")
    return ensure_buckets()


# ---------------------------------------------------------------- migrate
def cmd_migrate(args: argparse.Namespace) -> int:
    names = args.svc or MIGRATE_ORDER
    bad = [n for n in names if n not in MIGRATE_ORDER]
    if bad:
        sys.exit(f"不支持迁移的服务: {', '.join(bad)}（可选: {' '.join(MIGRATE_ORDER)}）")
    env = child_env(args.env)
    for name in sorted(names, key=MIGRATE_ORDER.index):
        cwd = SERVICES_DIR / name
        if not (cwd / "alembic.ini").is_file():
            print(f"[{name}] 不存在，跳过")
            continue
        print(f"[{name}] alembic upgrade head")
        if subprocess.run([str(ALEMBIC), "upgrade", "head"], cwd=cwd, env=env).returncode != 0:
            return 1
        if name == "iam":
            print("[iam] seed")
            if subprocess.run([str(PYTHON), "-m", "app.seed"], cwd=cwd, env=env).returncode != 0:
                return 1
    return 0


# ---------------------------------------------------------------- up
def pid_file(name: str) -> Path:
    return RUN_DIR / f"{name}.pid"


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(name: str) -> int | None:
    path = pid_file(name)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text().strip())
    except ValueError:
        return None
    return pid if is_alive(pid) else None


def start_detached(svc: Service, env: dict[str, str]) -> None:
    if (pid := read_pid(svc.name)) is not None:
        print(f"[{svc.name}] 已在运行 (pid={pid})，跳过")
        return
    RUN_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / f"{svc.name}.log", "ab") as log:
        proc = subprocess.Popen(
            [str(PYTHON), svc.entry],
            cwd=svc_dir(svc),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    pid_file(svc.name).write_text(str(proc.pid))
    print(f"[{svc.name}] 已后台启动 pid={proc.pid} 日志={LOG_DIR / (svc.name + '.log')}")


async def _pump(name: str, stream: asyncio.StreamReader) -> None:
    prefix = f"[{name}] "
    while line := await stream.readline():
        sys.stdout.write(prefix + line.decode(errors="replace"))
        sys.stdout.flush()


async def run_foreground(services: list[Service], env: dict[str, str]) -> int:
    procs: list[tuple[Service, asyncio.subprocess.Process]] = []
    for svc in services:
        proc = await asyncio.create_subprocess_exec(
            str(PYTHON),
            svc.entry,
            cwd=svc_dir(svc),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        procs.append((svc, proc))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    pumps = [asyncio.create_task(_pump(s.name, p.stdout)) for s, p in procs if p.stdout]
    waiters = [asyncio.create_task(p.wait()) for _, p in procs]
    stopper = asyncio.create_task(stop.wait())
    # 任一子进程退出或收到信号即整体收尾
    await asyncio.wait([stopper, *waiters], return_when=asyncio.FIRST_COMPLETED)
    for _, proc in procs:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(asyncio.gather(*waiters), timeout=10)
    except TimeoutError:
        for _, proc in procs:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
        await asyncio.gather(*waiters)
    await asyncio.gather(*pumps, return_exceptions=True)
    stopper.cancel()
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    services = select_services(args.svc)
    missing = [s.name for s in services if not svc_exists(s)]
    if missing:
        sys.exit(f"服务入口不存在: {', '.join(missing)}")
    if not services:
        print("没有可启动的服务（services/ 下尚无入口）")
        return 0
    env = child_env(args.env)
    if args.detach:
        for svc in services:
            start_detached(svc, env)
        return 0
    return asyncio.run(run_foreground(services, env))


# ---------------------------------------------------------------- down
def terminate(pid: int, timeout: float = 10.0) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return
        time.sleep(0.2)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def cmd_down(args: argparse.Namespace) -> int:
    for svc in select_services(args.svc) if args.svc else list(SERVICES.values()):
        pids: list[int] = []
        if (pid := read_pid(svc.name)) is not None:
            pids = [pid]
        if not pids:
            print(f"[{svc.name}] 未运行")
        for pid in pids:
            print(f"[{svc.name}] 停止 pid={pid}")
            terminate(pid)
        pid_file(svc.name).unlink(missing_ok=True)
    return 0


# ---------------------------------------------------------------- status
def healthz(port: int) -> str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:  # noqa: S310
            return f"ok({resp.status})"
    except urllib.error.HTTPError as exc:
        return f"异常({exc.code})"
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return "不可达"


def cmd_status(_: argparse.Namespace) -> int:
    print(f"{'服务':<10}{'状态':<8}{'PID':<9}{'端口':<7}healthz")
    for svc in SERVICES.values():
        pid = read_pid(svc.name)
        state = "运行中" if pid else ("未启动" if svc_exists(svc) else "未实现")
        port = str(svc.port) if svc.port else "-"
        health = healthz(svc.port) if (svc.port and pid) else "-"
        print(f"{svc.name:<10}{state:<8}{pid if pid else '-':<9}{port:<7}{health}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库平台本地开发控制脚本")
    parser.add_argument("--env", choices=["test"], default=None, help="test：使用 kbp_test 库、Redis db 1、桶 kbp-test")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="生成本地 JWT 密钥对").set_defaults(func=cmd_init)
    p = sub.add_parser("migrate", help="执行迁移（iam 之后跑 seed）")
    p.add_argument("svc", nargs="*")
    p.set_defaults(func=cmd_migrate)
    p = sub.add_parser("up", help="启动服务")
    p.add_argument("-d", "--detach", action="store_true", help="后台运行")
    p.add_argument("svc", nargs="*")
    p.set_defaults(func=cmd_up)
    p = sub.add_parser("down", help="停止服务")
    p.add_argument("svc", nargs="*")
    p.set_defaults(func=cmd_down)
    sub.add_parser("status", help="查看状态").set_defaults(func=cmd_status)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
