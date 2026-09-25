/**
 * R01 项目聚合视图（TG-003）：开发进度、数据缺口/覆盖、验收状态、文件、
 * 策略版本与对照组件（A/B1/B2/B3，D/N 预留）。
 *
 * 展示语义（合同约束）：
 * - 未研究指标 value=null + null_reason，绝不填 0；
 * - fixture 工程样例显著标注，不与真实曲线混排；
 * - 未准入（not_ready）产物只留原始证据，不标为正式比较；
 * - 断联（stale）、失败（failed/blocked）如实展示，不伪造成完成。
 * 数据全部来自服务端持久化查询，刷新后保留。
 */
import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button, Empty, Spin, Tag, Tooltip } from "antd";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  PauseCircle,
  RefreshCw,
  ShieldQuestion,
} from "lucide-react";
import ReactECharts from "echarts-for-react";
import {
  researchAgent,
  type ExternalCaseSummary,
  type ProjectOverview,
} from "../services-v2/researchAgent";

const panel = "rounded-xl border border-border bg-card p-4";
const workstreamName: Record<string, string> = {
  P0: "P0 开发与数据",
  A: "A · 固定配置基线",
  B1: "B1 · 趋势过滤",
  B2: "B2 · 相对动量",
  B3: "B3 · 波动率仓位",
  D: "D · 数据 agent（后续预留）",
  N: "N · 数据+新闻 agent（后续预留）",
};
const statusLabel: Record<string, string> = {
  planned: "计划中",
  running: "运行中",
  blocked: "受阻",
  failed: "失败",
  completed: "已完成",
  stale: "断联（长时间无回报）",
  registered: "已登记",
};
const stageLabel: Record<string, string> = {
  proposal: "方案",
  "data-check": "数据检查",
  "development-compare": "开发比较",
  "engineering-validation": "工程验收",
  "independent-verification": "独立核验",
  "forward-observation": "向前观察",
};
const stepLabel: Record<string, string> = {
  done: "完成",
  in_progress: "进行中",
  blocked: "受阻",
  failed: "失败",
};
const nullReasonLabel: Record<string, string> = {
  "not-computed": "未计算",
  "no-data": "无数据",
  "not-applicable": "不适用",
  "pending-verification": "待核验",
};

function FixtureBadge({ compact }: { compact?: boolean }) {
  return (
    <Tag
      color="orange"
      style={{ fontWeight: 700 }}
      data-testid="fixture-badge"
      className={compact ? "" : "text-sm px-3 py-1"}
    >
      工程样例 (fixture)
    </Tag>
  );
}

function NotReadyBadge() {
  return (
    <Tooltip title="项目未通过准入：仅保留原始回报证据，不作为正式比较或已验证成果">
      <Tag color="default" data-testid="not-ready-badge">
        未准入 · 仅原始证据
      </Tag>
    </Tooltip>
  );
}

function MetricValue({
  metric,
}: {
  metric: { metric: string; value: number | null; null_reason?: string; unit: string; basis: string };
}) {
  return (
    <div className="text-sm flex flex-wrap items-baseline gap-2">
      <span className="text-muted-foreground">{metric.metric}</span>
      {metric.value === null ? (
        <span data-testid="metric-null" className="text-muted-foreground">
          {nullReasonLabel[metric.null_reason || ""] || "未计算"}（null）
        </span>
      ) : (
        <span className="font-medium">
          {metric.value} {metric.unit}
        </span>
      )}
      <span className="text-xs text-muted-foreground">口径：{metric.basis}</span>
    </div>
  );
}

function relativeUri(uri: string): string {
  return uri.startsWith("node://")
    ? uri.split(`/workspace/`)[1] || uri.split("/").slice(3).join("/")
    : uri;
}

