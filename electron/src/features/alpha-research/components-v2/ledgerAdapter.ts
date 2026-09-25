/**
 * R01 账本导出公共适配层（H1.1，对齐 p03 artifacts/p03/h1/README.md）。
 *
 * 判别规则（identify_export_format 同序）：
 * - "view"           顶层含 view_schema（export_view 产物，直接消费）
 * - "legacy_fixture" 顶层含 day_summaries（attempt-1 旧工程样例；兼容展示）
 * - "evidence"       顶层含 banner+session+equity+orders（原生审计原件；
 *                    由本适配层转换为 view 等价结构，只重组不改数值）
 * - "unknown"        其余 —— 显式拒绝，不猜测、不静默零值
 *
 * evidence→view 转换：equity 逐日快照 → days（订单按 trade_date 归位、
 * positions 字典列表化、当日风险取快照 risk_status/high_water_mark）。
 * 原件没有的逐日风险触发事件（triggered_today）不做臆造，标记来源说明。
 */

export type ExportFormat = "view" | "evidence" | "legacy_fixture" | "unknown";

export interface LedgerPositionRow {
  symbol: string;
  qty: number;
  avg_cost: number;
  available_qty: number;
  pending_t1_qty?: number;
  last_mark?: number;
  last_mark_date?: string | null;
  stale_days?: number;
  close?: number;
  mark_source?: string;
  market_value?: number;
}

export interface LedgerOrderFill {
  price: number;
  quantity: number;
  total_fee: number;
}

export interface LedgerOrderRow {
  client_order_id: string;
  symbol: string;
  side: string;
  origin?: string;
  status: string;
  qty_target: number | null;
  qty_filled: number | null;
  qty_remaining: number | null;
  avg_fill_price: number | null;
  fees: number | null;
  reject_reason: string | null;
  signal_date?: string | null;
  ideal_weight?: number | null;
  realized_weight?: number | null;
  fills?: LedgerOrderFill[];
  trade_date?: string;
}

export interface LedgerDay {
  date: string;
  cash?: number;
  dividend_receivable?: number;
  market_value?: number;
  nav?: number;
  valuation_reliable?: boolean;
  positions: LedgerPositionRow[];
  orders: LedgerOrderRow[];
  risk?: {
    status?: string;
    high_water_mark?: number;
    triggered_today?: Array<Record<string, unknown>>;
  };
}

export interface LedgerView {
  view_schema: number;
  derived_from: string;
  banner?: string;
  session?: Record<string, unknown>;
  package?: Record<string, unknown>;
  risk_state?: Record<string, unknown>;
  risk_events?: Array<Record<string, unknown>>;
  corporate_actions?: Array<Record<string, unknown>>;
  dividends?: Array<Record<string, unknown>>;
  blocked_dividends?: Array<Record<string, unknown>>;
  days: LedgerDay[];
  adapter_notes?: Record<string, string>;
}

export function identifyExportFormat(obj: unknown): ExportFormat {
  if (typeof obj !== "object" || obj === null) return "unknown";
  const o = obj as Record<string, unknown>;
  if ("view_schema" in o) return "view";
  if ("day_summaries" in o) return "legacy_fixture";
  if ("banner" in o && "session" in o && "equity" in o && "orders" in o)
    return "evidence";
  return "unknown";
}

interface EvidenceSnapshot {
  trade_date?: string;
  cash?: number;
  dividend_receivable?: number;
  market_value?: number;
  nav?: number;
  valuation_reliable?: boolean;
  risk_status?: string;
  high_water_mark?: number;
  positions?: Record<string, LedgerPositionRow>;
}

export class AdapterFormatError extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = "AdapterFormatError";
  }
}

/**
 * evidence 原件的严格校验（对齐 p03 ViewBuildError 语义）：equity/orders
 * 缺失、为 null 或不是数组 => 显式拒绝，绝不静默变空列表。
 */
export function assertValidEvidence(evidence: Record<string, unknown>): void {
  for (const key of ["equity", "orders"] as const) {
    const v = evidence[key];
    if (v === undefined || v === null) {
      throw new AdapterFormatError(`evidence 原件缺少 ${key}（null/undefined），拒绝转换`);
    }
    if (!Array.isArray(v)) {
      throw new AdapterFormatError(`evidence.${key} 不是数组（形状不符），拒绝转换`);
    }
  }
  for (const snap of evidence.equity as unknown[]) {
    if (typeof snap !== "object" || snap === null || !("trade_date" in snap)) {
      throw new AdapterFormatError("evidence.equity 存在无 trade_date 的快照，拒绝转换");
    }
  }
}

