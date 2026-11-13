"""组织保护规则（技术方案 M1 5.2.0）：停用 / 删除的保护判定。

``compute(session, op)`` 一次性算出操作人的"管辖根集合 R(op)"与"本人组织链 P(op)"，得到 ``OrgProtection``。
同一个对象同时供：

* 组织管理树（5.2.1）为每个节点计算 ``disable_blocked_reason`` / ``delete_blocked_reason``；
* 停用（5.2.7）/ 删除（5.2.8）接口的请求时校验，

两处调用同一组判定函数，保证提示与实际校验一致。判定顺序：集团节点 400114 → 管辖根 403102 →
本人组织链（仅停用，超管与 ALL 同样生效）403103。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DataScopeType, OrgType, Status
from app.models import SysOrg
from app.repositories import org_repo, role_repo
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError

GROUP_PROTECTED = (400114, "集团节点不能移动、停用或删除")
ROOT_PROTECTED = (403102, "不能停用/删除自己管辖范围的根组织，请联系上级管理员")
MOVE_ROOT_PROTECTED = (403101, "不能调整自己管辖范围根组织的上级，请联系上级管理员")
MOVE_PARENT_UNMANAGEABLE = (403104, "当前上级组织不在您的管理范围内，不能移动该组织")
OWN_CHAIN_PROTECTED = (403103, "不能停用本人所在的组织及其上级组织")


def _ancestor_ids(org: SysOrg) -> set[int]:
    return {int(x) for x in org.ancestors.split(",") if x and int(x) != 0}


@dataclass(frozen=True)
class OrgProtection:
    unrestricted: bool  # 超管或任一角色 ALL：不计算管辖根
    roots: frozenset[int]  # R(op)
    own_chain: frozenset[int]  # P(op)

    def disable_error(self, org: SysOrg) -> tuple[int, str] | None:
        """停用该节点时的拦截原因（不含"状态已是停用"的 no-op 判断）；不受保护返回 None。"""
        if org.org_type == OrgType.GROUP:
            return GROUP_PROTECTED
        if not self.unrestricted and org.id in self.roots:
            return ROOT_PROTECTED
        if org.id in self.own_chain:
            return OWN_CHAIN_PROTECTED
        return None

    def delete_error(self, org: SysOrg) -> tuple[int, str] | None:
        if org.org_type == OrgType.GROUP:
            return GROUP_PROTECTED
        if not self.unrestricted and org.id in self.roots:
            return ROOT_PROTECTED
        return None

    def move_error(self, org: SysOrg, parent_manageable: bool) -> tuple[int, str] | None:
        """移动保护 M1~M3：集团 400114 → 管辖根且上级不可管理 403101 → 上级不可管理 403104。"""
        if org.org_type == OrgType.GROUP:
            return GROUP_PROTECTED
        if parent_manageable:
            return None
        if not self.unrestricted and org.id in self.roots:
            return MOVE_ROOT_PROTECTED
        return MOVE_PARENT_UNMANAGEABLE

    def move_blocked_reason(self, org: SysOrg, parent_manageable: bool) -> str | None:
        err = self.move_error(org, parent_manageable)
        return err[1] if err else None

    def check_move(self, org: SysOrg, parent_manageable: bool) -> None:
        err = self.move_error(org, parent_manageable)
        if err is not None:
            raise BizError(*err)

    def check_disable(self, org: SysOrg) -> None:
        err = self.disable_error(org)
        if err is not None:
            raise BizError(*err)

    def check_delete(self, org: SysOrg) -> None:
        err = self.delete_error(org)
        if err is not None:
            raise BizError(*err)

    def disable_blocked_reason(self, org: SysOrg) -> str | None:
        """树节点提示文案；节点已停用时恒为 None（启用不受保护）。"""
        if org.status != Status.ENABLED:
            return None
        err = self.disable_error(org)
        return err[1] if err else None

    def delete_blocked_reason(self, org: SysOrg) -> str | None:
        err = self.delete_error(org)
        return err[1] if err else None


async def compute(session: AsyncSession, op: AuthContext) -> OrgProtection:
    """基于操作人当前启用且未删除的角色计算（每个角色分别算管辖根后取并集）。"""
    own_chain = frozenset(op.org_path)
    if op.is_super_admin or op.data_scope.all:
        return OrgProtection(unrestricted=True, roots=frozenset(), own_chain=own_chain)

    roles = await role_repo.effective_roles_of_users(session, [op.user_id])
    roots: set[int] = set()
    custom_role_ids = [r.role_id for r in roles if r.data_scope == DataScopeType.CUSTOM]
    for r in roles:
        kind = r.data_scope
        if kind in (DataScopeType.COMPANY_AND_CHILD, DataScopeType.COMPANY):
            roots.add(op.company_id)
        elif kind in (DataScopeType.DEPT_AND_CHILD, DataScopeType.DEPT):
            roots.add(op.org_id)
        elif kind == DataScopeType.ALL:  # data_scope.all 已在上方处理，这里仅为防御
            return OrgProtection(unrestricted=True, roots=frozenset(), own_chain=own_chain)
    if custom_role_ids:
        chosen_by_role = await role_repo.role_custom_orgs(session, custom_role_ids)
        all_chosen = {oid for ids in chosen_by_role.values() for oid in ids}
        orgs = await org_repo.get_by_ids(session, all_chosen)
        for chosen in chosen_by_role.values():
            alive = {oid: orgs[oid] for oid in chosen if oid in orgs and not orgs[oid].is_deleted}
            for oid, org in alive.items():
                if not (_ancestor_ids(org) & alive.keys()):  # 祖先链上没有该角色的其他勾选组织
                    roots.add(oid)
    return OrgProtection(unrestricted=False, roots=frozenset(roots), own_chain=own_chain)