function CurveCard({
  node,
  caseId,
  uri,
  name,
  fixture,
  notReady,
}: {
  node: string;
  caseId: string;
  uri: string;
  name: string;
  fixture: boolean;
  notReady?: boolean;
}) {
  const [points, setPoints] = useState<Array<{ date: string; nav: number }> | null>(
    null,
  );
  const [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    (async () => {
      try {
        const blob = await researchAgent.file(node, caseId, relativeUri(uri));
        const parsed = JSON.parse(await blob.text());
        const rows = parsed.points || parsed.curve || parsed;
        if (stopped) return;
        if (Array.isArray(rows) && rows.length)
          setPoints(
            rows.map((r: { date: string; nav?: number; value?: number }) => ({
              date: r.date,
              nav: Number(r.nav ?? r.value),
            })),
          );
        else setError("曲线文件为空或格式不符");
      } catch {
        if (!stopped) setError("曲线文件不可读（节点受控目录）");
      }
    })();
    return () => {
      stopped = true;
    };
  }, [node, caseId, uri]);
  return (
    <div
      className={`rounded-lg border-2 p-3 ${
        fixture
          ? "border-orange-400 border-dashed"
          : "border-blue-500 border-solid"
      }`}
      data-testid={fixture ? "fixture-curve-card" : "real-curve-card"}
    >
      <div className="flex flex-wrap items-center gap-2 mb-1">
        {fixture ? <FixtureBadge /> : <Tag color="blue">真实回放数据</Tag>}
        {notReady && <NotReadyBadge />}
        <span className="text-sm font-medium">{name}</span>
        <span className="text-xs text-muted-foreground">
          {fixture
            ? "非真实研究结果，仅用于界面与通路验收"
            : "真实输入包确定性回放派生；未通过正式准入前仅作原始证据展示"}
        </span>
      </div>
      {points ? (
        <ReactECharts
          style={{ height: 200 }}
          option={{
            grid: { left: 55, top: 25, right: 15, bottom: 30 },
            tooltip: { trigger: "axis" },
            xAxis: { type: "category", data: points.map((p) => p.date) },
            yAxis: { type: "value", scale: true, name: "nav" },
            series: [
              {
                type: "line",
                showSymbol: false,
                lineStyle: fixture
                  ? { type: "dashed", color: "#d97706" }
                  : { type: "solid", color: "#2563eb" },
                itemStyle: { color: fixture ? "#d97706" : "#2563eb" },
                data: points.map((p) => p.nav),
              },
            ],
          }}
        />
      ) : error ? (
        <Alert type="warning" message={error} />
      ) : (
        <Spin size="small" />
      )}
    </div>
  );
}

function ReadinessPanel({
  overview,
}: {
  overview: ProjectOverview;
}) {
  const r = overview.readiness;
  if (!r)
    return (
      <Alert
        type="warning"
        showIcon
        message="尚未登记 R01 准入对象（readiness.json）"
        description="数据/开发准入未登记时，非 P0 工作流的外部回报只保留原始证据，不进入正式比较；正式研究派发前须完成 P0 自检与独立验收。"
      />
    );
  const gates: Array<[string, boolean]> = [
    ["数据就绪 data_ready", r.data_ready],
    ["执行就绪 execution_ready", r.execution_ready],
    ["账务核验 accounting_verified", r.accounting_verified],
    ["平台就绪 platform_ready", r.platform_ready],
  ];
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-2">
        {gates.map(([name, ok]) => (
          <Tag key={name} color={ok ? "green" : "red"} icon={ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}>
            {name}：{ok ? "通过" : "未通过"}
          </Tag>
        ))}
        <Tag
          color={
            r.independent_acceptance.status === "passed"
              ? "green"
              : r.independent_acceptance.status === "failed"
                ? "red"
                : "default"
          }
        >
          独立验收：{r.independent_acceptance.status}
        </Tag>
      </div>
      <p className="text-xs text-muted-foreground">
        检查人 {r.checked_by} · 自检时间 {r.self_check_at} · 代码 {r.code_revision.slice(0, 12)} ·
        合同版本 data/ledger/report = {r.contract_versions.data}/{r.contract_versions.ledger}/{r.contract_versions.report}
      </p>
      <p className="text-xs break-all">
        输入包 {r.input_manifest.package_id}（release {r.input_manifest.release_id.slice(0, 16)}…）；
        ETF 输入 {r.etf_input.package_id} v{r.etf_input.package_version} @ {r.etf_input.uri}
      </p>
      {r.blocking_gaps.length > 0 && (
        <Alert
          type="error"
          showIcon
          message={`阻塞缺口（禁止正式研究）：${r.blocking_gaps.join("、")}`}
        />
      )}
      {!overview.ready_for_research && (
        <Alert
          type="warning"
          showIcon
          message="正式准入未通过：研究结果比较入口保持关闭"
          description={`未通过原因：${(overview.admission_reasons || ["unknown"]).join("；")}。
自检通过≠正式准入：独立验收通过且版本绑定一致后才放行；外部回报仍作为原始证据保留，
可查看但不得标记为已验证成果。`}
        />
      )}
    </div>
  );
}

