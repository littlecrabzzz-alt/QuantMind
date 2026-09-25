"""可控时钟（h2-interfaces §3）：runner 全链路时间读取的唯一入口。

工程验收用可控时钟+故障注入，不依赖真实等待；生产入口用 SystemClock。
所有阶段（数据就绪截止/执行窗口/心跳/幂等记录）一律经注入的 clock
取当前时间，禁止散落 ``datetime.now()``。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.shared.utc_datetime import utc_now

SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai() -> ZoneInfo:
    """运行默认时区（配置可覆盖，默认 Asia/Shanghai）。"""
    return SHANGHAI


class RunClock(Protocol):
    """时间源协议：返回 aware UTC 时间。"""

    def now(self) -> datetime: ...


class SystemClock:
    """生产时钟：真实 UTC now（经 shared.utc_datetime 统一口径）。"""

    def now(self) -> datetime:
        return utc_now()


class FrozenClock:
    """可控时钟：固定/手动推进，工程验收与测试用。

    - ``set_shanghai(day, "HH:MM")`` 把时钟定到某日上海墙钟时点；
    - ``advance(timedelta)`` 平移；
    - ``sleep`` 不存在——验收通过显式拨针覆盖休眠唤醒场景。
    """

    def __init__(self, initial: datetime | None = None):
        self._now = initial or utc_now()

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set_shanghai(self, day: date, hhmm: str) -> None:
        """定位到 day 的上海墙钟 hhmm（HH:MM）。"""
        h, m = hhmm.split(":")
        wall = datetime.combine(day, time(int(h), int(m)), tzinfo=SHANGHAI)
        self.set(wall.astimezone(timezone.utc))


def local_wall(now: datetime, tz: ZoneInfo) -> datetime:
    """UTC now 在运行时区的墙钟时间（调度窗口判断用）。"""
    return now.astimezone(tz)


def parse_hhmm(value: str) -> time:
    h, m = str(value).strip().split(":")
    if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise ValueError(f"非法 HH:MM: {value!r}")
    return time(int(h), int(m))
