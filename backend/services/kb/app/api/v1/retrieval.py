"""召回测试接口（tech-design-m2 5.7）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.retrieval import RetrievalResult, RetrieveRecordItem, RetrieveTestBody
from app.services import retrieval_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(prefix="/kb/datasets/{dataset_id}", tags=["retrieval"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
TestCtx = Annotated[AuthContext, Depends(require_perm("kb:retrieval:test"))]


@router.post(
    "/retrieve-test",
    summary="召回测试（kb:retrieval:test；ACL 只读；写入测试记录并计入召回次数）",
    response_model=ApiResponse[RetrievalResult],
)
async def retrieve_test(dataset_id: int, body: RetrieveTestBody, ctx: TestCtx, session: DbDep) -> dict[str, Any]:
    return ok(await retrieval_service.retrieve_test(session, ctx, dataset_id, body))


@router.get(
    "/retrieve-records",
    summary="我的召回测试记录（kb:retrieval:test；ACL 只读；仅本人最近 20 条）",
    response_model=ApiResponse[list[RetrieveRecordItem]],
)
async def retrieve_records(dataset_id: int, ctx: TestCtx, session: DbDep) -> dict[str, Any]:
    return ok(await retrieval_service.list_records(session, ctx, dataset_id))
