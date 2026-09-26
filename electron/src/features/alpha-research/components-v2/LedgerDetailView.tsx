/**
 * R01 账本明细视图（H1.2）：按日期查看持仓/现金/应收/权益/估值可信度、
 * 订单三态数量+费用+拒因（缺失 vs 不适用区分）、净值与回撤（单位/起点/
 * 区间/费用口径）、标记（fixture/未准入/工程回放 vs 历史研究；非 fixture
 * ≠真实成交）。四种导出格式经公共适配层（ledgerAdapter）同一入口消费。
 */
import React, { useEffect, useMemo, useState } from "react";
import { Alert, Empty, Select, Table, Tag, Tooltip } from "antd";
import { FileText } from "lucide-react";
import ReactECharts from 'echarts-for-react';
import { ledgerPerformance } from './ledgerPerformance';
import {
  AdapterFormatError,
  classifyRunKinds,
  evidenceToView,
  fixtureConsistency,
  identifyExportFormat,
  legacyFixtureView,
  normalizeView,
  type LedgerDay,
  type LedgerView,
} from "./ledgerAdapter";
import { researchAgent } from "../services-v2/researchAgent";
import { FixtureBadge, NotReadyBadge } from "./R01ProjectView";

function relativeUri(uri: string): string {
  return uri.startsWith("node://")
    ? uri.split(`/workspace/`)[1] || uri.split("/").slice(3).join("/")
    : uri;
}

function MissingValue({ field }: { field: string }) {
  return (
    <Tooltip title={`该账本导出缺失字段 ${field}（不填零）`}>
      <Tag color="volcano">缺失</Tag>
    </Tooltip>
  );
}

function naValue() {
  return <span className="text-muted-foreground">—（不适用）</span>;
}

function numOr(v: number | null | undefined, field: string, na = false) {
  if (v === null) return na ? naValue() : <MissingValue field={field} />;
  if (v === undefined) return <MissingValue field={field} />;
  return <span>{v}</span>;
}

const kindColor: Record<string, string> = {
  工程回放: "orange",
  历史研究: "geekblue",
  持续虚拟运行: "purple",
  真实交易: "red",
  未知: "default",
};

