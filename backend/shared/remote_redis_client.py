import logging
import os

from redis import Redis

from backend.shared.quote_redis_config import (
    remote_quote_redis_db,
    remote_quote_redis_host,
    remote_quote_redis_password,
    remote_quote_redis_port,
)

logger = logging.getLogger(__name__)

# ============================================================
# 行情 Redis — 默认全市场库 quantmindai.cn db3（可用环境变量覆盖）
# ============================================================
REMOTE_REDIS_HOST = remote_quote_redis_host()
REMOTE_REDIS_PORT = remote_quote_redis_port()
REMOTE_REDIS_USER = os.getenv("REMOTE_QUOTE_REDIS_USER", os.getenv("REDIS_USER", ""))
REMOTE_REDIS_PASSWORD = remote_quote_redis_password() or ""
REMOTE_REDIS_DB = remote_quote_redis_db()


def get_remote_redis_client(db: int = None) -> Redis:
    """获取行情 Redis 客户端"""
    if db is None:
        db = REMOTE_REDIS_DB
    return Redis(
        host=REMOTE_REDIS_HOST,
        port=REMOTE_REDIS_PORT,
        db=db,
        username=REMOTE_REDIS_USER or None,
        password=REMOTE_REDIS_PASSWORD or None,
        decode_responses=True,
    )
