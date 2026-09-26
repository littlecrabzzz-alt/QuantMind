"""每日数据就绪门控（h2-interfaces §1 消费侧，H2.1-D2 的 runner 消费端）。

**接口对齐声明（待联调）**：日增量包身份五元组与质量门控字段由 p02r 的
``scripts/publish_r01_daily_inputs.py``（D1）写入 manifest、D2 门控在发布
侧完成后，本模块的 ``DailyInputsProvider`` 即切换真实注册表实现；当前
提供 ``StaticPackageProvider`` fixture stub（单一冻结包模拟逐日增量身份），
接口签名按 h2-interfaces §1 冻结，不改流水线。

语义：

- ``resolve(decision_date, ...)`` 返回三态：
  - ``ready``：身份五元组 + 质量检查全 pass → 允许冻结输入；
  - ``data_blocked(reason)``：任一质量项 fail/unknown 或数据迟到——显式
    阻塞受影响决策，禁止陈旧数据冒充当日已执行；
  - ``not_trade_day``：决策日不在交易日历（休市日/无交易日）——有效
    无运行日，不是错误。
- 质量检查（消费侧复核；生产者 manifest 为第一道）：
  行情覆盖 / 分红事件可读 / 交易状态 / 必要预热 / 哈希校验 / 新鲜度。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from backend.services.simulation.replay.etf_input_package import EtfInputPackage


@dataclass(frozen=True)
class DailyDataIdentity:
    """决策日 ↔ 数据版本 ↔ 取得时间（h2-interfaces §1 身份五元组+时点）。"""

    decision_date: str
    package_id: str
    package_version: str  # d<YYYYMMDD>（日增量；v 前缀=历史固定包）
    source_release_id: str
    manifest_sha256: str
    data_as_of: str  # 数据截止交易日
    obtained_at: str  # 来源分区实际取得时间（aware UTC）
    revised: bool = False
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "source_release_id": self.source_release_id,
            "manifest_sha256": self.manifest_sha256,
            "data_as_of": self.data_as_of,
            "obtained_at": self.obtained_at,
            "revised": self.revised,
            "supersedes": self.supersedes,
        }


@dataclass
class GateCheck:
    name: str
    status: str  # pass | fail | unknown | skip
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class GateResult:
    status: str  # ready | data_blocked | not_trade_day
    reason: str | None = None
    checks: list[GateCheck] = field(default_factory=list)
    identity: DailyDataIdentity | None = None
    package: EtfInputPackage | None = None

    @property
    def blocked_reason(self) -> str | None:
        return self.reason if self.status == "data_blocked" else None


class DailyInputsProvider(Protocol):
    """日增量包供数接口（p02 D1/D2 生产者实现前的冻结签名）。"""

    def resolve(
        self,
        decision_date: date,
        *,
        symbols: list[str],
        now: datetime,
    ) -> GateResult: ...

    def load(
        self, identity: DailyDataIdentity, *, lock: dict | None = None
    ) -> EtfInputPackage:
        """按冻结身份取输入包（同身份必须返回同内容；lock=冻结清单）。"""

    def input_lock(
        self, upto: date | None = None, *, now: datetime | None = None
    ) -> dict:
        """冻结哈希清单（基线+已发布非修订日增量，upto 截止含当日；
        now=运行时钟，按 obtained_at 过滤迟到日包）。"""

    def next_open_trade_date(self, d: date) -> date | None:
        """d 之后下一个开市日（日历口径；None=超出已知日历）。"""


def _fixture_daily_identity(
    pkg: EtfInputPackage, decision_date: date, obtained_at: datetime
) -> DailyDataIdentity:
    """由单一冻结包派生逐日增量身份（stub：package_version=d<date>）。"""
    m = pkg.manifest
    return DailyDataIdentity(
        decision_date=decision_date.isoformat(),
        package_id=str(m.get("package_id")),
        package_version=f"d{decision_date.strftime('%Y%m%d')}",
        source_release_id=str(m.get("source_release_id", "")),
        manifest_sha256=pkg.manifest_sha256,
        data_as_of=decision_date.isoformat(),
        obtained_at=obtained_at.isoformat(),
    )


class StaticPackageProvider:
    """fixture/冻结包供数 stub（待 p02 D1/D2 合入后换真实注册表实现）。
    - 单一 ``EtfInputPackage`` 充当"v2 历史包+日增量"整体；每日身份按
      ``package_version=d<YYYYMMDD>`` 派生（身份可绑定决策日即可）；
    - ``late_dates``：数据迟到故障注入 → ``data_blocked("data_late…")``；
    - ``blocked_dates``：按日注入任意阻塞原因（缺数/未完成等）；
    - ``obtained_delay``：模拟取得时间晚于窗口（生产者时钟）。
    """

    stub_note = (
        "StaticPackageProvider=fixture stub（h2-interfaces §1 待联调）："
        "p02 publish_r01_daily_inputs 合入后切换真实日增量包注册表实现"
    )

    def __init__(
        self,
        pkg: EtfInputPackage,
        *,
        late_dates: set[date] | None = None,
        blocked_dates: dict[date, str] | None = None,
    ):
        self._pkg = pkg
        self.late_dates = set(late_dates or ())
        self.blocked_dates = dict(blocked_dates or {})

    @property
    def package(self) -> EtfInputPackage:
        return self._pkg

    def resolve(
        self,
        decision_date: date,
        *,
        symbols: list[str],
        now: datetime,
    ) -> GateResult:
        pkg = self._pkg
        checks: list[GateCheck] = []

        # 交易日历（休市日/无交易日 = 有效无运行日）
        if not pkg.is_trade_date(decision_date):
            return GateResult(
                status="not_trade_day",
                reason=f"{decision_date} 不在输入包交易日历（休市/无交易日）",
                checks=[GateCheck("trade_calendar", "skip", "not a trade date")],
            )
        checks.append(GateCheck("trade_calendar", "pass"))

        # 故障注入：数据迟到/显式阻塞
        if decision_date in self.late_dates:
            return GateResult(
                status="data_blocked",
                reason=(
                    f"data_late: {decision_date} 日增量包未在决策截止前取得"
                    "（故障注入 late_dates；禁止陈旧数据冒充当日已执行）"
                ),
                checks=checks + [GateCheck("freshness", "fail", "injected data_late")],
            )
        if decision_date in self.blocked_dates:
            return GateResult(
                status="data_blocked",
                reason=self.blocked_dates[decision_date],
                checks=checks
                + [GateCheck("producer_gate", "fail", "injected blocked")],
            )

        # 行情覆盖：决策标的当日行
        bars = pkg.load_date(decision_date, symbols=symbols)
        missing = [s for s in symbols if s not in bars]
        if missing:
            return GateResult(
                status="data_blocked",
                reason=f"coverage_missing: 决策标的当日无行情 {missing}",
                checks=checks + [GateCheck("bar_coverage", "fail", str(missing))],
            )
        suspended = sorted(s for s, b in bars.items() if b.suspended)
        checks.append(
            GateCheck(
                "trading_status",
                "pass",
                f"suspended={suspended or '无'}（停牌是数据不是失败）",
            )
        )

        # 分红/份额事件可读（unknown_blocked 标的由账本停买，不阻塞决策）
        gap_syms = sorted(pkg.unresolved_gap_symbols())
        checks.append(
            GateCheck(
                "dividend_events",
                "pass",
                f"unresolved_gap_symbols={gap_syms or '无'}（账本暂停其买入）",
            )
        )

        # 必要预热：上一交易日存在（T+1 信号对齐需要）
        prev = pkg.prev_trade_date(decision_date)
        if prev is None:
            return GateResult(
                status="data_blocked",
                reason="warmup_missing: 决策日无上一交易日（预热不足）",
                checks=checks + [GateCheck("warmup", "fail")],
            )
        checks.append(GateCheck("warmup", "pass", f"prev_trade_date={prev}"))

        # 哈希校验：加载期已强制 manifest_sha256 比对（此处复核记录）
        checks.append(
            GateCheck("manifest_sha256", "pass", pkg.manifest_sha256[:16] + "…")
        )

        identity = _fixture_daily_identity(pkg, decision_date, now)
        checks.append(
            GateCheck("freshness", "pass", f"data_as_of={identity.data_as_of}")
        )
        return GateResult(status="ready", checks=checks, identity=identity, package=pkg)

    def load(
        self, identity: DailyDataIdentity, *, lock: dict | None = None
    ) -> EtfInputPackage:
        # stub：单一冻结包内容不可变，lock 无额外作用（保持协议一致）
        return self._pkg

    def input_lock(
        self, upto: date | None = None, *, now: datetime | None = None
    ) -> dict:
        # stub：单一冻结包内容不可变，无日增量清单（now 兼容协议签名）
        return {
            "baseline": {
                "package_id": self._pkg.package_id,
                "manifest_sha256": self._pkg.manifest_sha256,
                "root": str(self._pkg.root),
            },
            "daily": [],
        }

    def next_open_trade_date(self, d: date) -> date | None:
        # fixture/冻结包：包内日历（包末尾之后未知 → None，前沿语义）
        return self._pkg.next_trade_date(d)


# ---------------------------------------------------------------------------
# 真实日增量包供数（p02 H2.1-D1/D2 已合入：registry + evaluate_data_readiness）
# ---------------------------------------------------------------------------


class DailyIncrementProvider:
    """v2 冻结基线 + 日增量包（d<date>）供数（真实链路）。

    - 注册表：``~/Library/Application Support/QuantMind/r01/package-registry.json``
      （p02 发布通路；kind=daily_increment 条目）；
    - 门控：直接消费 ``publish_r01_daily_inputs.evaluate_data_readiness``
      的冻结签名（ready/data_blocked/blocked_reasons/identity）；
    - 账本输入：基线 v2 包与当日 d 包按 symbol 合并（daily/factors/events/
      etf_limit 追加）后物化到缓存目录，再经 ``load_etf_input_package``
      加载（同身份同内容；合并结果按 baseline+daily sha 缓存复用）；
    - 无当日包：无法区分休市/迟到（runner 侧无独立日历端点）⇒ 显式
      ``data_blocked(no_daily_package)``，不臆造 not_trade_day、不用陈旧
      数据冒充（日历细分待 p02 日历接口后补充，见待联调注记）。
    """

    def __init__(
        self,
        baseline_root: str,
        *,
        baseline_manifest_sha256: str,
        registry_path: str | None = None,
        cache_dir: str | None = None,
    ):
        import json as _json
        from pathlib import Path as _Path

        from backend.services.simulation.replay.etf_input_package import (
            load_etf_input_package,
        )

        self._baseline_root = baseline_root
        self._baseline_sha = baseline_manifest_sha256
        self.baseline = load_etf_input_package(
            baseline_root, expect_manifest_sha256=baseline_manifest_sha256
        )
        if registry_path is None:
            registry_path = str(
                _Path.home()
                / "Library/Application Support/QuantMind/r01/package-registry.json"
            )
        self._registry_path = registry_path
        self._cache_dir = _Path(cache_dir) if cache_dir else None
        self._merged: dict[str, EtfInputPackage] = {}
        self._identity_by_key: dict[str, DailyDataIdentity] = {}
        self._json = _json

    # -- 注册表 ---------------------------------------------------------

    @property
    def package(self) -> EtfInputPackage:
        """当前可用包视图（最近合并的日增量；否则基线）——供状态导出/确认入口。"""
        if self._merged:
            return next(iter(list(self._merged.values())[-1:]))
        return self.baseline

    def _registry_entries(self) -> dict[str, dict]:
        p = __import__("pathlib").Path(self._registry_path)
        if not p.is_file():
            return {}
        data = self._json.loads(p.read_text(encoding="utf-8"))
        return {
            uri: e
            for uri, e in (data.get("packages") or {}).items()
            if e.get("kind") == "daily_increment"
        }

    def _daily_entry(self, decision_date: date) -> tuple[str, dict] | None:
        want = f"d{decision_date.strftime('%Y%m%d')}"
        for uri, e in self._registry_entries().items():
            if e.get("package_version") == want:
                return uri, e
        return None

    # -- DailyInputsProvider 协议 ----------------------------------------

    def resolve(
        self,
        decision_date: date,
        *,
        symbols: list[str],
        now: datetime,
    ) -> GateResult:
        baseline = self.baseline
        # 优先日增量包：当日 d 包已发布 ⇒ 身份/门控/数据以此为准；
        # 基线内日期且无 d 包 ⇒ 回退基线（回放/历史场景）；基线之后且
        # 无 d 包 ⇒ 显式受阻（未发布或休市无法区分，不臆造不冒充）
        found = self._daily_entry(decision_date)
        if found is None:
            if baseline.is_trade_date(decision_date):
                provider = StaticPackageProvider(baseline)
                return provider.resolve(decision_date, symbols=symbols, now=now)
            # 基线之后：用日包日历分类休市/无交易日；开市日无包=受阻
            is_open = self._calendar_open(decision_date)
            if is_open is False:
                return GateResult(
                    status="not_trade_day",
                    reason=f"{decision_date} 非交易日（日包日历 is_open=0：周末/节假日）",
                    checks=[GateCheck("trade_calendar", "skip", "closed")],
                )
            return GateResult(
                status="data_blocked",
                reason=(
                    f"no_daily_package: 注册表无 d{decision_date.strftime('%Y%m%d')} "
                    "日增量包（开市日未发布=迟到；"
                    "不用陈旧数据冒充当日已执行）"
                    if is_open
                    else f"no_daily_package: {decision_date} 超出已发布日历覆盖，"
                    "无法判定开市日（按受阻处理）"
                ),
                checks=[
                    GateCheck(
                        "daily_package",
                        "unknown",
                        "registry miss" + ("" if is_open else "; calendar range"),
                    )
                ],
            )
        _uri, entry = found
        p02 = _load_p02_publisher()

        root = __import__("pathlib").Path(entry["absolute_path"])
        manifest = self._json.loads(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        import hashlib

        sha = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
        readiness = p02.evaluate_data_readiness(manifest, manifest_sha256=sha)
        if not readiness.get("ready"):
            return GateResult(
                status="data_blocked",
                reason="data_blocked: "
                + "; ".join(readiness.get("blocked_reasons") or []),
                checks=[
                    GateCheck(
                        "p02_readiness_gate",
                        "fail",
                        str(readiness.get("blocked_reasons")),
                    )
                ],
            )
        ident_raw = readiness["identity"]
        identity = DailyDataIdentity(
            decision_date=ident_raw["decision_date"],
            package_id=ident_raw["package_id"],
            package_version=ident_raw["package_version"],
            source_release_id=ident_raw["source_release_id"],
            manifest_sha256=ident_raw["manifest_sha256"],
            data_as_of=str(readiness.get("data_as_of") or ""),
            obtained_at=str(readiness.get("obtained_at") or ""),
            revised=bool(manifest.get("revised")),
            supersedes=(manifest.get("supersedes") or {}).get("package_version"),
        )
        # 迟到校验（J4R2 #2）：obtained_at 晚于运行时钟 ⇒ 数据尚未实际取得，
        # 不得进入已开始/当次的决策（显式受阻，不用未来数据）；
        # 基线内日期可回退基线覆盖（数据当日可得，只是日包未发布）
        if identity.obtained_at:
            try:
                obtained = datetime.fromisoformat(
                    identity.obtained_at.replace("Z", "+00:00")
                )
                if obtained > now:
                    if baseline.is_trade_date(decision_date):
                        provider = StaticPackageProvider(baseline)
                        result = provider.resolve(
                            decision_date, symbols=symbols, now=now
                        )
                        result.checks.append(
                            GateCheck(
                                "daily_pkg_not_yet_obtained",
                                "skip",
                                f"日包 {identity.package_version} 取得晚于时钟"
                                f"（{identity.obtained_at}），回退基线覆盖",
                            )
                        )
                        return result
                    return GateResult(
                        status="data_blocked",
                        reason=(
                            f"data_not_yet_obtained: obtained_at={identity.obtained_at} "
                            f"晚于运行时钟 {now.isoformat()}（数据未到，不冒充已取得）"
                        ),
                        checks=[
                            GateCheck("obtained_at_clock", "fail", identity.obtained_at)
                        ],
                    )
            except ValueError:
                return GateResult(
                    status="data_blocked",
                    reason=f"obtained_at 不可解析: {identity.obtained_at!r}",
                    checks=[
                        GateCheck("obtained_at_clock", "unknown", identity.obtained_at)
                    ],
                )
        pkg = self._merged_package_all()
        # 消费侧复核：决策标的当日行覆盖
        bars = pkg.load_date(decision_date, symbols=symbols)
        missing = [s for s in symbols if s not in bars]
        if missing:
            return GateResult(
                status="data_blocked",
                reason=f"coverage_missing: 决策标的当日无行情 {missing}",
                checks=[GateCheck("bar_coverage", "fail", str(missing))],
            )
        return GateResult(
            status="ready",
            checks=[
                GateCheck("p02_readiness_gate", "pass"),
                GateCheck(
                    "baseline_binding",
                    "pass",
                    f"{self.baseline.package_id}@{self._baseline_sha[:12]}…",
                ),
            ],
            identity=identity,
            package=pkg,
        )

    def load(
        self, identity: DailyDataIdentity, *, lock: dict | None = None
    ) -> EtfInputPackage:
        """按冻结身份取输入包。

        - ``lock``（冻结哈希清单，J4R2 #2）：严格按清单合并（基线+清单内
          日增量，逐项复验 manifest sha；清单外/修订包一律不参与），
          不重取注册表最新——已冻结运行的内容不可变；
        - 无 lock（未冻结场景/测试）：基线+全部已发布非修订日增量。
        """
        if lock is not None:
            return self._merged_locked(lock)
        found = self._daily_entry(date.fromisoformat(identity.decision_date))
        if found is None:
            # 基线回退身份（resolve 走基线路径时由 StaticPackageProvider 派生）：
            # package_id/sha 与基线一致 → 返回合并视图（基线+已发布日增量）
            if (
                identity.package_id == self.baseline.package_id
                and identity.manifest_sha256 == self._baseline_sha
            ):
                return self._merged_package_all()
            raise ValueError(
                f"注册表无 {identity.package_version}（身份与注册表不一致）"
            )
        return self._merged_package_all()

    # -- 冻结哈希清单（J4R2 #2） ------------------------------------------

    def _lockable_entries(
        self, upto: date | None = None, *, now: datetime | None = None
    ) -> list[dict]:
        """可入清单的日增量条目（非修订；upto 截止到某日含）。

        - 修订包（revised=true）只服务于修订轨迹，不参与运行合并——
          已冻结运行与向前运行都不悄悄改历史内容；
        - J5R3 #2：``now`` 给定时按 obtained_at 过滤——取得时间晚于
          运行时钟的日包（迟到/尚未取得）不得进入 resolve 回退后的
          实际加载清单。
        """
        out = []
        for _uri, e, _extra in self._daily_entries_sorted():
            version = str(e.get("package_version", ""))
            if len(version) < 9 or not version.startswith("d"):
                continue
            try:
                day = date(int(version[1:5]), int(version[5:7]), int(version[7:9]))
            except ValueError:
                continue
            if upto is not None and day > upto:
                continue
            root = __import__("pathlib").Path(e["absolute_path"])
            mf = root / "manifest.json"
            if not mf.is_file():
                continue
            import hashlib

            manifest = self._json.loads(mf.read_text(encoding="utf-8"))
            if manifest.get("revised"):
                continue  # 修订包不入运行合并
            if now is not None:
                obtained_raw = str(manifest.get("obtained_at") or "")
                try:
                    obtained = datetime.fromisoformat(
                        obtained_raw.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue  # 取得时间不可解析：不入清单（保守）
                if obtained > now:
                    continue  # 迟到/未取得：不进入实际加载
            out.append(
                {
                    "package_version": version,
                    "manifest_sha256": hashlib.sha256(mf.read_bytes()).hexdigest(),
                    "absolute_path": str(root),
                }
            )
        return out

    def input_lock(
        self, upto: date | None = None, *, now: datetime | None = None
    ) -> dict:
        """冻结哈希清单：基线 + 截至 upto 的已发布非修订日增量。

        ``now``（J5R3 #2）：按 obtained_at 过滤迟到日包——主链冻结/执行
        清单一律传入运行时钟；辅助路径（状态导出）可不传。
        """
        return {
            "baseline": {
                "package_id": self.baseline.package_id,
                "manifest_sha256": self._baseline_sha,
                "root": self._baseline_root,
            },
            "daily": self._lockable_entries(upto=upto, now=now),
        }

    def next_open_trade_date(self, d: date) -> date | None:
        # 日包 calendar.parquet 全量日历（含未来月），供月末信号判定；
        # 超出已知日历（None）→ 前沿：不发月末信号，等日历扩展
        for i in range(1, 61):
            nxt = date.fromordinal(d.toordinal() + i)
            state = self._calendar_open(nxt)
            if state is True:
                return nxt
            if state is None:
                return None
        return None

    @staticmethod
    def lock_key(lock: dict) -> str:
        import hashlib

        return hashlib.sha256(
            json.dumps(lock, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    def _merged_locked(self, lock: dict) -> EtfInputPackage:
        """严格按冻结清单合并：逐项复验 sha（不符显式报错，不静默续）。"""
        import hashlib
        import shutil

        import pandas as pd

        from backend.services.simulation.replay.etf_input_package import (
            load_etf_input_package,
        )

        baseline = lock.get("baseline") or {}
        if baseline.get("manifest_sha256") != self._baseline_sha:
            raise ValueError(
                "input_lock 基线哈希与 provider 不一致："
                f"lock={baseline.get('manifest_sha256')} provider={self._baseline_sha}"
            )
        daily = sorted(lock.get("daily") or [], key=lambda e: e["package_version"])
        for e in daily:
            mf = __import__("pathlib").Path(e["absolute_path"]) / "manifest.json"
            if not mf.is_file():
                raise ValueError(f"input_lock 条目缺失: {e['package_version']} ({mf})")
            sha = hashlib.sha256(mf.read_bytes()).hexdigest()
            if sha != e["manifest_sha256"]:
                raise ValueError(
                    f"input_lock 哈希失配: {e['package_version']} "
                    f"lock={e['manifest_sha256'][:16]}… actual={sha[:16]}…（内容被动过，拒绝）"
                )
        version_tag = daily[-1]["package_version"] if daily else "baseline-only"
        cache_key = "locked-" + self.lock_key(lock)
        cached = self._merged.get(cache_key)
        if cached is not None:
            return cached
        if not daily:
            return self.baseline

        cache = self._cache_dir or __import__("tempfile").mkdtemp(
            prefix="r01vr-merged-"
        )
        target = __import__("pathlib").Path(cache) / f"lock-{version_tag}"
        if not (target / "manifest.json").is_file():
            for sub in ("daily", "events", "factors", "etf_limit"):
                src = __import__("pathlib").Path(self._baseline_root) / sub
                if src.is_dir():
                    shutil.copytree(src, target / sub, dirs_exist_ok=True)
            merged_manifest = dict(self.baseline.manifest)
            latest_manifest = None
            for e in daily:
                droot = __import__("pathlib").Path(e["absolute_path"])
                dmanifest = self._json.loads(
                    (droot / "manifest.json").read_text(encoding="utf-8")
                )
                latest_manifest = dmanifest
                self._merge_one_increment(target, droot, dmanifest)
            assert latest_manifest is not None
            merged_manifest["package_id"] = f"{self.baseline.package_id}+{version_tag}"
            merged_manifest["package_version"] = version_tag
            # p03 J4E1/J5E1 绑定合同：capture_binding 按此重建/前缀兼容恢复
            # （versions 与逐项 manifest_sha256s 平行清单，哈希不可缺）
            merged_manifest["daily_increment_versions"] = [
                d["package_version"] for d in daily
            ]
            merged_manifest["daily_increment_manifest_sha256s"] = [
                d["manifest_sha256"] for d in daily
            ]
            merged_manifest["baseline_manifest_sha256"] = self._baseline_sha
            merged_manifest["input_lock"] = {
                "daily": [d["package_version"] for d in daily],
                "locked": True,
            }
            merged_manifest["data_end"] = latest_manifest.get("data_as_of")
            (target / "manifest.json").write_text(
                self._json.dumps(merged_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        pkg = load_etf_input_package(target)
        self._merged[cache_key] = pkg
        return pkg

    @staticmethod
    def _merge_one_increment(target, droot, dmanifest: dict) -> None:
        """把一个日增量目录合并进 target（按各自日期列去重追加）。"""
        import shutil

        import pandas as pd

        codes = [sym["code"] for sym in dmanifest.get("symbols", [])]
        for sub in ("daily", "events", "factors", "etf_limit"):
            dsrc = __import__("pathlib").Path(droot) / sub
            if not dsrc.is_dir():
                continue
            (target / sub).mkdir(parents=True, exist_ok=True)
            date_col = "event_date" if sub == "events" else "trade_date"
            for code in codes:
                f = dsrc / f"{code}.parquet"
                if not f.is_file():
                    continue
                dst = target / sub / f"{code}.parquet"
                if dst.is_file():
                    base_df = pd.read_parquet(dst)
                    day_df = pd.read_parquet(f)
                    keep = ~base_df[date_col].astype(str).isin(
                        day_df[date_col].astype(str)
                    )
                    out = pd.concat(
                        [base_df[keep].reset_index(drop=True), day_df],
                        ignore_index=True,
                    )
                    out.sort_values(date_col).reset_index(drop=True).to_parquet(
                        dst, index=False
                    )
                else:
                    shutil.copy(f, dst)

    # -- 合并 -------------------------------------------------------------

    def _daily_entries_sorted(self) -> list[tuple[str, dict, dict]]:
        """注册表全部日增量条目（按版本日期升序）。"""
        out = []
        for uri, e in self._registry_entries().items():
            out.append((uri, e, {}))
        return sorted(out, key=lambda t: str(t[1].get("package_version", "")))

    def _calendar_open(self, d: date) -> bool | None:
        """日包 calendar.parquet 判定并市开市日；None=日历未覆盖。

        日包携带全量 SSE 交易日历（1990-12 起），供基线之后日期的
        休市/无交易日分类（不再把周末/节假日误报为 data_blocked）。
        """
        if getattr(self, "_cal", None) is None:
            import pandas as pd

            self._cal = {}
            for _uri, entry, _ in self._daily_entries_sorted():
                f = (
                    __import__("pathlib").Path(entry["absolute_path"])
                    / "calendar.parquet"
                )
                if f.is_file():
                    df = pd.read_parquet(f)
                    self._cal.update({
                        str(r["cal_date"]): int(r["is_open"]) for _, r in df.iterrows()
                    })
            # A calendar is known before future prices. The private observed
            # snapshot extends history without admitting any future market bars.
            from pathlib import Path
            import hashlib
            registry_file = Path(self._registry_path)
            registry = self._json.loads(registry_file.read_text()) if registry_file.is_file() else {}
            snapshot = registry.get("calendar_snapshot")
            self.calendar_binding = None
            if snapshot:
                raw = Path(snapshot["path"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != snapshot["sha256"]:
                    raise ValueError("calendar_snapshot_checksum_mismatch")
                self.calendar_binding = {k: snapshot[k] for k in ("sha256", "obtained_at", "source")}
                payload = self._json.loads(raw)["data"]
                for values in payload["items"]:
                    row = dict(zip(payload["fields"], values))
                    if row["exchange"] == "SSE":
                        self._cal[str(row["cal_date"])] = int(row["is_open"])
        key = d.strftime("%Y%m%d")
        if key in self._cal:
            return self._cal[key] == 1
        return None

    def _merged_package_all(self) -> EtfInputPackage:
        """基线 + 全部已发布非修订日增量 → 单一账本输入视图（未冻结场景）。

        - 修订包（revised）不参与（只服务修订轨迹）；
        - 已冻结运行走 ``_merged_locked``（清单锁定，不重取最新）；
        - 缓存键=最新可入清单日版本；后续新 d 包发布后重建（决策幂等
          不受影响：逐 session 只读当日行情/事件）；
        - 信号/月末判断需要"下一交易日"在场：合并全部已发布增量保证
          日历完整（decision 日为最新发布日时 next=None 属包边界语义）。
        """
        import shutil

        from backend.services.simulation.replay.etf_input_package import (
            load_etf_input_package,
        )

        entries = self._lockable_entries()  # 非修订、路径/manifest 完整
        if not entries:
            return self.baseline
        latest_version = entries[-1]["package_version"]
        cached = self._merged.get(latest_version)
        if cached is not None:
            return cached

        cache = self._cache_dir or __import__("tempfile").mkdtemp(
            prefix="r01vr-merged-"
        )
        target = __import__("pathlib").Path(cache) / f"baseline-v2+{latest_version}"
        if not (target / "manifest.json").is_file():
            for sub in ("daily", "events", "factors", "etf_limit"):
                src = __import__("pathlib").Path(self._baseline_root) / sub
                if src.is_dir():
                    shutil.copytree(src, target / sub, dirs_exist_ok=True)
            merged_manifest = dict(self.baseline.manifest)
            latest_manifest = None
            for e in entries:
                droot = __import__("pathlib").Path(e["absolute_path"])
                dmanifest = self._json.loads(
                    (droot / "manifest.json").read_text(encoding="utf-8")
                )
                latest_manifest = dmanifest
                self._merge_one_increment(target, droot, dmanifest)
            assert latest_manifest is not None
            merged_manifest["package_id"] = (
                f"{self.baseline.package_id}+{latest_version}"
            )
            merged_manifest["package_version"] = latest_version
            # p03 J4E1/J5E1 绑定合同：capture_binding 按此重建/前缀兼容恢复
            merged_manifest["daily_increment_versions"] = [
                e["package_version"] for e in entries
            ]
            merged_manifest["daily_increment_manifest_sha256s"] = [
                e["manifest_sha256"] for e in entries
            ]
            merged_manifest["baseline_manifest_sha256"] = self._baseline_sha
            merged_manifest["daily_increment_of"] = latest_manifest.get("package_uri")
            merged_manifest["data_end"] = latest_manifest.get("data_as_of")
            (target / "manifest.json").write_text(
                self._json.dumps(merged_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        pkg = load_etf_input_package(target)
        self._merged = {latest_version: pkg}
        return pkg


def _load_p02_publisher():
    """按路径加载 p02 的 ``scripts/publish_r01_daily_inputs.py``（非包内模块）。

    只用其冻结的 ``evaluate_data_readiness`` 纯函数；加载失败显式报错
    （不静默退回 stub 冒充真实链路）。
    """
    import importlib.util

    from backend.services.simulation.virtual_run import gating as _self

    path = (
        __import__("pathlib").Path(_self.__file__).resolve().parents[4]
        / "scripts"
        / "publish_r01_daily_inputs.py"
    )
    spec = importlib.util.spec_from_file_location("r01_p02_daily_publisher", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod
