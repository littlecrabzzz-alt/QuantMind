/**
 * R01 持续虚拟运行·日常运行页（H2.2-P1，h2-interfaces §4）。
 * 状态可分辨：正常/无须交易/数据受阻/失败/风险暂停/作业暂停/尚未启用/失联（陈旧心跳）。
 * next_run_at 仅来自 runner 报告的已配置调度；三段停止/恢复只显示执行端已写入的阶段，
 * 平台不伪造生效；风险暂停与作业暂停分列；真实盘保持关闭（本页只读展示）。
 */
import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button, Empty, Table, Tag, Tooltip } from "antd";
import { Activity, RefreshCw } from "lucide-react";
import {
  researchAgent,
  type R01RunStatus,
} from "../services-v2/researchAgent";

const panel = "rounded-xl border border-border bg-card p-4";
const stateColor: Record<string, string> = {
  正常: "green",
  无须交易: "blue",
  数据受阻: "volcano",
  失败: "red",
  风险暂停: "magenta",
  作业暂停: "orange",
  尚未启用: "default",
};
const stageLabel: Record<string, string> = {
  requested: "已请求（等待 runner 接收）",
  received: "已接收（待执行端生效确认）",
  effective: "已生效（执行端确认）",
};

function StageTag({ stage, label }: { stage?: { stage: string } | null; label: string }) {
  if (!stage) return <span className="text-muted-foreground text-xs">{label}：—</span>;
  const effective = stage.stage === "effective";
  return (
    <Tooltip title={`三段状态：仅执行端确认后显示生效（当前=${stage.stage}）`}>
      <Tag color={effective ? "green" : "orange"}>{label}：{stageLabel[stage.stage] || stage.stage}</Tag>
    </Tooltip>
  );
}