export default function LedgerDetailView({
  node,
  caseId,
  artifact,
  showCurve = false,
}: {
  node: string;
  caseId: string;
  artifact: { name: string; uri: string; fixture?: boolean; not_ready?: boolean; sha256?: string };
  showCurve?: boolean;
}) {
  const [raw, setRaw] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [date, setDate] = useState<string>("");
  const [openOriginal, setOpenOriginal] = useState(false);
  const [original, setOriginal] = useState("");

  useEffect(() => {
    let stopped = false;
    setRaw(null);
    setError('');
    (async () => {
      try {
        const blob = await researchAgent.file(node, caseId, relativeUri(artifact.uri));
        const bytes = await blob.arrayBuffer();
        if (artifact.sha256) {
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
            .map(b => b.toString(16).padStart(2, '0')).join('');
          if (hash !== artifact.sha256) throw new Error('账本原件 SHA256 与登记不一致');
        }
        const parsed = JSON.parse(new TextDecoder().decode(bytes));
        if (stopped) return;
        setRaw(parsed);
      } catch (exc) {
        if (!stopped) setError(exc instanceof Error ? exc.message : "账本文件不可读（节点受控目录）");
      }
    })();
    return () => {
      stopped = true;
    };
  }, [node, caseId, artifact.uri, artifact.sha256]);

  const format = useMemo(() => (raw ? identifyExportFormat(raw) : null), [raw]);
  const conversion = useMemo(() => {
    if (!raw || format !== "evidence") return { view: null, error: "" };
    try {
      return { view: evidenceToView(raw), error: "" };
    } catch (exc) {
      return { view: null, error: exc instanceof Error ? exc.message : String(exc) };
    }
  }, [raw, format]);
  const adapterError = conversion.error;

  const view = conversion.view;
  const normalization = useMemo(() => {
    if (adapterError || format !== "view") return { view: null, error: '' };
    try {
      return { view: normalizeView(raw), error: '' };
    } catch (exc) {
      return { view: null, error: exc instanceof Error ? exc.message : String(exc) };
    }
  }, [raw, format, adapterError]);
  const normalized = normalization.view;
  const viewError = normalization.error;
  const days: LedgerDay[] | null = useMemo(() => {
    if (adapterError || viewError) return null;
    if (format === "view") return normalized?.days ?? null;
    if (view) return view.days;
    return null;
  }, [raw, view, format, adapterError, viewError, normalized]);

  useEffect(() => {
    if (days?.length) setDate(days[days.length - 1].date);
  }, [days]);

  if (error) return <Alert type="error" message={error} />;
  if (!raw) return <p className="text-xs text-muted-foreground mt-1">读取账本明细…</p>;

  if (format === "unknown") {
    return (
      <Alert
        type="error"
        showIcon
        data-testid="ledger-unknown-format"
        message="无法识别的账本导出格式（unknown）"
        description="该文件既不是 export_view（view_schema）、也不是原生 evidence（banner+session+equity+orders）、
也不是旧工程样例（day_summaries）。页面显式拒绝展示，不做猜测或以零值填充；请通过
R01Ledger.export_view()/export_evidence() 公共入口生成。"
      />
    );
  }

  if (format === "legacy_fixture") {
    const legacy = legacyFixtureView(raw);
    return (
      <div className="mt-1" data-testid="ledger-legacy-compat">
        <div className="flex flex-wrap gap-2 items-center mb-1">
          <Tag color="orange">旧工程样例兼容展示（legacy_fixture）</Tag>
          <span className="text-xs text-muted-foreground">
            attempt-1 形状（day_summaries），只读兼容；数值不与新 view 混算
          </span>
        </div>
        <pre className="bg-secondary/30 rounded p-2 text-xs whitespace-pre-wrap max-h-72 overflow-auto">
          {JSON.stringify(legacy.daySummaries.slice(0, 3), null, 1).slice(0, 4000)}
          {legacy.daySummaries.length > 3 ? `\n…（共 ${legacy.daySummaries.length} 日）` : ""}
        </pre>
      </div>
    );
  }

  if (adapterError) {
    return (
      <Alert
        type="error"
        showIcon
        data-testid="ledger-adapter-rejected"
        message="evidence 原件形状不符，公共适配层显式拒绝转换（不静默填空）"
        description={adapterError}
      />
    );
  }

  if (viewError) {
    return (
      <Alert
        type="error"
        showIcon
        data-testid="ledger-view-schema-rejected"
        message="view 导出版本未知，页面显式拒绝（不猜测字段布局）"
        description={viewError}
      />
    );
  }

  if (!days || !days.length) {
    return <Empty description="账本导出无逐日记录" />;
  }

  const activeView: LedgerView = format === "view" ? normalized! : view!;
  const day = days.find((d) => d.date === date) ?? days[days.length - 1];
  const navs = days.map((d) => d.nav).filter((v): v is number => typeof v === "number");
  const kinds = classifyRunKinds(activeView);
  const fixtureCheck = fixtureConsistency(activeView, artifact.fixture);
  const session = (activeView.session ?? {}) as Record<string, unknown>;
  const firstDay = days[0].date;
  const lastDay = days[days.length - 1].date;
  const performance = ledgerPerformance(days, session.initial_cash);
  const { totalReturn, totalFees, maxDrawdown: maxDd } = performance;

  return (
    <div className="mt-1 space-y-2" data-testid="ledger-detail-view">
      <div className="flex flex-wrap gap-2 items-center" data-testid="ledger-run-kinds">
        {kinds.map((k) => (
          <Tooltip key={k} title={`运行类别（按数据源字段分立判别）：${k}`}>
            <Tag color={kindColor[k]}>{k}</Tag>
          </Tooltip>
        ))}
        {artifact.fixture && <FixtureBadge compact />}
        {artifact.not_ready && <NotReadyBadge />}
        {format === "evidence" && (
          <Tag color="purple">经公共适配层转换（evidence 原件 → view）</Tag>
        )}
        {!fixtureCheck.consistent && (
          <Alert type="warning" message={fixtureCheck.detail} className="w-full" />
        )}
        <span className="text-xs text-muted-foreground">
          本视图为研究账本回放明细；非 fixture ≠ 真实成交，与实盘/交易记录无关
        </span>
      </div>
      {showCurve && <div data-testid="ledger-history-chart">
        <p className="text-sm">{firstDay} ～ {lastDay} · {days.length.toLocaleString()} 个交易日 · {performance.orderCount} 张订单</p>
        <p className="text-sm">初始本金 {performance.initial ?? '未提供'} 元 · 期末权益 {performance.nav.at(-1) ?? '缺失'} 元 · 累计收益 {totalReturn === null ? '无法计算' : `${(totalReturn * 100).toFixed(2)}%`} · 最大回撤 {maxDd === null ? '无法计算' : `${(maxDd * 100).toFixed(2)}%`}</p>
        <ReactECharts style={{ height: 330 }} option={{
          animation: false,
          tooltip: { trigger: 'axis', valueFormatter: (v: number) => v == null ? '缺失' : Number(v).toFixed(2) },
          legend: { data: ['账户权益（元）', '回撤（%）'] },
          grid: { left: 75, right: 55, bottom: 65, top: 35 },
          xAxis: { type: 'category', data: days.map(d => d.date), boundaryGap: false },
          yAxis: [{ type: 'value', scale: true, name: '元' }, { type: 'value', max: 0, name: '%' }],
          dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 10 }],
          series: [
            { name: '账户权益（元）', type: 'line', showSymbol: false, data: performance.nav, connectNulls: false },
            { name: '回撤（%）', type: 'line', showSymbol: false, yAxisIndex: 1, data: performance.drawdown, connectNulls: false },
          ],
        }} onEvents={{ click: (p: { name: string }) => { if (days.some(d => d.date === p.name)) setDate(p.name); } }} />
        <p className="text-xs text-muted-foreground">历史模拟结果，收益从初始本金计算，含首日损益与账本费用；金额单位为元。下方可检索日期查看原始持仓和订单。</p>
      </div>}
      <div className="flex flex-wrap gap-3 items-center text-xs">
        <span>查看日期：</span>
        <Select
          aria-label="账本日期"
          showSearch
          size="small"
          value={day.date}
          style={{ minWidth: 140 }}
          onChange={setDate}
          options={days.map((d) => ({ value: d.date, label: d.date }))}
        />
        <button
          className="text-primary inline-flex items-center gap-1"
          data-testid="ledger-open-original"
          onClick={() => {
            if (openOriginal) {
              setOpenOriginal(false);
              return;
            }
            researchAgent
              .file(node, caseId, relativeUri(artifact.uri))
              .then(async (blob) => {
                setOriginal((await blob.text()).slice(0, 100000));
                setOpenOriginal(true);
              });
          }}
        >
          <FileText size={12} /> {openOriginal ? "收起原件" : "打开/核对原件"}
        </button>
      </div>
      {openOriginal && (
        <pre className="bg-secondary/30 rounded p-2 text-xs whitespace-pre-wrap max-h-72 overflow-auto">
          {original}
        </pre>
      )}
      <div className="text-xs space-y-1">
        <p>
          现金：{numOr(day.cash, "cash")} · 应收红利：
          {numOr(day.dividend_receivable, "dividend_receivable")} · 持仓市值：
          {numOr(day.market_value, "market_value")} · 权益 nav：
          {numOr(day.nav, "nav")}
        </p>
        <p>
          估值可信度：
          {day.valuation_reliable === undefined ? (
            <MissingValue field="valuation_reliable" />
          ) : day.valuation_reliable ? (
            <Tag color="green">可信</Tag>
          ) : (
            <Tag color="red">不可信（缺行情估值冻结/无市价，数值沿用最近有效标记）</Tag>
          )}
          {day.risk?.status ? ` · 当日风险态：${day.risk.status}` : ""}
        </p>
      </div>
      <details open>
        <summary className="cursor-pointer text-xs">
          持仓（{day.positions.length}，{day.date} 收盘）
        </summary>
        <Table
          size="small"
          pagination={false}
          dataSource={day.positions}
          rowKey="symbol"
          columns={[
            { title: "标的", dataIndex: "symbol" },
            {
              title: "数量",
              dataIndex: "qty",
              render: (v: number | null) => numOr(v, "qty"),
            },
            {
              title: "可用数量",
              dataIndex: "available_qty",
              render: (v: number | null) => numOr(v, "available_qty"),
            },
            {
              title: "均价",
              dataIndex: "avg_cost",
              render: (v: number | null) => numOr(v, "avg_cost"),
            },
            {
              title: "收盘标记",
              dataIndex: "last_mark",
              render: (v: number | null) => numOr(v, "last_mark"),
            },
            {
              title: "标记来源",
              dataIndex: "mark_source",
              render: (v: string | undefined, row: { stale_days?: number }) =>
                v === undefined ? (
                  <MissingValue field="mark_source" />
                ) : v === "carry_forward" ? (
                  <Tooltip title={`陈旧标记：连续 ${row.stale_days ?? "?"} 日缺行情，沿用最近有效市价（不伪造收盘）`}>
                    <Tag color="orange">
                      carry_forward（陈旧 {row.stale_days ?? "?"} 日）
                    </Tag>
                  </Tooltip>
                ) : v === "unavailable" ? (
                  <Tooltip title="该持仓从未有市价：last_mark=0 表示缺失，不是价格">
                    <Tag color="red">unavailable（缺失）</Tag>
                  </Tooltip>
                ) : (
                  <Tag color="green">{v}</Tag>
                ),
            },
            {
              title: "市值",
              dataIndex: "market_value",
              render: (v: number | null) => numOr(v, "market_value"),
            },
          ].map((c) => ({ ...c, width: undefined }))}
        />
      </details>
      <details>
        <summary className="cursor-pointer text-xs">
          订单（当日 {day.orders.length} 笔；三态数量+费用+拒因）
        </summary>
        <Table
          size="small"
          pagination={false}
          dataSource={day.orders}
          rowKey="client_order_id"
          columns={[
            { title: "标的", dataIndex: "symbol" },
            { title: "方向", dataIndex: "side" },
            {
              title: "目标数量",
              dataIndex: "qty_target",
              render: (v: number | null) => numOr(v, "qty_target"),
            },
            {
              title: "成交数量",
              dataIndex: "qty_filled",
              render: (v: number | null) => numOr(v, "qty_filled", true),
            },
            {
              title: "剩余数量",
              dataIndex: "qty_remaining",
              render: (v: number | null) => numOr(v, "qty_remaining", true),
            },
            {
              title: "成交均价",
              dataIndex: "avg_fill_price",
              render: (v: number | null) => numOr(v, "avg_fill_price", true),
            },
            {
              title: "费用",
              dataIndex: "fees",
              render: (v: number | null) => numOr(v, "fees", true),
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (v: string) => <Tag>{v}</Tag>,
            },
            {
              title: "拒单/未成交原因",
              dataIndex: "reject_reason",
              render: (v: string | null) =>
                v === null ? naValue() : <span className="text-red-500">{v}</span>,
            },
            {
              title: "理想/实际权重",
              render: (_, o) => (
                <span>
                  {numOr(o.ideal_weight ?? null, "ideal_weight", true)} /{" "}
                  {numOr(o.realized_weight ?? null, "realized_weight", true)}
                </span>
              ),
            },
          ]}
        />
      </details>
      <details>
        <summary className="cursor-pointer text-xs">净值与回撤（口径说明）</summary>
        <div className="text-xs space-y-1">
          <p>
            单位：元 · 初始本金={performance.initial ?? "缺失"} · 首日收盘 {firstDay} nav={navs[0] ?? "缺失"} · 区间：
            {firstDay}~{lastDay}（{days.length} 个账本日）
          </p>
          <p>
            费用口径：订单费用已计入 nav（{String(session.commission_rate ?? "会话未记录费率")}{" "}
            费率，最低 {String(session.commission_min ?? "—")}）；净值含现金+应收红利+持仓市值
          </p>
          <p>
            区间收益：
            {totalReturn === null ? (
              <MissingValue field="区间收益（不足两日）" />
            ) : (
              `${(totalReturn * 100).toFixed(4)}%`
            )}{" "}
            · 最大回撤：
            {maxDd === null ? (
              <MissingValue field="最大回撤（不足两日）" />
            ) : (
              `${(maxDd * 100).toFixed(4)}%`
            )}{" "}
            · 累计费用：{totalFees === null ? '缺失' : totalFees.toFixed(4)} 元 · 换手：
            <Tooltip title="输入不足以按冻结口径计算换手（无冻结换手定义的成交额基数）">
              <Tag>未知（null）</Tag>
            </Tooltip>
          </p>
        </div>
      </details>
      {format === "evidence" && (
        <p className="text-xs text-muted-foreground">
          适配说明：{view?.adapter_notes?.origin}；{view?.adapter_notes?.triggered_today}
        </p>
      )}
    </div>
  );
}
