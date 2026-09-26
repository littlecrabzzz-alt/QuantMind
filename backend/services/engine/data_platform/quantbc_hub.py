"""QuantBC 数据中枢 — 区块链/加密货币本地 parquet 读取的单一入口。

复用 QuantDBDataHub 的查询基础设施（DuckDB 连接管理、视图挂载、K线/列
标准化），仅替换数据目录与视图命名空间（qbc_*），避免与其他市场视图串扰。

数据目录：环境变量 QM_QUANTBC_DATA_DIR，默认 data/quantbc/。
目录结构与 QuantDB 对齐（日线 / 指数 / 估值 / 财务 / 标的池）。
"""

from __future__ import annotations

import logging
import hashlib
import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backend.services.engine.data_platform.quantdb_hub import (
    QuantDBDataHub,
    _dt_conditions,
)

logger = logging.getLogger(__name__)

_QUANTBC_DATA_DIR_ENV = "QM_QUANTBC_DATA_DIR"
_QUANTBC_DEFAULT_DATA_DIRS = [
    "/data/quantbc",  # Docker 容器内（挂载点）
    str(Path(__file__).resolve().parents[4] / "data" / "quantbc"),  # 项目根/data/quantbc
]


def _crypto_enabled() -> bool:
    """生产环境通过 ENABLE_CRYPTO=false 屏蔽区块链（默认开启，与 market_adapters 一致）。"""
    raw = os.getenv("ENABLE_CRYPTO", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _resolve_quantbc_data_dir() -> Path:
    # Docker 层屏蔽：ENABLE_CRYPTO=false 时返回不存在路径，quantbc 不可用
    if not _crypto_enabled():
        return Path(_QUANTBC_DATA_DIR_ENV)  # 非目录，不可用
    env_val = os.getenv(_QUANTBC_DATA_DIR_ENV, "").strip()
    if env_val:
        return resolve_quantbc_release_dir(Path(env_val))
    for d in _QUANTBC_DEFAULT_DATA_DIRS:
        p = Path(d)
        if p.is_dir():
            return resolve_quantbc_release_dir(p)
    return Path(_QUANTBC_DEFAULT_DATA_DIRS[-1])


def resolve_quantbc_release_dir(root: str | Path) -> Path:
    """Pin CURRENT once; a broken pointer must not fall back to another dataset."""
    root = Path(root).expanduser().resolve()
    pointer = root / "CURRENT.json"
    if not pointer.exists():
        return root  # Legacy flat datasets remain readable outside research admission.
    current = json.loads(pointer.read_text())
    if current.get("schema_version") != 1:
        raise ValueError("Unsupported QuantBC pointer schema")
    release_id = current.get("release_id")
    if (
        not isinstance(release_id, str) or release_id in {"", ".", ".."}
        or Path(release_id).name != release_id
        or current.get("path") != f"releases/{release_id}"
        or pointer.is_symlink() or (root / "releases").is_symlink()
        or (root / current["path"]).is_symlink()
    ):
        raise ValueError("Invalid QuantBC release pointer")
    release = root / current["path"]
    manifest = release / "manifest.json"
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != current["manifest_sha256"]:
        raise ValueError("QuantBC manifest checksum mismatch")
    load_quantbc_release_manifest(release, require_spot=False)
    return release


def load_quantbc_release_manifest(
    data_dir: str | Path, *, verify_files: bool = False, require_spot: bool = True
) -> dict:
    """Research admits only published spot daily bars closed in UTC."""
    release = Path(data_dir)
    manifest = json.loads((release / "manifest.json").read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("quality"), dict):
        raise ValueError("Invalid QuantBC manifest schema")
    quality = manifest.get("quality") or {}
    symbols = manifest.get("symbols")
    required_columns = {
        "symbol", "time", "open", "high", "low", "close", "volume", "amount",
        "quote_volume", "open_time", "close_time", "available_at", "venue", "product_type",
    }
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "complete"
        or manifest.get("venue") != "binance"
        or manifest.get("frequency") != "1d"
        or manifest.get("timezone") != "UTC"
        or manifest.get("product_type") not in {"crypto_spot", "tokenized_equity_spot"}
        or (require_spot and manifest.get("product_type") != "crypto_spot")
        or manifest.get("release_id") != release.name
        or not isinstance(symbols, list) or not symbols or len(set(symbols)) != len(symbols)
        or not required_columns.issubset(manifest.get("columns") or [])
        or quality.get("status") != "passed" or quality.get("timezone") != "UTC"
        or not isinstance(quality.get("history_complete"), bool)
        or not isinstance(manifest.get("files"), dict) or not manifest["files"]
    ):
        raise ValueError("QuantBC release is not a validated UTC daily spot dataset")
    # Historical bars can support research without proving what was available then.
    # available_at is only the earliest possible availability at the bar boundary.
    if (
        manifest.get("available_at_semantics") != "bar_period_end_lower_bound"
        or manifest.get("point_in_time_verified") is not False
        or manifest.get("history_complete_scope") != "current_public_api_daily_bar_coverage"
    ):
        raise ValueError("QuantBC release lacks the declared historical availability semantics")
    start, end = date.fromisoformat(manifest["data_start"]), date.fromisoformat(manifest["data_end"])
    exclusive = (end + timedelta(days=1)).isoformat()
    coverage = quality.get("symbols") or {}
    if not isinstance(coverage, dict) or any(not isinstance(row, dict) for row in coverage.values()):
        raise ValueError("Invalid QuantBC coverage schema")
    if (
        start > end or end >= datetime.now(timezone.utc).date()
        or manifest.get("end_exclusive") != exclusive or quality.get("end_exclusive") != exclusive
    ):
        raise ValueError("QuantBC release contains unclosed UTC daily bars")
    if set(coverage) != set(symbols) or any(
        row.get("rows", 0) <= 0 or row.get("last") != end.isoformat()
        or any(row.get(field) != 0 for field in ("gaps", "duplicates", "unclosed"))
        for row in coverage.values()
    ) or sum(row["rows"] for row in coverage.values()) != quality.get("rows"):
        raise ValueError("QuantBC daily coverage failed research admission")
    listed = manifest["files"]
    paths = list(release.rglob("*"))
    actual = {str(path.relative_to(release)) for path in paths if path.is_file() and path != release / "manifest.json"}
    if release.is_symlink() or any(path.is_symlink() for path in paths) or actual != set(listed):
        raise ValueError("QuantBC release file inventory mismatch")
    for name, checksum in listed.items():
        path = release / name
        if Path(name).is_absolute() or ".." in Path(name).parts or str(Path(name)) != name:
            raise ValueError("Invalid QuantBC release file path")
        if verify_files and hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"QuantBC source checksum mismatch: {name}")
    if "quality.json" not in listed or json.loads((release / "quality.json").read_text()) != quality:
        raise ValueError("QuantBC quality report differs from its manifest")
    return manifest


