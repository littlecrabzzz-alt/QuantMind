import { request } from "./researchRuns";

export interface AgentPlan {
  version: number;
  plan: {
    title: string;
    question: string;
    subject: string;
    method: string;
    steps: string[];
    outputs: string[];
    criteria: string[];
    missing: string[];
    allowed_tools: string[];
  };
}
export interface AgentEvent {
  seq: number;
  at: number;
  kind: string;
  name?: string;
  call_id?: string;
  arguments?: Record<string, unknown>;
  output?: string;
  status?: string;
  text?: string;
  message?: string;
  message_id?: string;
  report_kind?: string;
  event_id?: string;
  apply_status?: string;
  platform_seq?: number;
}
export interface AgentCase {
  id: string;
  node_id: string;
  status: string;
  error?: string;
  sequence: number;
  created_at: number;
  executor_kind?: "builtin" | "external";
  external?: ExternalCaseSummary;
  input: {
    question: string;
    subject: string;
    material: string;
    model: string;
    executor_kind?: "builtin" | "external";
    project_key?: string;
    workstream?: string;
  };
  plan: AgentPlan | null;
  plans?: AgentPlan[];
  approval: { version: number; deadline: number; max_jobs: number } | null;
  messages: Array<{
    id: string;
    role: string;
    content: string;
    at: number;
    status: string;
  }>;
  events: AgentEvent[];
  files: Array<{ path: string; size: number; modified_at: number }>;
  jobs: Record<
    string,
    {
      id: string;
      purpose: string;
      status: string;
      command?: string;
      log?: string;
      error?: string;
    }
  >;
  outcomes: Array<{
    id: string;
    kind: string;
    name: string;
    status: string;
    href: string;
    path?: string;
    metrics?: { total_return: number; max_drawdown: number };
    curve?: Array<{ date: string; value: number }>;
  }>;
  todos: Array<{ content: string; status: string }>;
  usage: { input_tokens: number; output_tokens: number };
}
export interface AgentCapabilities {
  ready: boolean;
  reason?: string;
  node_id: string;
  owner_scope: string;
  environment: string;
  models: string[];
  inventory?: {
    snapshot_id: string;
    dates: Record<string, string[]>;
    features: string[];
    limits: string[];
  };
}
// ---- R01 external executor mode（合同镜像：contracts/data-contract.schema.json v2）----
export interface ExternalMetric {
  metric: string;
  value: number | null;
  null_reason?: "not-computed" | "no-data" | "not-applicable" | "pending-verification";
  unit: string;
  basis: string;
}
export interface ExternalRun {
  source_run_id: string;
  source_task: string;
  first_seq: number;
  last_seq: number;
  execution_status: string;
  evidence_stage: string;
  first_seen_at: string;
  last_seen_at: string;
  events: number;
  data: {
    input_package_id?: string;
    source_release_id?: string;
    data_as_of?: string;
    manifest_sha256?: string;
  } | null;
  errors: string[];
}
export interface ExternalCaseSummary {
  project_key: string;
  workstream: string;
  execution_status: string;
  stale: boolean;
  evidence_stage: string;
  runs: ExternalRun[];
  attempts: number;
  events_applied: number;
  events_stale: number;
  events_error: number;
  last_event_at: string | null;
  progress: Array<{
    step_id: string;
    title: string;
    status: string;
    note?: string;
    seq: number;
    at: string;
  }>;
  checks: Array<{ item: string; result: string; evidence_ref: string; at: string }>;
  gaps: Array<{ gap_id: string; desc: string; count: number; last_at: string }>;
  artifacts: Array<{
    name: string;
    kind: string;
    sha256: string;
    uri: string;
    at: string;
    fixture: boolean;
    not_ready: boolean;
  }>;
  metrics: Array<{
    strategy_id: string;
    metrics: ExternalMetric[];
    at: string;
    fixture: boolean;
    not_ready: boolean;
    source_run_id: string;
  }>;
  strategy_versions: Array<{
    strategy_id: string;
    fixture: boolean;
    first_at: string;
    last_at: string;
  }>;
  risk_pending: Record<
    string,
    { ledger_run_id: string; risk_line: string; risk_event_id: string; at: string }
  >;
  risk_history: Array<{
    event_id: string;
    risk_line?: string;
    confirmed_at?: string;
    confirmed_by?: string;
  }>;
  stop_requested: string | null;
  data: ExternalRun["data"];
}
export interface ExternalReportEvent {
  platform_seq: number;
  event_id: string;
  source_task: string;
  source_run_id: string;
  seq: number;
  kind: string;
  execution_status: string;
  evidence_stage: string;
  fixture: boolean;
  source_at: string;
  received_at: string;
  apply_status: string;
  apply_note: string | null;
  confirmed_at: string | null;
  payload: Record<string, unknown>;
}
export interface ReadinessObject {
  schema_version: number;
  project_key: string;
  data_ready: boolean;
  execution_ready: boolean;
  accounting_verified: boolean;
  platform_ready: boolean;
  blocking_gaps: string[];
  checked_by: string;
  evidence_refs: string[];
  input_manifest: { package_id: string; sha256: string; release_id: string };
  etf_input: {
    package_id: string;
    package_version: string;
    manifest_sha256: string;
    node: string;
    uri: string;
  };
  code_revision: string;
  contract_versions: { data: number; ledger: number; report: number };
  self_check_at: string;
  independent_acceptance: {
    status: "pending" | "passed" | "failed";
    at: string | null;
    by: string | null;
  };
  platform_updated_at?: string;
}
export interface ProjectOverview {
  project_key: string;
  readiness: ReadinessObject | null;
  self_check_passes: boolean;
  ready_for_research: boolean;
  independently_accepted: boolean;
  admission_reasons: string[];
  cases: Array<ExternalCaseSummary & { case_id: string; input: AgentCase["input"] }>;
  gaps: Array<{ gap_id: string; desc: string; count: number; blocking: boolean }>;
  blocking_gaps: string[];
  groups: Record<
    string,
    {
      workstream: string;
      status: string;
      cases: string[];
      metrics: ExternalCaseSummary["metrics"];
      strategy_versions: ExternalCaseSummary["strategy_versions"];
    }
  >;
  progress: ExternalCaseSummary["progress"];
  checks: ExternalCaseSummary["checks"];
  last_event_at: string | null;
}
const call = async (
  path: string,
  node?: string,
  method = "GET",
  data?: unknown,
) => (await request(path, node, { method, data }, "/research-agent")).data;
export const researchAgent = {
  capabilities: (): Promise<AgentCapabilities> => call("/capabilities"),
  list: async (node: string): Promise<AgentCase[]> =>
    (await call("/cases", node)).cases,
  create: (
    node: string,
    data: AgentCase["input"] & { key: string },
  ): Promise<AgentCase> => call("/cases", node, "POST", data),
  detail: (node: string, id: string): Promise<AgentCase> =>
    call(`/cases/${id}`, node),
  message: (
    node: string,
    id: string,
    content: string,
    interrupt: boolean,
    key: string,
  ) => call(`/cases/${id}/messages`, node, "POST", { content, interrupt, key }),
  stop: (node: string, id: string) => call(`/cases/${id}/stop`, node, "POST"),
  approve: (
    node: string,
    id: string,
    version: number,
    hours: number,
    max_jobs: number,
    key: string,
  ) =>
    call(`/cases/${id}/approve`, node, "POST", {
      version,
      hours,
      max_jobs,
      key,
      reviewed: true,
    }),
  file: async (node: string, id: string, path: string): Promise<Blob> =>
    (
      await request(
        `/cases/${id}/file`,
        node,
        { params: { path }, responseType: "blob" },
        "/research-agent",
      )
    ).data,
  upload: (
    node: string,
    id: string,
    path: string,
    base64: string,
  ): Promise<{ path: string }> =>
    call(`/cases/${id}/files`, node, "POST", { path, base64 }),
  // R01 外部执行模式（executor_kind=external）
  createExternal: (
    node: string,
    data: AgentCase["input"] & {
      key: string;
      executor_kind: "external";
      project_key: string;
      workstream: string;
    },
  ): Promise<AgentCase> => call("/cases", node, "POST", data),
  externalReports: async (
    node: string,
    id: string,
    sinceSeq = 0,
  ): Promise<{ events: ExternalReportEvent[]; count: number }> =>
    (
      await request(
        `/cases/${id}/external-reports`,
        node,
        { params: { since_seq: sinceSeq } },
        "/research-agent",
      )
    ).data,
  confirmResume: (node: string, id: string, eventId: string) =>
    call(`/cases/${id}/external-reports/${eventId}/confirm-resume`, node, "POST"),
  readiness: (
    node: string,
    projectKey: string,
  ): Promise<{
    readiness: ReadinessObject;
    self_check_passes: boolean;
    ready_for_research: boolean;
    independently_accepted: boolean;
    admission_reasons: string[];
  }> => call(`/projects/${projectKey}/readiness`, node),
  projectOverview: (node: string, projectKey: string): Promise<ProjectOverview> =>
    call(`/projects/${projectKey}`, node),
};
