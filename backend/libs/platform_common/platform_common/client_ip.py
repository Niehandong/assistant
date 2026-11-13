"""客户端 IP 解析：仅当直连对端是可信代理时才信任 X-Forwarded-For。"""

from __future__ import annotations

from collections.abc import Sequence
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import Request

Network = IPv4Network | IPv6Network


def _parse_networks(trusted_proxies: Sequence[str]) -> list[Network]:
    return [ip_network(p, strict=False) for p in trusted_proxies]


def _is_trusted(ip: str, networks: Sequence[Network]) -> bool:
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def get_client_ip(request: Request, trusted_proxies: Sequence[str]) -> str | None:
    """返回客户端 IP。

    - 直连对端不在可信代理内：直接返回对端地址（忽略可能被伪造的 XFF）。
    - 否则从 XFF 最右侧开始跳过可信代理，第一个非可信地址即客户端；全部可信则取最左侧。
    - XFF 中出现非法地址：视为不可信，返回直连对端地址。
    """
    peer = request.client.host if request.client else None
    if peer is None:
        return None
    networks = _parse_networks(trusted_proxies)
    if not _is_trusted(peer, networks):
        return peer
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return peer
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    for hop in reversed(hops):
        try:
            ip_address(hop)
        except ValueError:
            return peer
        if not _is_trusted(hop, networks):
            return hop
    return hops[0] if hops else peer
