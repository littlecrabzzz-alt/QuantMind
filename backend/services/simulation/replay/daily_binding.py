"""R01 日增量输入绑定与确定性重建（R01P0-J4E1，J3R 复核第 2 项修复）。

合并包身份语义（接口合同附录，见 artifacts/p03/h2/fixes-j4/README.md）：

- checkpoint 绑定 ``input_binding = {baseline: {package_id, manifest_sha256},
  increments: [{package_version, manifest_sha256}, ...]}``——基线包 + **已
  消费日增量的有序清单**（各含哈希）；
- 恢复时**按绑定清单重放合并**得到确定性 package_id（= f"{基线}+{末位
  消费版本}"）：新发布的、未消费的日增量不进入重建，不改变已恢复运行
  的身份；
- 消费新日增量 = 显式阶段：绑定清单追加该增量 → 重建扩展包 → 前缀兼容
  恢复（旧清单是新清单的前缀）→ 运行新日 → 新检查点携带扩展绑定；
- 兼容判定：基线 package_id+manifest_sha256 全等，且 checkpoint 清单是
  提供包清单的**前缀**（逐项版本+哈希相等）；篡改任一哈希/换基线/
  非前缀 → CheckpointPackageMismatch。

重建的合并包 manifest 额外记录 ``daily_increment_versions``（有序清单），
供消费侧（runner/页面）核验链路；注册表沿用节点私有
``~/Library/Application Support/QuantMind/r01/package-registry.json``
（uri→absolute_path，kind=daily_increment）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from backend.services.simulation.replay.etf_input_package import (
    EtfInputPackage,
    EtfInputPackageError,
    load_etf_input_package,
)

DEFAULT_REGISTRY_PATH = (
    Path.home() / "Library/Application Support/QuantMind/r01/package-registry.json"
)

_BASELINE_MARKER = "+"


def _binding_hash(binding: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(binding, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def capture_binding(package: EtfInputPackage) -> dict[str, Any]:
    """从包自身提取输入绑定（已消费日增量清单）。

    - 重建包（含 daily_increment_versions）：按清单逐项取版本+哈希；
    - 旧式合并包（仅 daily_increment_of/package_id 带 +d 后缀）：退化为
      单元素清单（末位版本），基线哈希不可得时置 None（恢复侧对 None
      基线哈希按"无法核验"处理，只允许与同 id 重建包前缀匹配）；
    - 基线包：无增量清单。
    """
    manifest = package.manifest
    baseline_id = str(manifest["package_id"]).split(_BASELINE_MARKER, 1)[0]
    baseline_sha: str | None
    if baseline_id == manifest["package_id"]:
        baseline_sha = package.manifest_sha256
    else:
        baseline_sha = manifest.get("baseline_manifest_sha256")
    versions = manifest.get("daily_increment_versions")
    hashes = manifest.get("daily_increment_manifest_sha256s")
    if not versions:
        suffix = str(manifest["package_id"]).split(_BASELINE_MARKER, 1)[1:]
        versions = suffix if suffix else []
        hashes = None
    increments = []
    for i, v in enumerate(versions):
        sha = hashes[i] if hashes and i < len(hashes) else None
        increments.append({"package_version": v, "manifest_sha256": sha})
    return {
        "baseline": {"package_id": baseline_id, "manifest_sha256": baseline_sha},
        "increments": increments,
    }


def _registry_entries(registry_path: Path) -> dict[str, dict]:  # noqa: C416
    if not registry_path.is_file():
        return {}
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    return dict(data.get("packages") or {})


def _resolve_root(
    entries: dict[str, dict], *, package_id: str | None, version: str | None
) -> tuple[Path, dict]:
    for e in entries.values():
        if package_id is not None and e.get("package_id") == package_id:
            return Path(e["absolute_path"]), e
        if (
            version is not None
            and e.get("kind") == "daily_increment"
            and e.get("package_version") == version
        ):
            return Path(e["absolute_path"]), e
    raise EtfInputPackageError(
        f"注册表未找到输入包（package_id={package_id} version={version}）"
    )


def _normalize_daily_columns(df):
    """合并前把旧式列名（volume/amount 原始单位）规范化为
    vol_shares/amount_cny（真实 v2 基线本就是规范列；工程 fixture 基线
    为旧式列——不规范化会在 concat 后产生 NaN→volume 0→误判停牌）。"""
    import pandas as pd

    if "vol_shares" not in df.columns and "volume" in df.columns:
        df = df.copy()
        df["vol_shares"] = pd.to_numeric(df["volume"], errors="coerce") * 100.0
        df["amount_cny"] = pd.to_numeric(df["amount"], errors="coerce") * 1000.0
        df = df.drop(columns=["volume", "amount"])
    return df


def _merge_rows(dst: Path, src: Path, date_col: str) -> None:
    import pandas as pd

    if not src.is_file():
        return
    if not dst.is_file():
        shutil.copy(src, dst)
        return
    base_df = _normalize_daily_columns(pd.read_parquet(dst))
    day_df = _normalize_daily_columns(pd.read_parquet(src))
    keep = ~base_df[date_col].astype(str).isin(day_df[date_col].astype(str))
    out = pd.concat([base_df[keep].reset_index(drop=True), day_df], ignore_index=True)
    out.sort_values(date_col).reset_index(drop=True).to_parquet(dst, index=False)


def _verify_bound_increments(
    entries: dict[str, dict], increments: list[dict[str, Any]]
) -> None:
    """J6E2：缓存命中路径的期望绑定校验——逐增量比对注册表当前指向包
    的 manifest sha256 与绑定（空绑定哈希项不比对，恢复侧另行拒绝）。"""
    from backend.services.simulation.replay.etf_input_package import (
        sha256_of_file,
    )

    for inc in increments:
        iroot, _ = _resolve_root(
            entries, package_id=None, version=str(inc["package_version"])
        )
        real_sha = sha256_of_file(iroot / "manifest.json")
        bound_sha = inc.get("manifest_sha256")
        if bound_sha and bound_sha != real_sha:
            raise EtfInputPackageError(
                f"日增量 {inc['package_version']} manifest_sha256 不一致："
                f"绑定={bound_sha} 实际={real_sha}（篡改或换包，拒绝；"
                "热缓存命中同样校验）"
            )


def rebuild_bound_package(
    binding: dict[str, Any],
    *,
    registry_path: Path | str | None = None,
    cache_dir: Path | str | None = None,
) -> EtfInputPackage:
    """按绑定清单确定性重建合并包（基线 + 有序已消费日增量）。

    未列入清单的日增量（含新发布者）不参与重建——恢复运行对其不可见。
    产物 manifest 携带 daily_increment_versions 与
    baseline_manifest_sha256；package_id = f"{基线}+{末位版本}"（无增量时
    即基线包原样加载）。
    """
    registry = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH
    entries = _registry_entries(registry)
    baseline = binding.get("baseline") or {}
    increments = list(binding.get("increments") or [])
    if not baseline.get("package_id"):
        raise EtfInputPackageError("input_binding 缺 baseline.package_id")

    if not increments:
        root, _ = _resolve_root(entries, package_id=baseline["package_id"], version=None)
        return load_etf_input_package(
            root,
            expect_manifest_sha256=(
                baseline.get("manifest_sha256")
                if baseline.get("manifest_sha256")
                else None
            ),
        )

    versions = [str(inc["package_version"]) for inc in increments]
    inc_hashes: list[str | None] = [inc.get("manifest_sha256") for inc in increments]
    cache_root = Path(cache_dir) if cache_dir else Path(tempfile.mkdtemp(prefix="r01-bound-"))
    target = cache_root / hashlib.sha256(
        "|".join([baseline["package_id"]] + versions).encode("utf-8")
    ).hexdigest()[:16]
    if not (target / "manifest.json").is_file():
        base_root, _ = _resolve_root(entries, package_id=baseline["package_id"], version=None)
        baseline_pkg = load_etf_input_package(
            base_root,
            expect_manifest_sha256=(
                baseline.get("manifest_sha256") if baseline.get("manifest_sha256") else None
            ),
        )
        merged_manifest = dict(baseline_pkg.manifest)
        merged_manifest["baseline_manifest_sha256"] = baseline_pkg.manifest_sha256
        merged_manifest["daily_increment_versions"] = versions
        data_end = merged_manifest.get("data_end")
        real_hashes: list[str] = []
        for inc, bound_sha in zip(increments, inc_hashes, strict=True):
            iroot, _ = _resolve_root(
                entries, package_id=None, version=str(inc["package_version"])
            )
            # J5E1：绑定哈希非空时强校验（篡改/换包在重建期拒绝）；
            # 同时计算真实哈希记入清单（捕获/恢复均不再出现 None）
            from backend.services.simulation.replay.etf_input_package import (
                sha256_of_file,
            )

            real_sha = sha256_of_file(iroot / "manifest.json")
            if bound_sha and bound_sha != real_sha:
                raise EtfInputPackageError(
                    f"日增量 {inc['package_version']} manifest_sha256 不一致："
                    f"绑定={bound_sha} 实际={real_sha}（篡改或换包，拒绝重建）"
                )
            real_hashes.append(real_sha)
            inc_pkg = load_etf_input_package(iroot, expect_manifest_sha256=real_sha)
            codes = [s["code"] for s in inc_pkg.manifest.get("symbols", [])]
            for sub, date_col in (
                ("daily", "trade_date"),
                ("events", "event_date"),
            ):
                (target / sub).mkdir(parents=True, exist_ok=True)
                # 基线文件首增量时拷贝
                if not any((target / sub).glob("*.parquet")):
                    src_dir = base_root / sub
                    if src_dir.is_dir():
                        shutil.copytree(src_dir, target / sub, dirs_exist_ok=True)
                for code in codes:
                    src = iroot / sub / f"{code}.parquet"
                    if src.is_file():
                        _merge_rows(target / sub / f"{code}.parquet", src, date_col)
            for sub in ("factors", "etf_limit"):
                src_dir = iroot / sub
                if src_dir.is_dir():
                    shutil.copytree(src_dir, target / sub, dirs_exist_ok=True)
            data_end = inc_pkg.manifest.get("data_as_of") or data_end
        merged_manifest["package_id"] = f"{baseline['package_id']}+{versions[-1]}"
        merged_manifest["package_version"] = versions[-1]
        merged_manifest["daily_increment_manifest_sha256s"] = real_hashes
        if data_end:
            merged_manifest["data_end"] = data_end
        (target / "manifest.json").write_text(
            json.dumps(merged_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # J6E2：热缓存命中仍执行期望绑定校验（篡改/换包不因缓存绕过）
    _verify_bound_increments(entries, increments)
    return load_etf_input_package(target)


def binding_compatible(
    package_binding: dict[str, Any], checkpoint_binding: dict[str, Any]
) -> tuple[bool, str]:
    """前缀兼容判定：同基线（id+sha）且 checkpoint 清单是包清单前缀。"""
    pb = (package_binding or {}).get("baseline") or {}
    cb = (checkpoint_binding or {}).get("baseline") or {}
    if pb.get("package_id") != cb.get("package_id"):
        return False, f"基线不一致：checkpoint={cb.get('package_id')} 包={pb.get('package_id')}"
    # J5E1：哈希缺失/为空 → 显式拒绝（不得跳过校验）
    if not cb.get("manifest_sha256") or not pb.get("manifest_sha256"):
        return False, "基线 manifest_sha256 缺失/为空（拒绝：无法核验身份）"
    if pb["manifest_sha256"] != cb["manifest_sha256"]:
        return False, "基线 manifest_sha256 不一致（篡改或换包）"
    cp_incs = list((checkpoint_binding or {}).get("increments") or [])
    pkg_incs = list((package_binding or {}).get("increments") or [])
    if len(cp_incs) > len(pkg_incs):
        return False, f"包增量清单短于 checkpoint 已消费清单（{len(pkg_incs)}<{len(cp_incs)}）"
    for i, cp in enumerate(cp_incs):
        pv = pkg_incs[i]
        if cp.get("package_version") != pv.get("package_version"):
            return False, (
                f"增量清单第 {i} 项版本不一致：checkpoint={cp.get('package_version')}"
                f" 包={pv.get('package_version')}"
            )
        if not cp.get("manifest_sha256") or not pv.get("manifest_sha256"):
            return False, (
                f"增量 {cp.get('package_version')} manifest_sha256 缺失/为空"
                "（拒绝：不得跳过校验）"
            )
        if cp["manifest_sha256"] != pv["manifest_sha256"]:
            return False, f"增量 {cp.get('package_version')} manifest_sha256 不一致（篡改或换包）"
    return True, "ok"


def extend_binding(
    binding: dict[str, Any], new_increment: dict[str, Any]
) -> dict[str, Any]:
    """显式消费新日增量：返回追加后的新绑定（原绑定不动）。"""
    out = json.loads(json.dumps(binding))  # deep copy
    out["increments"] = list(out.get("increments") or []) + [dict(new_increment)]
    return out


def binding_cache_key(binding: dict[str, Any]) -> str:
    return _binding_hash(binding)


def dversion(d: date) -> str:
    return f"d{d.strftime('%Y%m%d')}"
