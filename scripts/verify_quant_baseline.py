"""Verify financial invariants and retain the local baseline's inputs and artifacts."""
from __future__ import annotations

import csv
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def financial_checks(result, initial_capital):
    """Use exported transactions, not the platform's reported performance formulas."""
    if result.get("status") != "completed" or not result.get("trades") or not result.get("equity_curve"):
        raise RuntimeError("Backtest must complete with actual trades and equity observations")
    trades = result["trades"]
    equity = result["equity_curve"]
    if result["total_trades"] != len(trades):
        raise RuntimeError("Trade count does not match exported records")
    dates = [point["date"] for point in equity]
    if dates != sorted(set(dates)):
        raise RuntimeError("Equity dates must be ordered and unique")
    cash = initial_capital
    cash_error = 0.0
    account_error = 0.0
    for day in sorted({t["date"] for t in trades}):
        daily = [t for t in trades if t["date"] == day]
        for trade in daily:
            if trade["action"] not in {"buy", "sell"}:
                raise RuntimeError("Unsupported transaction action")
            if not all(math.isfinite(float(trade[k])) for k in ("totalAmount", "commission", "cash_after", "equity_after", "position_value_after")):
                raise RuntimeError("Non-finite transaction amount")
            cash += (1 if trade["action"] == "sell" else -1) * trade["totalAmount"] - trade["commission"]
            account_error = max(account_error, abs(trade["equity_after"] - trade["cash_after"] - trade["position_value_after"]))
        cash_error = max(cash_error, abs(cash - daily[-1]["cash_after"]))
        if cash < -0.01:
            raise RuntimeError("Negative cash in long-only unlevered baseline")
    values = [initial_capital] + [float(point["value"]) for point in equity]
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise RuntimeError("Invalid account value")
    returns = [current / prior - 1 for prior, current in zip(values, values[1:])]
    total_return = values[-1] / initial_capital - 1
    if cash_error > 0.01 or account_error > 0.01 or abs(total_return - result["total_return"]) > 1e-8:
        raise RuntimeError("Cash/account/return reconciliation failed")
    peak = initial_capital
    max_drawdown = 0.0
    for v in values:
        peak = max(peak, v)
        max_drawdown = min(max_drawdown, v / peak - 1)
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0.0
    sharpe = (statistics.mean(returns) - 0.02 / 252) / volatility * math.sqrt(252) if volatility else None
    return {
        "passed": True, "trading_days": len(equity), "trades": len(trades),
        "cash_reconciliation_max_error": cash_error, "account_reconciliation_max_error": account_error,
        "initial_capital": initial_capital, "final_value": values[-1], "total_return": total_return,
        "benchmark_return": result.get("benchmark_return"),
        "excess_return_percentage_points": (total_return - result["benchmark_return"]) * 100 if result.get("benchmark_return") is not None else None,
        "recorded_transaction_cost": sum(t["commission"] for t in trades),
        "max_drawdown_including_initial_capital": max_drawdown,
        "arithmetic_daily_sharpe": sharpe, "sharpe_risk_free_annual": 0.02,
        "platform_sharpe": result.get("sharpe_ratio"),
    }


def research_decision(checks):
    """Technical completion cannot establish research or paper-trading readiness."""
    excess = checks.get("excess_return_percentage_points")
    comparison = "基准收益缺失，无法比较"
    if excess is not None:
        comparison = f"测试期相对基准收益差 {excess:+.2f} 个百分点"
    return {
        "status": "needs_validation", "technical_checks_passed": checks["passed"],
        "paper_trading_eligible": False, "benchmark_comparison": comparison,
        "reasons": [
            "缺少相同股票池、执行与费用口径的等权及单因子对照",
            "仅验证一个固定测试窗口，尚无独立时期的稳定性证据",
            "尚未完成整个测试期间的历史逐日推理重放",
        ],
        "next_step": "预先固定对照方案；已查看的测试区间标记为研究用，另留最终检验区间",
    }


