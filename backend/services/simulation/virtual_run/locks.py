"""日运行锁（h2-interfaces §3）：Redis SET NX + TTL。

键 ``quantmind:r01:vr:lock:{ledger_run_id}:{decision_date}``（db0 专用
前缀，不占用活盘键空间）。覆盖：

- 重复调度/双 worker：同日第二持有者拿不到锁，直接返回 busy（不重入）；
- 进程崩溃残留：TTL 过期后允许接管并从恢复点续跑；
- 释放需持有 token（Lua 比对），误删他人锁不可能。

后端可插拔：生产 RedisLockBackend；测试/确定性验收 InMemoryLockBackend。
"""

from __future__ import annotations

import secrets
import time
from typing import Protocol

LOCK_KEY = "quantmind:r01:vr:lock:{ledger_run_id}:{decision_date}"


def make_lock_key(ledger_run_id: str, decision_date: str) -> str:
    return LOCK_KEY.format(ledger_run_id=ledger_run_id, decision_date=decision_date)


class LockBackend(Protocol):
    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool: ...
    def release(self, key: str, token: str) -> bool: ...
    def held_by(self, key: str) -> str | None: ...


class InMemoryLockBackend:
    """进程内锁（单测/确定性验收）；语义与 Redis 版一致。"""

    def __init__(self) -> None:
        self._locks: dict[str, tuple[str, float]] = {}

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        cur = self._locks.get(key)
        if cur is not None and cur[1] > now:
            return False
        self._locks[key] = (token, now + ttl_seconds)
        return True

    def release(self, key: str, token: str) -> bool:
        cur = self._locks.get(key)
        if cur is not None and cur[0] == token:
            del self._locks[key]
            return True
        return False

    def held_by(self, key: str) -> str | None:
        cur = self._locks.get(key)
        if cur is not None and cur[1] > time.monotonic():
            return cur[0]
        return None


class RedisLockBackend:
    """Redis db0 锁后端（SET key token NX PX ttl；Lua 校验 token 释放）。"""

    _RELEASE_LUA = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_url: str):
        import redis  # 延迟导入：测试环境可完全无 redis 依赖

        self._r = redis.from_url(redis_url, socket_timeout=3)

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        return bool(self._r.set(key, token, nx=True, px=int(ttl_seconds * 1000)))

    def release(self, key: str, token: str) -> bool:
        return bool(self._r.eval(self._RELEASE_LUA, 1, key, token))

    def held_by(self, key: str) -> str | None:
        v = self._r.get(key)
        return v.decode() if v is not None else None


class DayRunLock:
    """单决策日运行锁的上下文管理用法。

    用法::

        lock = DayRunLock(backend, ledger_run_id, decision_date, ttl_seconds=...)
        if not lock.acquire():
            ...  # busy：另一 worker 在推进，直接让出
        try:
            ...
        finally:
            lock.release()
    """

    def __init__(
        self,
        backend: LockBackend,
        ledger_run_id: str,
        decision_date: str,
        *,
        ttl_seconds: int,
    ):
        self._backend = backend
        self._key = make_lock_key(ledger_run_id, decision_date)
        self._ttl = int(ttl_seconds)
        self._token: str | None = None

    @property
    def key(self) -> str:
        return self._key

    def acquire(self) -> bool:
        self._token = secrets.token_hex(16)
        return self._backend.acquire(self._key, self._token, self._ttl)

    def release(self) -> bool:
        if self._token is None:
            return False
        ok = self._backend.release(self._key, self._token)
        self._token = None
        return ok