function GroupCard({
  group,
}: {
  group: NonNullable<ProjectOverview["groups"][string]>;
}) {
  const reserved = group.workstream === "D" || group.workstream === "N";
  return (
    <div className={`${panel} space-y-2`} data-testid={`group-${group.workstream}`}>
      <div className="flex items-center justify-between">
        <h4 className="font-medium">{workstreamName[group.workstream] || group.workstream}</h4>
        {group.status === "pending-research" ? (
          <Tag>{reserved ? "预留 · 待派发" : "未研究"}</Tag>
        ) : (
          <Tag color="blue">已回报</Tag>
        )}
      </div>
      {group.strategy_versions.length === 0 && (
        <p className="text-xs text-muted-foreground">尚无策略版本登记。</p>
      )}
      {group.strategy_versions.map((v) => (
        <div key={v.strategy_id} className="text-sm flex items-center gap-2">
          <span className="font-mono text-xs">{v.strategy_id}</span>
          {v.fixture && <FixtureBadge compact />}
          <span className="text-xs text-muted-foreground">
            首见 {v.first_at.slice(0, 19)}
          </span>
        </div>
      ))}
      {group.metrics.slice(-3).map((m, i) => (
        <div key={i} className="border-t border-border pt-2 space-y-1">
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-muted-foreground">
              {m.strategy_id} · {m.at.slice(0, 19)}
            </span>
            {m.fixture && <FixtureBadge compact />}
            {m.not_ready && <NotReadyBadge />}
          </div>
          {m.metrics.map((metric, j) => (
            <MetricValue key={j} metric={metric} />
          ))}
        </div>
      ))}
    </div>
  );
}

function ArtifactEntry({
  node,
  caseId,
  artifact,
}: {
  node: string;
  caseId: string;
  artifact: NonNullable<
    ExternalCaseSummary["artifacts"]
  >[number] & { not_ready_reason?: string };
}) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState("");
  const open = async () => {
    if (content !== null) {
      setContent(null);
      return;
    }
    try {
      const blob = await researchAgent.file(node, caseId, relativeUri(artifact.uri));
      setContent((await blob.text()).slice(0, 200000));
    } catch {
      setError("文件不可读（节点受控目录）");
    }
  };
  const download = async () => {
    const blob = await researchAgent.file(node, caseId, relativeUri(artifact.uri));
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = artifact.name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="text-xs border-b border-border pb-1 mb-1">
      <div className="flex flex-wrap items-center gap-2">
        <FileText size={13} />
        <button
          className="text-primary break-all text-left"
          data-testid="artifact-open"
          onClick={() => void open()}
        >
          {artifact.name}
        </button>
        <span className="text-muted-foreground font-mono">
          {artifact.sha256.slice(0, 12)}…
        </span>
        {artifact.fixture ? <FixtureBadge compact /> : <Tag color="blue">真实</Tag>}
        {artifact.not_ready && <NotReadyBadge />}
        <span className="text-muted-foreground">来源 run：{artifact.source_run_id}</span>
        <Button size="small" onClick={() => void download()}>
          下载
        </Button>
      </div>
      {content !== null && (
        <pre className="bg-secondary/30 rounded p-2 mt-1 whitespace-pre-wrap max-h-80 overflow-auto">
          {content}
        </pre>
      )}
      {error && <span className="text-red-500">{error}</span>}
      {/replay-evidence|positions|orders/i.test(artifact.name + artifact.kind) && (
        <ReplayEvidenceInline node={node} caseId={caseId} artifact={artifact} />
      )}
    </div>
  );
}