def verify(out):
    state = read(out / "state.json")
    cfg = read(out / "baseline-config.json")
    training = read(out / "training-status.json")
    inference = read(out / "inference-result.json")
    result = read(out / "backtest-result.json")
    if training["status"] != "completed" or inference.get("effective_model_id") != state["model_id"] or not inference.get("success") or inference.get("fallback_used") or inference.get("signals_count", 0) <= 0:
        raise RuntimeError("Training/inference evidence does not match the experiment")
    signal = result["config"]["signal_meta"]
    if signal.get("effective_model_id") != state["model_id"] or signal.get("fallback_used") or signal.get("score_nan_ratio") != 0:
        raise RuntimeError("Backtest predictions were missing, replaced, or from a different model")
    checks = financial_checks(result, cfg["context"]["initial_capital"])
    checks["model_id"] = state["model_id"]
    checks["test_metrics"] = training["result"]["metadata"]["metrics"]
    decision = research_decision(checks)
    write(out / "research-decision.json", decision)
    write(out / "validation.json", checks)
    export_csv(out / "equity.csv", result["equity_curve"])
    export_csv(out / "trades.csv", result["trades"])
    export_csv(out / "positions.csv", result["positions"])
    if (out / "inference-detail.json").exists():
        detail = read(out / "inference-detail.json")
        signals = detail.get("items", [])
        if len(signals) != inference["signals_count"]:
            raise RuntimeError("Inference export is incomplete")
        export_csv(out / "inference-signals.csv", signals)
        ranked = sorted(signals, key=lambda row: float(row["fusion_score"]), reverse=True)
        export_csv(out / "top20-scores.csv", [
            {"rank": i, "symbol": row["symbol"], "stock_name": row.get("stock_name"),
             "model_score": row["fusion_score"], "data_date": inference["data_trade_date"],
             "prediction_date": inference["prediction_trade_date"]}
            for i, row in enumerate(ranked[:20], 1)
        ])

    # Retain physical copies: future data syncs may replace the live inputs.
    # Snapshots and their manifest are immutable across resume/verification calls.
    manifest_path = out / "input-manifest.json"
    if not manifest_path.exists():
        buffer = timedelta(days=max(7, cfg["target_horizon_days"] + 3))
        start = (date.fromisoformat(cfg["train_start"]) - buffer).strftime("%Y%m%d")
        end = (date.fromisoformat(cfg["test_end"]) + buffer).strftime("%Y%m%d")
        files = []
        for source in ("data/quantdb/6_ml_datasets/l1_factors", "data/quantdb/1_kline_data/daily_backward"):
            for partition in (ROOT / source).glob("dt=*"):
                if start <= partition.name[3:] <= end:
                    files.extend(partition.glob("*.parquet"))
        files.extend(p for p in (ROOT / "db/qlib_data").rglob("*") if p.is_file())
        files.extend(p for p in (ROOT / "data/training_jobs" / state["run_id"]).iterdir() if p.is_file() and p.name != "config.yaml")
        files.extend(ROOT / name for name in (
            "docker/training/train.py", "docker/training/preprocessing.py", "docker/training/parallel_utils.py",
            "backend/services/engine/data_platform/quantdb_factor_reader.py", "scripts/run_quant_baseline.py", "scripts/verify_quant_baseline.py",
        ))
        manifest = []
        for source in sorted(set(files)):
            relative = source.relative_to(ROOT)
            target = out / "snapshot" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            source_hash = sha256(source)
            if sha256(target) != source_hash:
                raise RuntimeError(f"Input changed during snapshot: {relative}")
            manifest.append({"path": str(relative), "bytes": target.stat().st_size, "sha256": source_hash})
        # The native config contains a callback secret. Export only a redacted copy.
        native = ROOT / "data/training_jobs" / state["run_id"] / "config.yaml"
        safe_lines = ["  secret: '[REDACTED_SECRET]'" if line.strip().startswith("secret:") else line for line in native.read_text().splitlines()]
        (out / "effective-training-config.yaml").write_text("\n".join(safe_lines) + "\n")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        diff = subprocess.check_output(["git", "diff", "--", "docker/training/train.py"], cwd=ROOT, text=True)
        (out / "training-code.patch").write_text(diff)
        write(manifest_path, {"git_commit": commit, "files": manifest, "total_bytes": sum(f["bytes"] for f in manifest)})
    else:
        for entry in read(manifest_path)["files"]:
            if sha256(out / "snapshot" / entry["path"]) != entry["sha256"]:
                raise RuntimeError(f"Retained snapshot checksum mismatch: {entry['path']}")
    write(out / "completion.json", {"status": "verified", "research_status": decision["status"], "decision": "research-decision.json", "model_id": state["model_id"], "backtest_id": state["backtest_id"], "validation": "validation.json", "manifest": "input-manifest.json"})
    metrics = checks["test_metrics"]
    retained = read(manifest_path)
    report = f"""# QuantMind 简单量化基线实验

状态：训练、模型注册、独立推理、事件驱动回测及资金核对已完成。用途为研究流程验证。

| 项目 | 结果 |
| --- | --- |
| 训练区间 | {cfg['train_start']} 至 {cfg['train_end']} |
| 验证区间 | {cfg['valid_start']} 至 {cfg['valid_end']} |
| 测试区间 | {cfg['test_start']} 至 {cfg['test_end']}（{checks['trading_days']} 个回测交易日） |
| 模型与因子 | LightGBM，{len(cfg['features'])} 个价量因子 |
| 测试 Rank IC / ICIR | {metrics['test_rank_ic']:.6f} / {metrics['test_rank_icir']:.6f}（ICIR 未年化） |
| 初始 / 期末资金 | {checks['initial_capital']:,.2f} / {checks['final_value']:,.2f} 元 |
| 组合收益 / 沪深300收益 | {checks['total_return']:.2%} / {checks['benchmark_return']:.2%} |
| 收益差 | {checks['excess_return_percentage_points']:.2f} 个百分点 |
| 最大回撤 | {checks['max_drawdown_including_initial_capital']:.2%} |
| 成交 / 记录费用 | {checks['trades']} 笔 / {checks['recorded_transaction_cost']:,.2f} 元 |
| 独立推理评分 | {inference['signals_count']} 条，{inference['data_trade_date']} 数据，{inference['prediction_trade_date']} 生效 |
| 逐日现金核对最大误差 | {checks['cash_reconciliation_max_error']:.10f} 元 |
| 输入及产物快照 | {len(retained['files'])} 个文件，{retained['total_bytes']/1024**3:.2f} GiB |

模型 `{state['model_id']}`；训练任务 `{state['run_id']}`；推理 `{inference['run_id']}`；回测 `{state['backtest_id']}`。

结论：本次流程通过；{decision['benchmark_comparison']}。研究状态为「需要进一步验证」，尚不满足模拟盘准入。详见 [研究结论及缺失证据](research-decision.json)。

## 查看结果

- [净值](equity.csv)、[交易流水](trades.csv)、[逐日持仓](positions.csv)。
- [全部推理评分](inference-signals.csv)、[最高20个模型评分](top20-scores.csv)。评分用于排序，不是预期收益率，平台的固定分数交易标签不作为本实验依据。
- [资金及指标核对](validation.json)、[完整回测响应](backtest-result.json)、[训练响应及日志](training-status.json)。
- [原始配置](baseline-config.json)、[实际训练配置（已隐藏回调密钥）](effective-training-config.yaml)、[输入快照清单](input-manifest.json)。
- `snapshot/` 保存因子、辅助价格、Qlib 数据、训练产物和源文件副本；原项目数据与数据库记录也保留。

## 口径与限制

信号在 T 日收盘后生成，T+1 收盘成交；训练标签为 close(T+2)/close(T+1)-1 的横截面排名。Top20、每日最多淘汰5只，100万元资金，不做空、不加杠杆。正式回测使用事件驱动引擎，未采用已知存在权重问题的快速向量化分支。

费用请求包含佣金、最低佣金、卖出印花税、过户费和冲击成本系数，具体值见 backtest-request.json；成交费用总额来自实际回测流水。

独立按每日算术超额收益、样本标准差及252个交易日计算的 Sharpe 为 {checks['arithmetic_daily_sharpe']:.4f}，含初始资金至首日的收益。平台报告为 {checks['platform_sharpe']:.4f}，采用年复合收益除以波动率等不同口径；不能混用。

主切分裁去训练/验证尾部2个交易日，未使用WFA、Stacking或自动选因子。2026年未进入本次模型拟合或测试绩效窗口；平台附加漂移/风格分析可能读取较新数据，不作为样本外收益证明。

快照在本次执行后立即生成并校验，尚未实施历史财务PIT、退市样本、全部行情质量、全部市场规则或实盘券商验收。未调用真实交易接口。
"""
    if (out / "prediction-validation.json").exists():
        prediction = read(out / "prediction-validation.json")
        report += f"\n## 本次额外预测核对\n\n[独立核对记录](prediction-validation.json)：测试集 {prediction['test_rows']:,} 条预测、{prediction['test_days']} 个交易日，逐日 Rank IC 均值重算为 {prediction['test_daily_rank_ic_mean']:.6f}。独立推理与训练保存的同日预测匹配 {prediction['matched_predictions']} 条，最大分数差 {prediction['max_score_difference']}。该核对结果随本次实验保留。\n"
    (out / "README.md").write_text(report)
    print("Verified and retained:", out, "return:", f"{checks['total_return']:.2%}")
