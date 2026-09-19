"""全局股票池 - 用户态接口（读选项 + 写本人私有池）。

与后台管理 `/api/v1/admin/stock-pools` 的分工：
- 后台管理负责全局/系统池「写」；
- 本路由负责「读」（各功能下拉）以及 **本人 scope=user 池** 的 ensure/加减成员
  （favorites / research，对齐终端自选与旧研究池）。

可见性：`scope=global` 全平台可见；`tenant` / `user` 需身份匹配；
`archived` 一律不可见。成员读取的是 TXT（保存即可见，无发布环节）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.services.engine.auth_context import get_authenticated_identity
from backend.shared.database_manager_v2 import get_session
from backend.shared.stock_pool import repository as repo
from backend.shared.stock_pool.resolver import ResolveContext, resolver
from backend.shared.stock_pool.user_pools import (
    UserPoolEnsureRequest,
    add_symbol_to_user_pool,
    ensure_user_pool,
    get_owned_user_pool,
    pool_to_dict,
    remove_symbol_from_user_pool,
    replace_user_pool_members,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stock-pools", tags=["Stock Pool"])

_VISIBILITY_CLAUSE = """
    status <> 'archived'
    AND (
        scope = 'global'
        OR (scope = 'tenant' AND tenant_id = :tenant_id)
        OR (scope = 'user' AND owner_user_id = :user_id)
    )