export function evidenceToView(evidence: Record<string, unknown>): LedgerView {
  assertValidEvidence(evidence);
  const equity = evidence.equity as EvidenceSnapshot[];
  const orders = evidence.orders as LedgerOrderRow[];
  const days: LedgerDay[] = equity.map((snap) => {
    const date = String(snap.trade_date ?? "");
    return {
      date,
      ...(snap.cash !== undefined ? { cash: snap.cash } : {}),
      ...(snap.dividend_receivable !== undefined
        ? { dividend_receivable: snap.dividend_receivable }
        : {}),
      ...(snap.market_value !== undefined ? { market_value: snap.market_value } : {}),
      ...(snap.nav !== undefined ? { nav: snap.nav } : {}),
      ...(snap.valuation_reliable !== undefined
        ? { valuation_reliable: snap.valuation_reliable }
        : {}),
      positions: Object.entries(snap.positions ?? {}).map(([symbol, p]) => ({
        symbol,
        ...p,
      })),
      orders: orders.filter((o) => String(o.trade_date ?? "") === date),
      risk: {
        status: snap.risk_status,
        high_water_mark: snap.high_water_mark,
        triggered_today: [],
      },
    };
  });
  return {
    view_schema: 1,
    derived_from: "p04 frontend adapter (evidence 原件)",
    banner: evidence.banner as string | undefined,
    session: evidence.session as Record<string, unknown> | undefined,
    package: evidence.package as Record<string, unknown> | undefined,
    risk_state: evidence.risk_state as Record<string, unknown> | undefined,
    risk_events: [],
    corporate_actions: evidence.corporate_actions as
      | Array<Record<string, unknown>>
      | undefined,
    dividends: evidence.dividends as Array<Record<string, unknown>> | undefined,
    blocked_dividends: evidence.blocked_dividends as
      | Array<Record<string, unknown>>
      | undefined,
    days,
    adapter_notes: {
      triggered_today:
        "evidence 原件无逐日风险触发事件列表；此处不臆造，如需触发事件明细请使用 export_view 入口",
      origin: "equity 快照重组 + 订单按 trade_date 归位；数值与原件一致，未做修改",
    },
  };
}

export interface LegacyFixtureView {
  kind: "legacy_fixture";
  daySummaries: Array<Record<string, unknown>>;
  banner?: string;
}

export function legacyFixtureView(obj: Record<string, unknown>): LegacyFixtureView {
  return {
    kind: "legacy_fixture",
    daySummaries: (obj.day_summaries as Array<Record<string, unknown>>) ?? [],
    banner: obj.banner as string | undefined,
  };
}


/**
 * 四类运行状态分立判别（H3 修复 3）：数据源有哪个字段显示哪类，未知显式未知。
 * 判别规则（adapter 文档口径）：
 * - 工程回放：banner 含 "FIXTURE" 或 package.is_fixture===true 或 session.group==="P0"
 * - 历史研究：session.group ∈ A/B1/B2/B3/D/N（研究账本回放）
 * - 持续虚拟运行：session.execution_mode==="continuous_virtual"（字段存在才显示）
 * - 真实交易：session.execution_mode==="live_trading"（字段存在才显示）
 * 以上互不合并；一个视图可同时命中多类时逐类列出；无任何已知字段 => ["未知"]。
 */
export type RunKind = "工程回放" | "历史研究" | "持续虚拟运行" | "真实交易" | "未知";

export function classifyRunKinds(
  view: Pick<LedgerView, "banner" | "session" | "package">,
): RunKind[] {
  const kinds: RunKind[] = [];
  const banner = String(view.banner ?? "");
  const session = (view.session ?? {}) as Record<string, unknown>;
  const pkg = (view.package ?? {}) as Record<string, unknown>;
  const group = String(session.group ?? "");
  if (banner.includes("FIXTURE") || pkg.is_fixture === true || group === "P0") {
    kinds.push("工程回放");
  }
  if (["A", "B1", "B2", "B3", "D", "N"].includes(group)) kinds.push("历史研究");
  if (session.execution_mode === "continuous_virtual") kinds.push("持续虚拟运行");
  if (session.execution_mode === "live_trading") kinds.push("真实交易");
  if (!kinds.length) kinds.push("未知");
  return kinds;
}

/**
 * fixture 语义一致性（H3 修复 4）：原件层（banner FIXTURE / package.is_fixture）
 * 与外层回报层（artifact.fixture）必须同语义；不一致 => 返回冲突说明（页面警示，
 * 不静默取其一）。规则：原件自称工程样例而外层未标 fixture、或原件自称正式研究
 * 账本而外层标 fixture，均为不一致。
 */
export function fixtureConsistency(
  view: Pick<LedgerView, "banner" | "package">,
  outerFixture: boolean | undefined,
): { consistent: boolean; detail: string } {
  if (outerFixture === undefined) {
    return { consistent: false, detail: "外层回报未提供 fixture 标记，无法核对两层语义" };
  }
  const pkg = (view.package ?? {}) as Record<string, unknown>;
  const innerFixture =
    String(view.banner ?? "").includes("FIXTURE") || pkg.is_fixture === true;
  if (innerFixture === outerFixture) {
    return {
      consistent: true,
      detail: innerFixture ? "两层一致：工程样例（fixture）" : "两层一致：非 fixture（正式研究账本）",
    };
  }
  return {
    consistent: false,
    detail: `两层 fixture 语义不一致：原件${innerFixture ? "自称工程样例" : "自称正式研究账本"}，外层回报${outerFixture ? "标 fixture" : "未标 fixture"}；以原件为准展示并警示`,
  };
}