export default function R01RunStatusPanel({ node }: { node?: string }) {
  const [runs, setRuns] = useState<R01RunStatus[]>([]);
  const [error, setError] = useState("");
  const [fetchedAt, setFetchedAt] = useState("");
  const load = useCallback(async () => {
    if (!node) return;
    try {
      const data = await researchAgent.r01RunStatus(node);
      setRuns(data.runs);
      setFetchedAt(new Date().toLocaleTimeString());
      setError("");
    } catch (e: any) {
      setError(
        typeof e?.response?.data?.detail === "string"
          ? e.response.data.detail
          : "读取持续虚拟运行状态失败",
      );
    }
  }, [node]);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);
  return (
    <div className={panel} data-testid="r01-run-status">
      <div className="flex flex-wrap justify-between items-center gap-2 mb-2">
        <h3 className="font-medium flex items-center gap-2">
          <Activity size={16} /> 持续虚拟运行（日常页）
        </h3>
        <span className="text-xs text-muted-foreground flex items-center gap-2">
          最近读取 {fetchedAt || "…"}
          <Button size="small" icon={<RefreshCw size={12} />} onClick={() => void load()}>
            刷新
          </Button>
        </span>
      </div>
      <p className="text-xs text-muted-foreground mb-2">
        虚拟运行（非实盘；真实盘开关保持关闭）。心跳过期/失联只显示陈旧，不自动判定成败；
        next_run_at 仅来自实际已配置调度，未配置=待启用。
      </p>
      {error && <Alert type="error" message={error} />}
      {!error && !runs.length && (
        <Empty description="尚无持续虚拟运行状态（runner 未接入或未启用；待联调）" />
      )}
      {runs.map((run) => {
        const d = run.platform_derived;
        return (
          <details key={run.ledger_run_id} className="border border-border rounded-lg p-3 mb-2" open>
            <summary className="cursor-pointer text-sm flex flex-wrap gap-2 items-center">
              <span className="font-mono text-xs">{run.ledger_run_id}</span>
              <Tag color={stateColor[d?.display_state ?? ""] || "default"}>
                {d?.display_state ?? run.run_state}
              </Tag>
              {d?.heartbeat_stale && <Tag color="orange">心跳陈旧/失联</Tag>}
              {d?.activation === "pending_activation" && <Tag>尚未启用（待启用）</Tag>}
              <span className="text-xs text-muted-foreground">
                {run.strategy_id} v{run.strategy_version} · {run.group}
              </span>
            </summary>
            <div className="text-xs space-y-2 mt-2">
              <p>
                输入日期：{run.input_date.decision_date}
                {run.input_date.data_as_of ? ` · 数据截止 ${run.input_date.data_as_of}` : ""}
                {run.input_date.obtained_at ? ` · 取得 ${String(run.input_date.obtained_at).slice(0, 19)}` : ""}
                {run.input_date.manifest_sha256 ? ` · manifest ${run.input_date.manifest_sha256.slice(0, 12)}…` : ""}
              </p>
              <p>
                最近心跳：{run.last_heartbeat ? new Date(run.last_heartbeat * 1000).toLocaleString() : "无"}
                {" · "}最近成功执行：
                {run.last_success_at
                  ? typeof run.last_success_at === "number"
                    ? new Date(run.last_success_at * 1000).toLocaleString()
                    : String(run.last_success_at).slice(0, 19)
                  : "无"}
                {" · "}下次运行：
                {d?.next_run_at
                  ? `${d.next_run_at}（来源：${d.next_run_at_source}）`
                  : "待启用（无已配置调度）"}
              </p>
              <p>
                今日决策：{run.today_decision.action}
                {run.today_decision.no_trade_reason
                  ? `（无须交易原因：${run.today_decision.no_trade_reason}——无订单也是有证据的有效运行）`
                  : ""}
                {run.today_decision.reason ? ` · 理由：${run.today_decision.reason}` : ""}
              </p>
              <div className="flex flex-wrap gap-2 items-center">
                <StageTag stage={run.stop_restore?.job_stop} label="停止" />
                <StageTag stage={run.stop_restore?.job_restore} label="恢复" />
                <Tooltip title="风险暂停（两线触发，待确认）与作业暂停（用户/运维停止）分别展示">
                  <Tag color={run.run_state === "paused_risk" ? "magenta" : "default"}>
                    风险态：{run.risk_state.status}
                    {run.risk_state.high_water_mark !== undefined
                      ? ` · HWM ${run.risk_state.high_water_mark}`
                      : ""}
                  </Tag>
                </Tooltip>
                {!!run.risk_state.pending_confirmations?.length && (
                  <Tag color="red">待确认 {run.risk_state.pending_confirmations.length} 项</Tag>
                )}
                {!!run.risk_state.blocked_orders?.length && (
                  <Tag color="volcano">风险拦截订单 {run.risk_state.blocked_orders.length} 笔</Tag>
                )}
              </div>
              <p>
                nav：{run.nav ?? "缺失"} · 回撤：
                {run.drawdown !== undefined ? `${(run.drawdown * 100).toFixed(2)}%` : "缺失"} ·
                现金：{run.cash ?? "缺失"} · 应收红利：{run.dividend_receivable ?? "缺失"}
              </p>
              <details>
                <summary className="cursor-pointer">持仓（{(run.positions ?? []).length}）</summary>
                <Table
                  size="small"
                  pagination={false}
                  dataSource={(run.positions ?? []) as Array<Record<string, unknown>>}
                  rowKey={(r) => String(r.symbol ?? Math.random())}
                  columns={["symbol", "qty", "available_qty", "last_mark", "market_value"].map((k) => ({
                    title: k,
                    dataIndex: k,
                    render: (v: unknown) => (v === undefined ? "缺失" : String(v)),
                  }))}
                />
              </details>
              <details>
                <summary className="cursor-pointer">
                  今日订单（{(run.orders ?? []).length} 笔）
                </summary>
                <Table
                  size="small"
                  pagination={false}
                  dataSource={(run.orders ?? []) as Array<Record<string, unknown>>}
                  rowKey={(r) => String(r.client_order_id ?? r.symbol ?? Math.random())}
                  columns={["symbol", "side", "qty", "price", "status", "reject_reason"].map((k) => ({
                    title: k,
                    dataIndex: k,
                    render: (v: unknown) =>
                      v === null ? "—（不适用）" : v === undefined ? "缺失" : String(v),
                  }))}
                />
              </details>
              {(run.anomalies ?? []).length > 0 && (
                <Alert
                  type="warning"
                  message={`异常/待处置 ${run.anomalies!.length + (run.pending_actions ?? []).length} 项`}
                  description={
                    <pre className="text-xs whitespace-pre-wrap">
                      {[...run.anomalies!, ...(run.pending_actions ?? [])]
                        .map((a) => JSON.stringify(a, null, 0))
                        .join("\n")}
                    </pre>
                  }
                />
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}
