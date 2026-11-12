"""知识库分配接口（tech-design-m2 5.3）。路径挂在 ``/kb/datasets/{id}`` 下。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.assignment import (
    AssignableOrgNode,
    AssignableUser,
    AssignmentCreate,
    AssignmentItem,
    AssignmentUpdate,
)
from app.services import assignment_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/kb/datasets/{dataset_id}", tags=["assignments"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:list"))]
AssignCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:assign"))]
CandidateCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:assign", "kb:dataset:transfer", mode="any"))]


@router.get(
    "/assignments",
    summary="分配名单（kb:dataset:list；ACL 可编辑；不分页）",
    response_model=ApiResponse[list[AssignmentItem]],
)
async def list_assignments(dataset_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await assignment_service.list_assignments(session, ctx, dataset_id))


@router.post(
    "/assignments", summary="新增分配（kb:dataset:assign；ACL 所有者）", response_model=ApiResponse[AssignmentItem]
)
async def create_assignment(
    dataset_id: int, body: AssignmentCreate, request: Request, session: DbDep, ctx: AssignCtx
) -> dict[str, Any]:
    return ok(await assignment_service.create_assignment(session, ctx, request, dataset_id, body))


@router.put(
    "/assignments/{assignment_id}",
    summary="修改分配（kb:dataset:assign；ACL 所有者）",
    response_model=ApiResponse[AssignmentItem],
)
async def update_assignment(
    dataset_id: int, assignment_id: int, body: AssignmentUpdate, request: Request, session: DbDep, ctx: AssignCtx
) -> dict[str, Any]:
    return ok(await assignment_service.update_assignment(session, ctx, request, dataset_id, assignment_id, body))


@router.delete(
    "/assignments/{assignment_id}",
    summary="移除分配（kb:dataset:assign；ACL 所有者）",
    response_model=ApiResponse[None],
)
async def delete_assignment(
    dataset_id: int, assignment_id: int, request: Request, session: DbDep, ctx: AssignCtx
) -> dict[str, Any]:
    await assignment_service.delete_assignment(session, ctx, request, dataset_id, assignment_id)
    return ok(None)


@router.get(
    "/assignable-orgs",
    summary="可分配组织树（kb:dataset:assign 或 kb:dataset:transfer；ACL 所有者）",
    response_model=ApiResponse[list[AssignableOrgNode]],
)
async def assignable_orgs(dataset_id: int, ctx: CandidateCtx, session: DbDep) -> dict[str, Any]:
    return ok(await assignment_service.assignable_orgs(session, ctx, dataset_id))


@router.get(
    "/assignable-users",
    summary="可分配用户（kb:dataset:assign 或 kb:dataset:transfer；ACL 所有者；仅启用未删除，排除所有者）",
    response_model=ApiResponse[Page[AssignableUser]],
)
async def assignable_users(
    dataset_id: int,
    ctx: CandidateCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
    org_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    items, total = await assignment_service.assignable_users(
        session, ctx, dataset_id, keyword=keyword.strip() if keyword else None, org_id=org_id, pp=pp
    )
    return page(items, total, pp.page, pp.page_size)