"""


class UserPoolMembersReplace(BaseModel):
    symbols: list[str] = Field(default_factory=list)


@router.get("/options", summary="股票池下拉选项（轻量）")
async def list_pool_options(
    request: Request,
    market: str | None = Query(None),
    pool_type: str | None = Query(None),
    include_system: bool = Query(True),
):
    """给前端选择器用的精简列表：不含成员明细。"""
    user_id, tenant_id = get_authenticated_identity(request)

    where = [_VISIBILITY_CLAUSE]
    params: dict[str, object] = {"tenant_id": tenant_id, "user_id": user_id}
    if market:
        where.append("market = :market")
        params["market"] = market.upper()
    if pool_type:
        where.append("pool_type = :pool_type")
        params["pool_type"] = pool_type
    if not include_system:
        where.append("is_system = FALSE")

    async with get_session() as session:
        await repo.ensure_tables(session)
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT pool_id, code, name, description, market, pool_type,
                           scope, status, symbol_count, checksum, is_system
                      FROM qm_stock_pool
                     WHERE {" AND ".join(where)}
                     ORDER BY is_system DESC, market ASC, code ASC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.get("", summary="股票池列表")
async def list_pools(
    request: Request,
    market: str | None = Query(None),
    pool_type: str | None = Query(None),
    keyword: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    user_id, tenant_id = get_authenticated_identity(request)

    where = [_VISIBILITY_CLAUSE]
    params: dict[str, object] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "limit": int(limit),
        "offset": int(offset),
    }
    if market:
        where.append("market = :market")
        params["market"] = market.upper()
    if pool_type:
        where.append("pool_type = :pool_type")
        params["pool_type"] = pool_type
    if keyword:
        where.append("(code ILIKE :kw OR name ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    clause = " AND ".join(where)

    async with get_session() as session:
        await repo.ensure_tables(session)
        total = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM qm_stock_pool WHERE {clause}"), params
            )
        ).scalar() or 0
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT pool_id, code, name, description, market, pool_type,
                           scope, status, symbol_count, checksum, is_system,
                           file_path, updated_at
                      FROM qm_stock_pool
                     WHERE {clause}
                     ORDER BY is_system DESC, market ASC, code ASC
                     LIMIT :limit OFFSET :offset
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

    return {
        "total": int(total),
        "items": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/resolve", summary="解析池引用（供功能页联调 / 排障）")
async def resolve_ref(
    request: Request,
    ref: str = Query(..., description="pool:csi300 / csi300 / list:SH600036 / all"),
    market: str | None = Query(None),
    preview_limit: int = Query(20, ge=0, le=500),
):
    user_id, tenant_id = get_authenticated_identity(request)

    snap = await resolver.resolve(
        ref,
        ResolveContext(tenant_id=tenant_id, user_id=str(user_id), market=market),
        strict=False,
    )
    return {
        "ref": ref,
        "pool_id": snap.pool_id,
        "code": snap.code,
        "market": snap.market,
        "source": snap.source,
        "unfiltered": snap.unfiltered,
        "symbol_count": len(snap.symbols),
        "checksum": snap.checksum,
        "warnings": snap.warnings,
        "sample": snap.api_symbols[:preview_limit],
    }


# ---------------------------------------------------------------------------
# 本人私有池（必须放在 /{pool_id} 之前，避免被路径参数吞掉）
# ---------------------------------------------------------------------------
@router.post("/me/ensure", summary="确保本人用户池存在（favorites/research）")
async def me_ensure_pool(request: Request, payload: UserPoolEnsureRequest):
    user_id, tenant_id = get_authenticated_identity(request)
    try:
        async with get_session() as session:
            pool = await ensure_user_pool(
                session,
                code=payload.code,
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                name=payload.name,
                market=payload.market,
                actor=str(user_id),
            )
            members = repo.read_members(pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "pool": pool_to_dict(pool),
        "symbols": members,
        "total": len(members),
        "ref": f"pool:{pool.code}",
    }


@router.get("/me/{code}", summary="获取本人用户池（含成员）")
async def me_get_pool(
    request: Request,
    code: str,
    ensure: bool = Query(True, description="不存在时是否自动创建"),
    limit: int = Query(20000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
):
    user_id, tenant_id = get_authenticated_identity(request)
    try:
        async with get_session() as session:
            if ensure:
                pool = await ensure_user_pool(
                    session,
                    code=code,
                    user_id=str(user_id),
                    tenant_id=str(tenant_id),
                    actor=str(user_id),
                )
            else:
                pool = await get_owned_user_pool(
                    session,
                    code=code,
                    user_id=str(user_id),
                    tenant_id=str(tenant_id),
                )
            if pool is None:
                raise HTTPException(status_code=404, detail=f"用户池不存在: {code}")
            members = repo.read_members(pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "pool": pool_to_dict(pool),
        "symbols": members[offset : offset + limit],
        "total": len(members),
        "ref": f"pool:{pool.code}",
        "limit": limit,
        "offset": offset,
    }


@router.post("/me/{code}/symbols/{symbol}", summary="向本人用户池追加一只股票")
async def me_add_symbol(request: Request, code: str, symbol: str):
    user_id, tenant_id = get_authenticated_identity(request)
    try:
        async with get_session() as session:
            result = await add_symbol_to_user_pool(
                session,
                code=code,
                symbol=symbol,
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                actor=str(user_id),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.delete("/me/{code}/symbols/{symbol}", summary="从本人用户池移除一只股票")
async def me_remove_symbol(request: Request, code: str, symbol: str):
    user_id, tenant_id = get_authenticated_identity(request)
    try:
        async with get_session() as session:
            result = await remove_symbol_from_user_pool(
                session,
                code=code,
                symbol=symbol,
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                actor=str(user_id),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.put("/me/{code}/members", summary="整体覆盖本人用户池成员")
async def me_replace_members(
    request: Request, code: str, payload: UserPoolMembersReplace
):
    user_id, tenant_id = get_authenticated_identity(request)
    try:
        async with get_session() as session:
            result = await replace_user_pool_members(
                session,
                code=code,
                symbols=list(payload.symbols or []),
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                actor=str(user_id),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/{pool_id}", summary="股票池详情")
async def get_pool(request: Request, pool_id: str):
    user_id, tenant_id = get_authenticated_identity(request)

    async with get_session() as session:
        await repo.ensure_tables(session)
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT pool_id, code, name, description, market, pool_type,
                           scope, status, symbol_count, checksum, is_system,
                           file_path, source_kind, source_ref,
                           created_at, updated_at
                      FROM qm_stock_pool
                     WHERE pool_id = :pid AND {_VISIBILITY_CLAUSE}
                    """
                    ),
                    {"pid": pool_id, "tenant_id": tenant_id, "user_id": user_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"股票池不存在或无权访问: {pool_id}"
            )

    return dict(row)


@router.get("/{pool_id}/members", summary="股票池成员（读 TXT）")
async def list_members(
    request: Request,
    pool_id: str,
    limit: int = Query(500, ge=1, le=20000),
    offset: int = Query(0, ge=0),
):
    user_id, tenant_id = get_authenticated_identity(request)

    async with get_session() as session:
        await repo.ensure_tables(session)
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT * FROM qm_stock_pool
                     WHERE pool_id = :pid AND {_VISIBILITY_CLAUSE}
                    """
                    ),
                    {"pid": pool_id, "tenant_id": tenant_id, "user_id": user_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"股票池不存在或无权访问: {pool_id}"
            )
        from backend.shared.stock_pool.schemas import StockPool

        pool = StockPool(**dict(row))
        api_symbols = repo.read_members(pool)

    return {
        "pool_id": pool_id,
        "total": len(api_symbols),
        "symbols": api_symbols[offset : offset + limit],
        "checksum": pool.checksum,
        "limit": limit,
        "offset": offset,
    }
