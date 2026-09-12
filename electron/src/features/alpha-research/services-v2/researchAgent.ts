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
}
export interface AgentCase {
  id: string;
  node_id: string;
  status: string;
  error?: string;
  sequence: number;
  created_at: number;
  input: { question: string; subject: string; material: string; model: string };
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
};