def quantbc_derived_dir(data_dir: str | Path) -> Path:
    release = Path(data_dir).resolve()
    manifest = load_quantbc_release_manifest(release)
    root = release.parent.parent if release.parent.name == "releases" else release.parent
    derived = root / "derived" / manifest["release_id"]
    if derived.resolve().is_relative_to((root / "releases").resolve()) or derived.resolve().is_relative_to(release):
        raise ValueError("QuantBC derived output must not point inside raw releases")
    return derived


class QuantBCDataHub(QuantDBDataHub):
    """区块链/加密货币本地 parquet 数据中枢。视图命名空间 qbc_*。"""

    _instance: QuantBCDataHub | None = None
    _instance_lock = threading.Lock()

    def __init__(self, data_dir: str | Path | None = None) -> None:
        release = resolve_quantbc_release_dir(data_dir) if data_dir else _resolve_quantbc_data_dir()
        if (release / "manifest.json").is_file():
            load_quantbc_release_manifest(release, verify_files=True, require_spot=False)
        super().__init__(data_dir=release)

    @classmethod
    def get_instance(cls) -> QuantBCDataHub:
        data_dir = _resolve_quantbc_data_dir()
        if cls._instance is None or cls._instance.data_dir != data_dir:
            with cls._instance_lock:
                if cls._instance is None or cls._instance.data_dir != data_dir:
                    cls._instance = cls(data_dir)
        return cls._instance

    def _mount_views(self, conn) -> None:
        """用 qbc_* 前缀挂载分区视图，避免与其他市场视图冲突。"""
        conn_id = id(conn)
        if conn_id in self._views_mounted_per_conn:
            return
        dd = self._data_dir
        partitioned_views = {
            "qbc_daily_forward": "1_kline_data/daily_forward",
            "qbc_index_daily": "1_kline_data/index_daily",
            "qbc_valuation": "5_technical_derived/valuation",
            "qbc_features_daily": "6_ml_datasets/features_daily",
        }
        for view_name, rel_path in partitioned_views.items():
            full_path = dd / rel_path
            if not full_path.exists():
                continue
            parquet_glob = str(full_path / "**" / "*.parquet")
            try:
                conn.execute(
                    f"CREATE VIEW IF NOT EXISTS {view_name} AS "
                    f"SELECT * FROM read_parquet('{parquet_glob}', hive_partitioning=1, union_by_name=true)"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("创建 DuckDB 视图 %s 失败: %s", view_name, exc)
        self._views_mounted_per_conn.add(conn_id)

    # ---- 区块链查询（视图名带 qbc_ 前缀） ----
    def fetch_daily_kline(self, symbol: str, start, end, *, adjust: str = "qfq"):
        """区块链日线。symbol 为币种交易对（BTCUSDT）。"""
        return self.fetch_daily_kline_batch([symbol], start, end, adjust=adjust)

    def fetch_daily_kline_batch(self, symbols: list[str], start, end, *, adjust: str = "qfq"):
        """批量读取同一 QuantBC 版本，不能继承 A 股 qdb_* 视图。"""
        import pandas as pd

        if not symbols:
            return pd.DataFrame()
        view_name = "qbc_daily_forward"
        if not self._view_exists(view_name):
            frames = [self._read_daily_kline_from_files(symbol, start, end, adjust="qfq") for symbol in symbols]
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        conn = self._get_duck_conn()
        conditions = [f"symbol IN ({', '.join('?' for _ in symbols)})"] + _dt_conditions(start, end)
        where = " AND ".join(conditions)
        df = conn.execute(
            f"SELECT * FROM {view_name} WHERE {where} ORDER BY symbol, dt", list(symbols)
        ).fetchdf()
        return self._normalize_kline(df)

    def fetch_valuation(self, symbol: str | None = None, start=None, end=None):
        """区块链估值快照（按日落盘）。"""
        if not self._view_exists("qbc_valuation"):
            return self._empty_df()
        conn = self._get_duck_conn()
        conditions = []
        if symbol:
            conditions.append(f"symbol = '{symbol}'")
        conditions.extend(_dt_conditions(start, end))
        where = " AND ".join(conditions) if conditions else "1=1"
        df = conn.execute(f"SELECT * FROM qbc_valuation WHERE {where} ORDER BY dt").fetchdf()
        return self._normalize_columns(df)

    def fetch_stock_list(self):
        """区块链标的池（instrument_detail.parquet）。"""
        import pandas as pd

        detail_dir = self._data_dir / "2_base_sector" / "instrument_detail"
        file_path = detail_dir / "instrument_list.parquet"
        if not file_path.exists():
            file_path = detail_dir / "instrument_detail.parquet"
        if not file_path.exists():
            return pd.DataFrame()
        return pd.read_parquet(file_path)

    # ---- 通用数据段读取（分红/财务/评级/持仓等） ----
    DATASET_DIRS = {
        "sector": "2_base_sector/sector",
        "f10": "2_base_sector/f10",
    }

    def fetch_dataset(self, dataset: str, symbol: str | None = None):
        """读取任一数据段（标的级 parquet）。"""
        import pandas as pd

        rel_dir = self.DATASET_DIRS.get(dataset)
        if rel_dir is None:
            return pd.DataFrame()
        d = self._data_dir / rel_dir
        if not d.is_dir():
            return pd.DataFrame()
        if symbol:
            file_path = d / f"{symbol}.parquet"
            if not file_path.exists():
                return pd.DataFrame()
            df = pd.read_parquet(file_path)
        else:
            files = sorted(d.glob("*.parquet"))
            if not files:
                return pd.DataFrame()
            df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        return df

    @staticmethod
    def _empty_df():
        import pandas as _pd

        return _pd.DataFrame()
