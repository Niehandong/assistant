"""异步数据库：引擎/会话工厂、ORM 基类与审计字段 Mixin、get_db 依赖。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, false, func, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from platform_common.config import BaseServiceSettings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类；各服务通过 ``__table_args__ = {"schema": "<服务名>"}`` 隔离 schema。"""


class AuditMixin:
    """所有表的通用字段（总体方案 4.3）。"""

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), default=0, nullable=False)
    updated_by: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False, nullable=False)


class VersionMixin:
    """乐观锁版本号；更新时由 service 层校验并 +1。"""

    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1, nullable=False)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: BaseServiceSettings) -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
        connect_args={"server_settings": {"timezone": settings.TIMEZONE}},
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def init_db(settings: BaseServiceSettings) -> AsyncEngine:
    """初始化进程内单例引擎与会话工厂（幂等）。"""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(settings)
        _session_factory = session_factory(_engine)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_db(settings)")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_db(settings)")
    return _session_factory


async def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每请求一个 AsyncSession；提交由 service 层控制，未提交的事务在退出时回滚。"""
    async with get_session_factory()() as session:
        yield session