interface ReplayDayRecord {
  date?: string;
  trade_date?: string;
  cash?: number | Record<string, unknown>;
  nav?: number;
  equity?: number | number[] | Record<string, unknown>;
  positions?: Array<Record<string, unknown>>;
  orders?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

function ReplayEvidenceInline({
  node,
  caseId,
  artifact,
}: {
  node: string;
  caseId: string;
  artifact: { name: string; uri: string };
}) {
  const [data, setData] = useState<{ days: ReplayDayRecord[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    (async () => {
      try {
        const blob = await researchAgent.file(node, caseId, relativeUri(artifact.uri));
        const parsed = JSON.parse(await blob.text());
        const days: ReplayDayRecord[] =
          parsed.days || parsed.day_summaries || parsed.summaries || [];
        if (stopped) return;
        if (days.length) setData({ days });
        else setError("证据文件缺少逐日记录（days）");
      } catch {
        if (!stopped) setError("证据文件不可读或不是合法 JSON");
      }
    })();
    return () => {
      stopped = true;
    };
  }, [node, caseId, artifact.uri]);
  if (error) return <div className="text-muted-foreground mt-1">{error}</div>;
  if (!data) return <div className="text-muted-foreground mt-1">读取回放明细…</div>;
  const last = data.days[data.days.length - 1];
  const positions = (last.positions || []) as Array<Record<string, unknown>>;
  const orders = data.days.flatMap((d) =>
    ((d.orders || []) as Array<Record<string, unknown>>).map(
      (o) => ({ ...o, _date: d.date || d.trade_date }) as Record<string, unknown>,
    ),
  );
  const navRows = data.days.filter((d) => d.nav !== undefined);
  return (
    <div className="mt-1 space-y-2" data-testid="replay-evidence-detail">
      <details open>
        <summary className="cursor-pointer">
          持仓 / 现金（{last.date || last.trade_date} 收盘）
        </summary>
        <table className="w-full text-xs my-1">
          <thead>
            <tr className="text-muted-foreground">
              <th className="text-left">标的</th>
              <th className="text-right">数量</th>
              <th className="text-right">收盘价</th>
              <th className="text-right">市值</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => (
              <tr key={i} className="border-t border-border">
                <td>{String(p.symbol || p.code || "")}</td>
                <td className="text-right">{String(p.qty ?? p.quantity ?? "")}</td>
                <td className="text-right">{String(p.close ?? p.price ?? "")}</td>
                <td className="text-right">{String(p.market_value ?? p.value ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs">
          现金：{typeof last.cash === "number" ? last.cash : JSON.stringify(last.cash)} ·
          权益/净值：{String(last.nav ?? last.equity ?? "")}
        </p>
      </details>
      <details>
        <summary className="cursor-pointer">订单（全部 {orders.length} 笔）</summary>
        <table className="w-full text-xs my-1">
          <thead>
            <tr className="text-muted-foreground">
              <th className="text-left">日期</th>
              <th className="text-left">标的</th>
              <th className="text-left">方向</th>
              <th className="text-right">数量</th>
              <th className="text-right">价格</th>
              <th className="text-left">状态</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o, i) => (
              <tr key={i} className="border-t border-border">
                <td>{String(o._date || "")}</td>
                <td>{String(o.symbol || o.code || "")}</td>
                <td>{String(o.side || o.action || "")}</td>
                <td className="text-right">{String(o.qty ?? o.quantity ?? "")}</td>
                <td className="text-right">{String(o.price ?? o.fill_price ?? "")}</td>
                <td>{String(o.status || "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
      <details>
        <summary className="cursor-pointer">逐日净值（{navRows.length} 日）</summary>
        <table className="w-full text-xs my-1">
          <tbody>
            {navRows.map((d, i) => (
              <tr key={i} className="border-t border-border">
                <td>{String(d.date || d.trade_date)}</td>
                <td className="text-right">nav={String(d.nav)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function ExternalCasePanel({
  node,
  caseId,
  summary,
}: {
  node: string;
  caseId: string;
  summary: ExternalCaseSummary;
}) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-2 items-center">
        <Tag color={summary.stale ? "orange" : summary.execution_status === "failed" ? "red" : "blue"}>
          {statusLabel[summary.execution_status] || summary.execution_status}
        </Tag>
        <Tag>证据阶段：{stageLabel[summary.evidence_stage] || summary.evidence_stage}</Tag>
        <Tag>{workstreamName[summary.workstream] || summary.workstream}</Tag>
        <Tooltip title="研究执行状态与实盘/交易运行状态互不挂接；running 仅指研究运行">
          <Tag color="default">研究执行状态（非交易）</Tag>
        </Tooltip>
        {summary.stop_requested && (
          <Tag color="orange" icon={<PauseCircle size={12} />}>
            已请求外部停止（待外部确认，平台不伪造已停止）
          </Tag>
        )}
        {Object.entries(summary.risk_pending).map(([eventId, risk]) => (
          <Button
            key={eventId}
            size="small"
            danger
            icon={<ShieldQuestion size={12} />}
            onClick={() => researchAgent.confirmResume(node, caseId, eventId)}
          >
            确认风险恢复（{risk.risk_line}）
          </Button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        多次有界运行 {summary.attempts} 次 · 事件 applied/stale/error ={" "}
        {summary.events_applied}/{summary.events_stale}/{summary.events_error} ·
        最近回报 {summary.last_event_at?.slice(0, 19) || "无"}
        {summary.data?.data_as_of ? ` · 数据截止 ${summary.data.data_as_of}` : ""}
      </p>
      <div className="text-xs space-y-1">
        <p>
          当前步骤：
          {summary.current_step
            ? `${summary.current_step.title}（${stepLabel[summary.current_step.status] || summary.current_step.status}，${summary.current_step.at.slice(0, 19)}）`
            : "尚无步骤回报"}
        </p>
        <p>
          下一步：
          {summary.next_step
            ? `${summary.next_step.title}（${stepLabel[summary.next_step.status] || summary.next_step.status}）`
            : "全部已回报步骤完成或无待办"}
        </p>
        <p>
          用量/费用：
          {summary.usage?.values?.length
            ? summary.usage.values
                .map((v) => `${v.metric}=${v.value}${v.unit}（${v.source_run_id}）`)
                .join("；")
            : summary.usage?.note || "未统计"}
        </p>
      </div>
      {summary.runs.map((run) => (
        <details key={run.source_run_id} className="border border-border rounded-lg p-2">
          <summary className="cursor-pointer">
            <span className="font-mono text-xs">{run.source_run_id}</span> ·{" "}
            {statusLabel[run.execution_status] || run.execution_status} · seq≤
            {run.last_seq} · 事件 {run.events} 条
          </summary>
          <p className="text-xs mt-1">
            任务 {run.source_task} · 运行区间 {run.first_seen_at.slice(0, 19)} →{" "}
            {run.last_seen_at.slice(0, 19)}
            {run.data?.input_package_id ? ` · 输入 ${run.data.input_package_id}` : ""} ·
            恢复点：续报从 seq {run.resume_after_seq ?? run.last_seq} + 1 起（重复回报幂等不新增实验）
          </p>
          {run.errors.length > 0 && (
            <pre className="text-xs whitespace-pre-wrap text-red-500 mt-1">
              {run.errors.join("\n")}
            </pre>
          )}
        </details>
      ))}
      {summary.gaps.length > 0 && (
        <div>
          <h4 className="font-medium mb-1">数据缺口</h4>
          {summary.gaps.map((g) => (
            <div key={g.gap_id} className="text-xs">
              <Tag color="volcano">{g.gap_id}</Tag> {g.desc}（回报 {g.count} 次）
            </div>
          ))}
        </div>
      )}
      {summary.artifacts.length > 0 && (
        <div>
          <h4 className="font-medium mb-1">文件 / 证据（可打开原件）</h4>
          {summary.artifacts.map((a, i) => (
            <ArtifactEntry key={i} node={node} caseId={caseId} artifact={a} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function R01ProjectView({
  node,
  connected,
  onOpenCase,
}: {
  node?: string;
  connected: boolean;
  onOpenCase: (id: string) => void;
}) {
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fetchedAt, setFetchedAt] = useState("");
  const load = useCallback(async () => {
    if (!node || !connected) return;
    setBusy(true);
    try {
      const data = await researchAgent.projectOverview(node, "r01");
      setOverview(data);
      setFetchedAt(new Date().toLocaleTimeString());
      setError("");
    } catch (e: any) {
      setError(
        typeof e?.response?.data?.detail === "string"
          ? e.response.data.detail
          : "读取 R01 项目数据失败",
      );
    } finally {
      setBusy(false);
    }
  }, [node, connected]);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);
  return (
    <section className="space-y-4 select-text" data-testid="r01-project-view">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <h1 className="text-2xl font-semibold">R01 项目总览</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            外部执行课题的聚合视图：开发进度、数据缺口与覆盖、验收状态、文件、策略版本与对照组件。
            数据来自服务端持久化，刷新后保留。
          </p>
        </div>
        <Button icon={<RefreshCw size={14} />} loading={busy} onClick={load}>
          刷新
        </Button>
      </div>
      {error && <Alert type="error" message={error} />}
      {!overview && !error && (
        <div className={panel}>
          <Spin />
          <p className="text-sm text-muted-foreground mt-2">正在读取项目数据…</p>
        </div>
      )}
      {overview && (
        <>
          <div className={panel} data-testid="r01-readiness">
            <h3 className="font-medium mb-2 flex items-center gap-2">
              <ShieldQuestion size={16} /> 准入与验收状态
            </h3>
            <ReadinessPanel overview={overview} />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className={panel} data-testid="r01-progress">
              <h3 className="font-medium mb-2">开发进度（P0）</h3>
              {overview.progress.length === 0 ? (
                <Empty description="尚无外部回报步骤" />
              ) : (
                overview.progress.map((p) => (
                  <div key={`${p.step_id}-${p.at}`} className="flex gap-2 text-sm items-center">
                    <Tag
                      color={
                        p.status === "done"
                          ? "green"
                          : p.status === "failed" || p.status === "blocked"
                            ? "red"
                            : "processing"
                      }
                    >
                      {stepLabel[p.status] || p.status}
                    </Tag>
                    <span>{p.title}</span>
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Clock size={11} /> {p.at.slice(0, 19)}
                    </span>
                  </div>
                ))
              )}
            </div>
            <div className={panel} data-testid="r01-gaps">
              <h3 className="font-medium mb-2">数据缺口 / 覆盖</h3>
              {overview.gaps.length === 0 ? (
                <Empty description="无回报缺口记录" />
              ) : (
                overview.gaps.map((g) => (
                  <div key={g.gap_id} className="text-sm flex items-center gap-2">
                    <Tag color={g.blocking ? "red" : "volcano"}>{g.gap_id}</Tag>
                    <span>{g.desc}</span>
                    {g.blocking && <span className="text-xs text-red-500">阻塞正式研究</span>}
                  </div>
                ))
              )}
              {overview.cases
                .filter((c) => c.data?.data_as_of)
                .map((c) => (
                  <p key={c.case_id} className="text-xs text-muted-foreground mt-2">
                    {c.workstream} · 数据截止 {c.data!.data_as_of} · 输入包{" "}
                    {c.data!.input_package_id}
                  </p>
                ))}
            </div>
          </div>
          <div className={panel} data-testid="r01-cases">
            <h3 className="font-medium mb-2">课题与运行（多次有界运行 / 检查点）</h3>
            {overview.cases.length === 0 ? (
              <Empty description="尚未登记外部课题（executor_kind=external）" />
            ) : (
              overview.cases.map((c) => (
                <details
                  key={c.case_id}
                  className="border border-border rounded-lg p-3 mb-2"
                >
                  <summary className="cursor-pointer">
                    <button
                      className="text-primary font-mono text-xs mr-2"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenCase(c.case_id);
                      }}
                    >
                      {c.case_id.slice(0, 12)}…
                    </button>
                    {c.input.question.slice(0, 40)} · {statusLabel[c.execution_status] || c.execution_status}
                    {c.stale && <Tag color="orange">断联</Tag>}
                  </summary>
                  <div className="mt-2">
                    <ExternalCasePanel node={node!} caseId={c.case_id} summary={c} />
                  </div>
                </details>
              ))
            )}
          </div>
          <div>
            <h3 className="font-medium mb-2">对照组件（六组记录）</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {Object.values(overview.groups).map((g) => (
                <GroupCard key={g.workstream} group={g} />
              ))}
            </div>
          </div>
          <div className={panel} data-testid="r01-real-curves">
            <h3 className="font-medium mb-2">真实回放曲线（非 fixture）</h3>
            {overview.cases.flatMap((c) =>
              c.artifacts
                .filter((a) => !a.fixture && /curve|equity|nav/i.test(a.name + a.kind))
                .map((a) => (
                  <CurveCard
                    key={`${c.case_id}-${a.sha256}`}
                    node={node!}
                    caseId={c.case_id}
                    uri={a.uri}
                    name={a.name}
                    fixture={false}
                    notReady={a.not_ready}
                  />
                )),
            )}
            {!overview.cases.some((c) =>
              c.artifacts.some(
                (a) => !a.fixture && /curve|equity|nav/i.test(a.name + a.kind),
              ),
            ) && <Empty description="尚无真实回放曲线；真实与样例曲线分区标注，不混排" />}
          </div>
          <div className={panel} data-testid="r01-fixture">
            <h3 className="font-medium mb-2">工程样例曲线（fixture，P0 验收用）</h3>
            {overview.cases.flatMap((c) =>
              c.artifacts
                .filter((a) => a.fixture && /curve|equity|nav/i.test(a.name + a.kind))
                .map((a) => (
                  <CurveCard
                    key={`${c.case_id}-${a.sha256}`}
                    node={node!}
                    caseId={c.case_id}
                    uri={a.uri}
                    name={a.name}
                    fixture
                    notReady={a.not_ready}
                  />
                )),
            )}
            {!overview.cases.some((c) =>
              c.artifacts.some((a) => a.fixture && /curve|equity|nav/i.test(a.name + a.kind)),
            ) && (
              <Empty description="尚无 fixture 样例曲线产物；样例与真实研究曲线严格隔离" />
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            最近读取 {fetchedAt}（服务端持久化查询；页面刷新后状态保留）
          </p>
        </>
      )}
    </section>
  );
}

export { ExternalCasePanel, FixtureBadge, NotReadyBadge, CurveCard };
