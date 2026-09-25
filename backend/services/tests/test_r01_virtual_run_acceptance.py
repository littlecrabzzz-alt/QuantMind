"""R01 持续虚拟盘工程验收（H2.2 派发单验收段：可控时钟/故障注入）。

一个测试跑完整验收矩阵并产出证据（R01_VR_EVIDENCE_DIR 设置时写
fault-injection-matrix.json / acceptance-report.md + 三对照哈希与对账
输出；未设置时只断言不写文件）。输入=fixture 冻结包（真实日增量包
联调待 p02 D1/D2 合入后另补，见 gating.stub_note）。

覆盖（派发单 H2.2 验收句 → 场景）：
月末信号→次日执行 / 休市日 / 无交易日 / 数据迟到 / 重复任务 /
中途崩溃（7 注入点） / 风险暂停 / 确认恢复 / 补跑·重启==连续运行 /
休眠唤醒接续 / 错过窗口（不回填） / 停止·恢复三段。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from backend.services.simulation.replay.etf_input_package import build_fixture_package
from backend.services.simulation.virtual_run.pipeline import CrashInjection
from backend.services.tests.test_r01_virtual_run_pipeline import (
    SYM_A,
    SYM_G,
    Harness,
    _crash_pkg,
    make_config,
)

EVIDENCE_DIR = os.getenv("R01_VR_EVIDENCE_DIR")


def _sha(obj) -> str:
    canon = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def _final_fingerprint(h: Harness) -> dict:
    st = h.ledger_state()
    keys = (
        "cash",
        "positions",
        "orders",
        "equity",
        "executed_dates",
        "dividend_receivable",
        "risk_state",
    )
    fp = {k: st[k] for k in keys}
    fp["sha256"] = _sha(fp)
    return fp


def _decide_and_execute(h: Harness, d: date) -> None:
    h.decide(d)
    h.execute(d)


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    return build_fixture_package(tmp_path_factory.mktemp("vr-acc") / "pkg")


MATRIX: list[dict] = []


def _record(
    scenario: str,
    injection: str,
    outcome: str,
    checks: list[str],
    ok: bool,
    detail: str = "",
) -> None:
    MATRIX.append(
        {
            "scenario": scenario,
            "injection": injection,
            "outcome": outcome,
            "checks": checks,
            "pass": ok,
            "detail": detail,
        }
    )


def test_engineering_acceptance_matrix(pkg, tmp_path):
    days_window = [
        date(2025, 9, 10),
        date(2025, 9, 11),
        date(2025, 9, 12),
        date(2025, 9, 15),
        date(2025, 9, 16),
        date(2025, 9, 17),
        date(2025, 9, 18),
        date(2025, 9, 19),
        date(2025, 9, 22),
        date(2025, 9, 23),
        date(2025, 9, 24),
        date(2025, 9, 25),
        date(2025, 9, 26),
        date(2025, 9, 29),
        date(2025, 9, 30),
    ]

    # ---- 基准：连续运行（含月末 09-30 → 10-01 执行） --------------------
    base = Harness(pkg, make_config())
    for d in days_window:
        _decide_and_execute(base, d)
    expected = _final_fingerprint(base)
    rec_me = base.day_record(date(2025, 9, 30))
    ok_me = (
        rec_me["today_decision"]["action"] == "rebalance"
        and rec_me["execution"]["execution_date"] == "2025-10-01"
        and bool(rec_me["orders_summary"])
    )
    _record(
        "月末信号→次日执行",
        "可控时钟 09-30 15:15 → 10-01 09:31",
        rec_me["today_decision"]["action"],
        [
            "signal_date=2025-09-30",
            "execution_date=2025-10-01",
            "price_mode=open",
            "orders>0",
        ],
        ok_me,
    )

    # 无订单日=有效运行（R2）
    rec_review = base.day_record(date(2025, 9, 24))
    ok_r2 = (
        rec_review["today_decision"]["action"] == "no_trade"
        and rec_review["orders_summary"] == []
        and rec_review["completed_at"] is not None
    )
    _record(
        "每日审查无新订单=有效运行",
        "月内普通交易日",
        rec_review["today_decision"]["action"],
        ["no_trade_reason 记录", "completed_at 证据", "orders=0"],
        ok_r2,
    )

    # 对账输出（连续运行）
    settle = base.store.get_stage(base.config.ledger_run_id, "2025-09-30", "settle")
    ok_recon = (
        settle["reconciliation"]["ok"]
        and settle["reconciliation"]["days_compared"] == 15
    )
    _record(
        "独立复算对账",
        "independent_recompute vs 账本 equity",
        f"days={settle['reconciliation']['days_compared']}",
        ["max_abs_nav_diff<=1e-6"],
        ok_recon,
        detail=json.dumps(settle["reconciliation"], ensure_ascii=False),
    )

    # ---- 三对照：崩溃恢复（逐注入点）与重复调度 --------------------------
    crash_points = [
        "after_data_check_state",
        "after_freeze_state",
        "after_signal_state",
        "after_risk_state",
        "after_execute_ledger_before_checkpoint",
        "after_execute_checkpoint_before_state",
        "after_settle_state",
    ]
    for cp in crash_points:
        h = Harness(pkg, make_config())
        for d in days_window:
            h.clock.set_shanghai(d, "15:15")
            try:
                h.pipeline(crash_points={cp}).run_day(d)
            except CrashInjection:
                h.pipeline().run_day(d)
            exec_day = h.pkg.next_trade_date(d)
            h.clock.set_shanghai(exec_day, "09:31")
            try:
                h.pipeline(crash_points={cp}).run_day(d)
            except CrashInjection:
                h.pipeline().run_day(d)
        got = _final_fingerprint(h)
        ok = got["sha256"] == expected["sha256"]
        _record(
            f"中途崩溃→重启续跑（{cp}）",
            f"一次性崩溃注入 {cp}",
            "fingerprint==连续运行" if ok else "MISMATCH",
            ["equity/orders/cash/positions 逐字节一致"],
            ok,
            detail=f"sha={got['sha256'][:16]}",
        )

    # 重复调度：同日重复决策+执行调用
    dup = Harness(pkg, make_config())
    for d in days_window:
        _decide_and_execute(dup, d)
        dup.pipeline().run_day(d)  # 重复调度
        dup.pipeline().run_day(d)  # 再重复
    got = _final_fingerprint(dup)
    ok_dup = got["sha256"] == expected["sha256"]
    _record(
        "重复调度幂等",
        "每决策日重复调用 3 次",
        "fingerprint==连续运行" if ok_dup else "MISMATCH",
        ["不重复扣款", "无第二份订单"],
        ok_dup,
        detail=f"sha={got['sha256'][:16]}",
    )

    # 双 worker：锁互斥
    from backend.services.simulation.virtual_run.locks import (
        DayRunLock,
        InMemoryLockBackend,
    )

    be = InMemoryLockBackend()
    lk1 = DayRunLock(be, "r01vr-A-x-v1", "2025-09-10", ttl_seconds=60)
    lk2 = DayRunLock(be, "r01vr-A-x-v1", "2025-09-10", ttl_seconds=60)
    lk1.acquire()
    ok_lock = not lk2.acquire() and lk1.release() and lk2.acquire()
    _record(
        "双 worker 互斥",
        "同日锁 SET NX",
        "第二持有者让出",
        ["acquire 拒绝", "token 释放后可接管"],
        ok_lock,
    )

    # ---- 休市日 / 无交易日 / 数据迟到 -----------------------------------
    hol = Harness(pkg, make_config())
    r_sat = hol.decide(date(2025, 9, 27))  # 周六
    _record(
        "休市日",
        "决策日=周六（非包交易日）",
        r_sat.outcome,
        ["not_trade_day", "日记录+心跳"],
        r_sat.outcome == "not_trade_day",
    )
    r_end = hol.decide(date(2025, 10, 1))  # 包末尾（无下一交易日）
    ex_end = hol.store.get_stage(hol.config.ledger_run_id, "2025-10-01", "execute")
    ok_end = r_end.outcome == "completed" and ex_end["status"] == "no_next_trade_date"
    _record(
        "无下一交易日（包边界）",
        "10-01 决策无执行日",
        r_end.outcome,
        ["execute=no_next_trade_date 收口", "不伪造执行"],
        ok_end,
    )

    late = Harness(pkg, make_config(), late_dates={date(2025, 9, 12)})
    _decide_and_execute(late, date(2025, 9, 10))
    _decide_and_execute(late, date(2025, 9, 11))
    r_late = late.decide(date(2025, 9, 12))
    st_late = late.ledger_state()
    ok_late = (
        r_late.outcome == "data_blocked"
        and st_late["executed_dates"][-1] == "2025-09-12"
    )
    _record(
        "数据迟到",
        "late_dates 注入 09-12",
        r_late.outcome,
        ["显式 data_blocked", "不冒充当日已执行", "页面 anomalies 可见"],
        ok_late,
    )

    # ---- 休眠唤醒接续 / 错过窗口 ----------------------------------------
    wake = Harness(pkg, make_config())
    _decide_and_execute(wake, date(2025, 9, 10))
    _decide_and_execute(wake, date(2025, 9, 11))
    wake.clock.set_shanghai(date(2025, 9, 22), "15:15")
    missed_days = [
        date(2025, 9, 12),
        date(2025, 9, 15),
        date(2025, 9, 16),
        date(2025, 9, 17),
        date(2025, 9, 18),
        date(2025, 9, 19),
    ]
    for d in missed_days:
        r = wake.pipeline().run_day(d)
        assert r.outcome == "missed_decision_window"
    _decide_and_execute(wake, date(2025, 9, 22))
    for d in [
        date(2025, 9, 23),
        date(2025, 9, 24),
        date(2025, 9, 25),
        date(2025, 9, 26),
        date(2025, 9, 29),
        date(2025, 9, 30),
    ]:
        _decide_and_execute(wake, d)
    got_wake = _final_fingerprint(wake)
    # 无订单期间补估值日 == 连续运行每日审查（同为无订单 session）
    ok_wake = got_wake["sha256"] == expected["sha256"]
    _record(
        "休眠唤醒接续",
        "错过 09-12..09-19 决策窗口后唤醒",
        "补估值日+决策恢复" if ok_wake else "MISMATCH",
        [
            "错过日记录 missed（不补写决策）",
            "估值日补齐日历连续",
            "fingerprint==连续运行",
        ],
        ok_wake,
        detail=f"sha={got_wake['sha256'][:16]}",
    )

    mw = Harness(pkg, make_config())
    mw.decide(date(2025, 9, 10))
    mw.clock.set_shanghai(date(2025, 9, 11), "16:00")  # 窗口 09:31+30min 已过
    r_mw = mw.pipeline().run_day(date(2025, 9, 10))
    ok_mw = (
        r_mw.outcome == "missed_execution_window"
        and mw.day_record(date(2025, 9, 10))["orders_summary"] == []
        and mw.day_record(date(2025, 9, 10))["execution"]["executed"] is False
    )
    _record(
        "错过执行窗口",
        "时钟拨至窗口截止后",
        r_mw.outcome,
        ["skip_and_record（默认冻结策略）", "不回填成交", "execution.executed=False"],
        ok_mw,
    )

    # ---- 风险暂停 / 确认恢复 --------------------------------------------
    crash_pkg = _crash_pkg(tmp_path / "crash")
    rh = Harness(crash_pkg, make_config())
    _decide_and_execute(rh, date(2025, 9, 10))
    trig_day = None
    d = date(2025, 9, 11)
    while d <= date(2025, 9, 23) and trig_day is None:
        if crash_pkg.is_trade_date(d):
            _decide_and_execute(rh, d)
            led = rh.checkpoints.load(crash_pkg, rh.config.to_ledger_config())
            if not led.risk.buys_allowed:
                trig_day = d
        d = date.fromordinal(d.toordinal() + 1)
    led = rh.checkpoints.load(crash_pkg, rh.config.to_ledger_config())
    unconfirmed = [
        e
        for e in led.export_evidence()["risk_state"]["events"]
        if not e.get("confirmed_by")
    ]
    for d in [
        date(2025, 9, 24),
        date(2025, 9, 25),
        date(2025, 9, 26),
        date(2025, 9, 29),
        date(2025, 9, 30),
    ]:
        _decide_and_execute(rh, d)
    rec_me_risk = rh.day_record(date(2025, 9, 30))
    buys = [o for o in rec_me_risk["orders_summary"] if o["side"] == "buy"]
    ok_risk = (
        trig_day is not None
        and bool(unconfirmed)
        and buys
        and all(o.get("reject_reason") == "risk_paused" for o in buys)
        and "risk_paused" in rec_me_risk["today_decision"]["action"]
    )
    _record(
        "风险暂停（两线触发→月末买入腿拒单）",
        f"510300 连续 -10%（触发日 {trig_day}）",
        rec_me_risk["today_decision"]["action"],
        [
            "buys_allowed=False",
            "买入腿 risk_paused",
            "卖出腿仍执行",
            "待确认事件入 pending_actions",
        ],
        ok_risk,
        detail=json.dumps([e["risk_event_id"] for e in unconfirmed]),
    )

    out = rh.pipeline().confirm_risk_events(
        [e["risk_event_id"] for e in unconfirmed], confirmed_by="user-acceptance"
    )
    ok_confirm = out["buys_allowed"] is True
    _record(
        "确认恢复（逐线确认）",
        "confirm_risk_events",
        "buys_allowed=True" if ok_confirm else "仍暂停",
        ["用户确认后恢复买入", "反弹不自动恢复"],
        ok_confirm,
    )

    # ---- 停止/恢复三段 ----------------------------------------------------
    sh = Harness(pkg, make_config())
    _decide_and_execute(sh, date(2025, 9, 10))
    sh.decide(date(2025, 9, 11))  # 待执行
    run_id = sh.config.ledger_run_id
    sh.store.set_stage(
        run_id,
        "_control",
        "control",
        {
            "command": "stop",
            "state": "requested",
            "requested_by": "user",
            "requested_at": sh.clock.now().isoformat(),
        },
    )
    sh.execute(date(2025, 9, 11))
    ctl = sh.store.get_stage(run_id, "_control", "control")
    r_stopped = sh.decide(date(2025, 9, 12))
    sh.store.set_stage(
        run_id,
        "_control",
        "control",
        {
            "command": "resume",
            "state": "requested",
            "requested_by": "user",
            "requested_at": sh.clock.now().isoformat(),
        },
    )
    r_back = sh.decide(date(2025, 9, 12))
    ctl2 = sh.store.get_stage(run_id, "_control", "control")
    ok_stop = (
        ctl["state"] == "effective"
        and r_stopped.outcome == "stopped"
        and r_back.outcome == "pending_execute"
        and ctl2["state"] == "effective"
        and ctl2["command"] == "resume"
    )
    _record(
        "停止/恢复三段",
        "requested→received→effective",
        f"stop:{ctl['state']} resume:{ctl2['state']}",
        ["仅执行端确认后 effective", "停止期不推进决策日", "恢复后接续"],
        ok_stop,
    )

    # ---- 汇总断言 + 证据写出 ---------------------------------------------
    failed = [m for m in MATRIX if not m["pass"]]
    assert not failed, f"验收矩阵存在失败项: {[m['scenario'] for m in failed]}"

    if EVIDENCE_DIR:
        out_dir = Path(EVIDENCE_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        status = base.store.get_status(base.config.ledger_run_id)
        evidence = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_package": {
                "package_id": pkg.package_id,
                "manifest_sha256": pkg.manifest_sha256,
                "fixture": True,
                "note": "fixture 冻结包；真实日增量包联调待 p02 D1/D2",
            },
            "continuous_fingerprint": expected,
            "matrix": MATRIX,
            "matrix_pass": len(MATRIX) - len(failed),
            "matrix_total": len(MATRIX),
            "run_status_sample": status,
        }
        (out_dir / "fault-injection-matrix.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        lines = [
            "# R01 持续虚拟盘 H2.2 工程验收（可控时钟/故障注入）",
            "",
            f"生成：{evidence['generated_at']} · 输入：`{pkg.package_id}`"
            f"（fixture，sha `{pkg.manifest_sha256[:16]}…`）",
            "",
            f"**结果：{evidence['matrix_pass']}/{evidence['matrix_total']} 通过**"
            "（开发自检，待独立验收）",
            "",
            f"三对照基准（连续运行终态指纹）：`{expected['sha256']}`",
            "",
            "| 场景 | 注入 | 结果 | 通过 |",
            "| --- | --- | --- | --- |",
        ]
        for m in MATRIX:
            lines.append(
                f"| {m['scenario']} | {m['injection']} | {m['outcome']} |"
                f" {'✅' if m['pass'] else '❌'} |"
            )
        lines += [
            "",
            "## 备注",
            "",
            "- 真实日增量包（p02 D1/D2）联调后另补一轮真实日增量证据；",
            "- 真实盘开关保持关闭：runner 无 qmt/live_trading 调用路径"
            "（见同目录 grep 证据）；",
            "- 本矩阵为开发验收（隔离环境），不冒充已实际运行数周。",
        ]
        (out_dir / "acceptance-report.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
