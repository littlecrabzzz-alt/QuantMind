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
  active?: { id: string; status: string; proposal: ResearchExperiment['proposal'] };
  selection?: { selected: string; reason: string; next_question: string };
  events?: Array<{ at: number; message: string }>;
  experiments?: ResearchExperiment[];
  curves?: Array<{ name: string; values: Array<{ date: string; nav: number }> }>;
  usage?: { calls: number; input_tokens: number; output_tokens: number; retryable: number; unknown_usage: number; amount: number | null };
  base_config?: ResearchCapabilities['base_config'];
}

const base = '/research-runs';
// Pin each request to its authenticated connection; reject late results after a switch.
async function request(path: string, node?: string, config: AxiosRequestConfig = {}) {
  const endpoint = String(SERVICE_ENDPOINTS.AI_STRATEGY).replace(/\/+$/, '');
  const token = authService.getAccessToken();
  const response = await axios.request({ ...config, url: `${endpoint}${base}${path}`, timeout: 30000,
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
  create: async (data: ResearchRequest): Promise<ResearchRun> =>
    (await request('', data.node_id, { method: 'POST', data })).data,
  control: async (id: string, node: string, action: 'pause' | 'cancel') =>
    request(`/${id}/controls/${action}`, node, { method: 'POST' }),
  resume: async (id: string, node: string, hours: number, key: string): Promise<ResearchRun> =>
    (await request(`/${id}/continue-window`, node, { method: 'POST', data: { node_id: node, hours, idempotency_key: key } })).data,
  download: async (id: string, node: string, suffix = 'report/download', filename = `research-${id}.md`) => {
    const response = await request(`/${id}/${suffix}`, node, { responseType: 'blob' });
    const url = URL.createObjectURL(response.data);
    const link = document.createElement('a');
    link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
