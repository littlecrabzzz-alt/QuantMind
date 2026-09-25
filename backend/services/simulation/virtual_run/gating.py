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

    def load(self, identity: DailyDataIdentity) -> EtfInputPackage:
        """按冻结身份取输入包（同身份必须返回同内容）。"""


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

    def load(self, identity: DailyDataIdentity) -> EtfInputPackage:
        # stub：同包同内容；真实实现按 registry 按 identity 解析并复验 sha
        if identity.package_id != self._pkg.package_id:
            raise ValueError(
                f"identity.package_id={identity.package_id} 与冻结包 "
                f"{self._pkg.package_id} 不一致（stub 不支持跨包）"
            )
        return self._pkg


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
        # 基线内日期：直接用基线日历判定（回放/补历史场景）
        if baseline.is_trade_date(decision_date):
            provider = StaticPackageProvider(baseline)
            return provider.resolve(decision_date, symbols=symbols, now=now)

        found = self._daily_entry(decision_date)
        if found is None:
            # 未来日期无日包：休市或未发布无法区分 → 显式受阻（不臆造）
            return GateResult(
                status="data_blocked",
                reason=(
                    f"no_daily_package: 注册表无 d{decision_date.strftime('%Y%m%d')} "
                    "日增量包（未发布或休市；runner 无独立日历端点，按受阻处理，"
                    "不用陈旧数据冒充当日已执行）"
                ),
                checks=[GateCheck("daily_package", "unknown", "registry miss")],
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

    def load(self, identity: DailyDataIdentity) -> EtfInputPackage:
        found = self._daily_entry(date.fromisoformat(identity.decision_date))
        if found is None:
            raise ValueError(
                f"注册表无 {identity.package_version}（身份与注册表不一致）"
            )
        return self._merged_package_all()

    # -- 合并 -------------------------------------------------------------

    def _daily_entries_sorted(self) -> list[tuple[str, dict, dict]]:
        """注册表全部日增量条目（按版本日期升序）。"""
        out = []
        for uri, e in self._registry_entries().items():
            out.append((uri, e, {}))
        return sorted(out, key=lambda t: str(t[1].get("package_version", "")))

    def _merged_package_all(self) -> EtfInputPackage:
        """基线 + 注册表全部已发布日增量 → 单一账本输入视图。

        - 缓存键=最新日版本；后续新 d 包发布后重建（决策幂等不受影响：
          逐 session 只读当日行情/事件，追加后续日期不改变已执行日期结果）；
        - 信号/月末判断需要"下一交易日"在场：合并全部已发布增量保证
          日历完整（decision 日为最新发布日时 next=None 属包边界语义）。
        """
        import hashlib
        import shutil

        import pandas as pd

        from backend.services.simulation.replay.etf_input_package import (
            load_etf_input_package,
        )

        entries = self._daily_entries_sorted()
        if not entries:
            return self.baseline
        latest_version = str(entries[-1][1].get("package_version"))
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
            for _uri, entry, _ in entries:
                droot = __import__("pathlib").Path(entry["absolute_path"])
                dmanifest = self._json.loads(
                    (droot / "manifest.json").read_text(encoding="utf-8")
                )
                latest_manifest = dmanifest
                codes = [sym["code"] for sym in dmanifest.get("symbols", [])]
                for sub in ("daily", "events", "factors", "etf_limit"):
                    dsrc = droot / sub
                    if not dsrc.is_dir():
                        continue
                    (target / sub).mkdir(parents=True, exist_ok=True)
                    for code in codes:
                        f = dsrc / f"{code}.parquet"
                        if not f.is_file():
                            continue
                        dst = target / sub / f"{code}.parquet"
                        if dst.is_file():
                            base_df = pd.read_parquet(dst)
                            day_df = pd.read_parquet(f)
                            keep = ~base_df["trade_date"].astype(str).isin(
                                day_df["trade_date"].astype(str)
                            )
                            out = pd.concat(
                                [base_df[keep].reset_index(drop=True), day_df],
                                ignore_index=True,
                            )
                            out.sort_values("trade_date").reset_index(
                                drop=True
                            ).to_parquet(dst, index=False)
                        else:
                            shutil.copy(f, dst)
            assert latest_manifest is not None
            merged_manifest["package_id"] = (
                f"{self.baseline.package_id}+{latest_version}"
            )
            merged_manifest["package_version"] = latest_version
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
