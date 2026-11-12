"""知识库日常访问 ACL（tech-design-m2 3.1）。

全部基于实时 AuthContext（user_id / org_id / company_id / org_path），不依赖只读副本，因此调岗后立即生效。
超级管理员**不**因身份获得日常访问；唯一例外是删除（``allow_super_admin=True``，仅 DELETE 使用）。

供其他任务复用：

* ``accessible_dataset_ids_subquery(ctx)``：可访问（所有者 + 被分配）的未删除知识库 id 子查询。
* ``assignment_match(ctx)``：作用于 ``DatasetAssignment`` 的"当前用户命中该分配"条件。
* ``await get_permission_level(session, ctx, dataset_id) -> "owner" | "edit" | "read" | None``。
* ``await require_dataset(session, ctx, dataset_id, need) -> Dataset``：不可访问 404000，级别不足 403311。
* ``await resolve_dataset(...) -> (Dataset, level)``：同上，同时返回当前用户的级别。
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, DatasetAssignment
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors

Level = Literal["owner", "edit", "read"]
Need = Literal["read", "edit", "owner"]

ERR_LEVEL_DENIED = (403311, "您对该知识库没有此操作权限")
_RANK: dict[str, int] = {"read": 1, "edit": 2, "owner": 3}


def level_satisfies(level: Level, need: Need) -> bool:
    return _RANK[level] >= _RANK[need]


def assignment_match(ctx: AuthContext) -> ColumnElement[bool]:
    """分配记录是否命中当前用户（不含 is_deleted 与 dataset_id 条件）。

    * 个人：target_id = 用户 id；
    * 部门：不含下级 → 等于用户主组织；含下级 → 在用户组织链（org_path，含自身）中；
    * 公司：不含下属 → 等于用户所属公司；含下属 → 在用户组织链中。
    """
    a = DatasetAssignment
    path = list(ctx.org_path) or [ctx.org_id]
    return or_(
        and_(a.target_type == "user", a.target_id == ctx.user_id),
        and_(
            a.target_type == "dept",
            or_(
                and_(a.include_children.is_(False), a.target_id == ctx.org_id),
                and_(a.include_children.is_(True), a.target_id.in_(path)),
            ),
        ),
        and_(
            a.target_type == "company",
            or_(
                and_(a.include_children.is_(False), a.target_id == ctx.company_id),
                and_(a.include_children.is_(True), a.target_id.in_(path)),
            ),
        ),
    )


def _assigned_dataset_ids(ctx: AuthContext, *, edit_only: bool = False) -> Select[tuple[int]]:
    a = DatasetAssignment
    stmt = select(a.dataset_id).where(a.is_deleted.is_(False), assignment_match(ctx))
    if edit_only:
        stmt = stmt.where(a.permission == "edit")
    return stmt


def accessible_dataset_ids_subquery(ctx: AuthContext) -> Select[tuple[int]]:
    """所有者 + 匹配分配的未删除知识库 id。"""
    return select(Dataset.id).where(
        Dataset.is_deleted.is_(False),
        or_(Dataset.owner_id == ctx.user_id, Dataset.id.in_(_assigned_dataset_ids(ctx))),
    )


def edit_dataset_ids_subquery(ctx: AuthContext) -> Select[tuple[int]]:
    """通过"可编辑"分配获得编辑权的知识库 id（不含所有者身份）。"""
    return _assigned_dataset_ids(ctx, edit_only=True)


async def _level_for(session: AsyncSession, ctx: AuthContext, dataset: Dataset) -> Level | None:
    if dataset.owner_id == ctx.user_id:
        return "owner"
    perms = (
        (
            await session.execute(
                select(DatasetAssignment.permission).where(
                    DatasetAssignment.dataset_id == dataset.id,
                    DatasetAssignment.is_deleted.is_(False),
                    assignment_match(ctx),
                )
            )
        )
        .scalars()
        .all()
    )
    if "edit" in perms:
        return "edit"
    return "read" if perms else None


async def get_permission_level(session: AsyncSession, ctx: AuthContext, dataset_id: int) -> Level | None:
    """当前用户对知识库的最高级别（owner > edit > read）；不存在、已删除或无访问权 → None。"""
    dataset = (
        await session.execute(select(Dataset).where(Dataset.id == dataset_id, Dataset.is_deleted.is_(False)))
    ).scalar_one_or_none()
    if dataset is None:
        return None
    return await _level_for(session, ctx, dataset)


async def resolve_dataset(
    session: AsyncSession,
    ctx: AuthContext,
    dataset_id: int,
    need: Need,
    *,
    for_update: bool = False,
    allow_super_admin: bool = False,
) -> tuple[Dataset, Level]:
    """加载知识库并校验级别。``for_update`` 锁行（写操作在事务内重新校验，防并发转移/删除）。
    ``allow_super_admin`` 仅删除接口使用：超管视同所有者。"""
    stmt = select(Dataset).where(Dataset.id == dataset_id, Dataset.is_deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update()
    dataset = (await session.execute(stmt)).scalar_one_or_none()
    if dataset is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    level = await _level_for(session, ctx, dataset)
    if level is None and allow_super_admin and ctx.is_super_admin:
        level = "owner"
    if level is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    if not level_satisfies(level, need):
        raise BizError(*ERR_LEVEL_DENIED)
    return dataset, level


async def require_dataset(
    session: AsyncSession,
    ctx: AuthContext,
    dataset_id: int,
    need: Need,
    *,
    for_update: bool = False,
    allow_super_admin: bool = False,
) -> Dataset:
    dataset, _ = await resolve_dataset(
        session, ctx, dataset_id, need, for_update=for_update, allow_super_admin=allow_super_admin
    )
    return dataset
