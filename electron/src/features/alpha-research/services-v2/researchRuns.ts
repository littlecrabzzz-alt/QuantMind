import axios, { type AxiosRequestConfig } from 'axios';
import { authService } from '../../../features/auth/services/authService';
import { SERVICE_ENDPOINTS } from '../../../config/services';

export type ResearchKind = 'strategy' | 'method';
export interface ResearchCapabilities {
  ready: boolean; reason?: string; node_id: string | null; owner_scope?: string; environment?: string;
  role?: string; snapshot_id?: string; models: string[];
  base_config?: { split: Record<string, string[]>; features: string[]; portfolio: { initial_capital: number } };
}
export interface ResearchRequest {
  idempotency_key: string; node_id: string; kind: ResearchKind; goal: string;
  hours: number; candidate_limit: number; model: string; expression: string; source_text: string;
  source_run_id?: string; source_experiment_id?: string;
}
export interface Metrics {
  total_return: number; max_drawdown: number; trades: number; transaction_cost: number;
}
export interface FactorMetrics {
  coverage: number; ic: number | null; rank_ic: number | null; rank_icir: number | null;
  positive_rank_ic_fraction: number | null;
}
export interface ResearchExperiment {
  id: string; status: string;
  proposal: { kind: string; hypothesis: string; evidence?: string; factor?: { expression: string }; origin?: string };
  gates?: Record<string, boolean>;
  result?: { summary: { comparison: Record<string, Metrics> }; artifacts: Record<string, string>;
    factor_analysis?: { splits: Record<string, FactorMetrics> } };
}
export interface ResearchRun {
  run_id: string; case_id: string; node_id: string; kind: ResearchKind; goal: string;
  status: string; stage: string; environment: string; snapshot_id: string; model: string;
  started_at: string; updated_at: string; deadline_epoch: number; candidate_limit: number;
  completed_experiments: number; error?: string; report_available?: boolean;
  draft_id?: string; plan_version?: number;
  active?: { id: string; status: string; submitted?: boolean; proposal: ResearchExperiment['proposal'] };
  selection?: { selected: string; reason: string; next_question: string };
  events?: Array<{ at: number; message: string }>;
  experiments?: ResearchExperiment[];
  curves?: Array<{ name: string; values: Array<{ date: string; nav: number }> }>;
  usage?: { calls: number; input_tokens: number; output_tokens: number; retryable: number; unknown_usage: number; amount: number | null };
  base_config?: ResearchCapabilities['base_config'];
}

const base = '/research-runs';
// Pin each request to its authenticated connection; reject late results after a switch.
export async function request(path: string, node?: string, config: AxiosRequestConfig = {}, root = base) {
  const endpoint = String(SERVICE_ENDPOINTS.AI_STRATEGY).replace(/\/+$/, '');
  const token = authService.getAccessToken();
  const response = await axios.request({ ...config, url: `${endpoint}${root}${path}`, timeout: 45000,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(node ? { 'X-Research-Node': node } : {}) } });
  if (endpoint !== String(SERVICE_ENDPOINTS.AI_STRATEGY).replace(/\/+$/, '') || token !== authService.getAccessToken()) {
    throw new Error('研究连接已改变，请刷新当前环境');
  }
  return response;
}
export const researchRuns = {
  capabilities: async (): Promise<ResearchCapabilities> => (await request('/capabilities')).data,
  list: async (node: string): Promise<ResearchRun[]> => (await request('', node)).data.runs,
  detail: async (id: string, node: string): Promise<ResearchRun> => (await request(`/${id}`, node)).data,
  control: async (id: string, node: string, action: 'pause' | 'cancel') =>
    request(`/${id}/controls/${action}`, node, { method: 'POST' }),
  download: async (id: string, node: string, suffix = 'report/download', filename = `research-${id}.md`) => {
    const response = await request(`/${id}/${suffix}`, node, { responseType: 'blob' });
    const url = URL.createObjectURL(response.data);
    const link = document.createElement('a');
    link.href = url; link.download = filename;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

export interface PlanVersion {
  version: number; at: number; run_id: string | null;
  execution?: { hours: number; model: string; candidate_limit: number };
  plan: { title: string; question: string; subject: string; method: string; baselines: string[];
    steps: string[]; outputs: string[]; criteria: string[]; limitations: string[]; questions: string[];
    candidate_limit: number; expression: string; requirements: { dataset: string; executor: string; features: string[]; missing: string[] } };
  admission: { ready: boolean; checks: Array<{ name: string; ready: boolean; detail: string }> };
}
export interface ResearchDraft {
  draft_id: string; node_id: string; revision: number; run_id: string | null; needs_plan: boolean;
  input: { question: string; subject: string; material: string; source_run_id?: string };
  plan: PlanVersion | null; plans?: PlanVersion[]; run?: ResearchRun;
  job: { id: string; mode: string; status: string; error: string | null; deadline: number } | null;
  messages?: Array<{ role: string; content: string; mode?: string; at: number; job_id: string }>;
  inventory?: { baselines?: Record<string, string>; execution_steps?: string[]; snapshot_id: string; market: string; universe: { size: number }; dates: Record<string, string[]>;
    features: string[]; portfolio: { initial_capital: number }; unavailable: string[] };
  discussion_usage?: ResearchRun['usage'];
}
export interface DiscussionMessage { key: string; revision: number; mode: 'ask' | 'plan' | 'revise'; content: string; model: string }
export interface Approval { version: number; action: 'start' | 'resume'; reviewed: true; key: string;
  hours: number; model: string; candidate_limit: number; parent_run_id?: string }
export const researchDrafts = {
  list: async (node: string): Promise<ResearchDraft[]> => (await request('/drafts', node)).data.drafts,
  create: async (node: string, data: ResearchDraft['input']): Promise<ResearchDraft> =>
    (await request('/drafts', node, { method: 'POST', data })).data,
  detail: async (node: string, id: string): Promise<ResearchDraft> => (await request(`/drafts/${id}`, node)).data,
  message: async (node: string, id: string, data: DiscussionMessage): Promise<ResearchDraft> =>
    (await request(`/drafts/${id}/messages`, node, { method: 'POST', data })).data,
  cancelMessage: async (node: string, id: string): Promise<ResearchDraft> =>
    (await request(`/drafts/${id}/messages/cancel`, node, { method: 'POST' })).data,
  execute: async (node: string, id: string, data: Approval): Promise<{ run_id: string; reused: boolean }> =>
    (await request(`/drafts/${id}/execute`, node, { method: 'POST', data })).data,
};
