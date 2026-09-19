/**
 * 用户私有股票池（favorites / research）读写。
 * 对接 engine `/api/v1/stock-pools/me/*`，与全局股票池同一套 PoolResolver。
 */

import axios from 'axios';
import { SERVICE_URLS } from '../config/services';
import { authService } from '../features/auth/services/authService';
import type { StockPoolOption } from './stockPoolOptionService';

export const USER_POOL_FAVORITES = 'favorites';
export const USER_POOL_RESEARCH = 'research';

export interface UserPoolDetail {
  pool: StockPoolOption & {
    tenant_id?: string | null;
    owner_user_id?: string | null;
    file_path?: string | null;
    source_kind?: string | null;
    source_ref?: string | null;
  };
  symbols: string[];
  total: number;
  ref: string;
}

const baseURL = () => `${String(SERVICE_URLS.ENGINE_SERVICE || '').replace(/\/+$/, '')}/api/v1`;

function authHeaders() {
  const token = authService.getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function ensureUserPool(
  code: string = USER_POOL_FAVORITES,
  name?: string,
): Promise<UserPoolDetail> {
  const resp = await axios.post(
    `${baseURL()}/stock-pools/me/ensure`,
    { code, name },
    { headers: authHeaders(), timeout: 30000 },
  );
  return resp.data as UserPoolDetail;
}

export async function getUserPool(
  code: string = USER_POOL_FAVORITES,
  opts?: { ensure?: boolean },
): Promise<UserPoolDetail> {
  const resp = await axios.get(`${baseURL()}/stock-pools/me/${encodeURIComponent(code)}`, {
    params: { ensure: opts?.ensure ?? true },
    headers: authHeaders(),
    timeout: 30000,
  });
  return resp.data as UserPoolDetail;
}

export async function listUserPoolSymbols(code: string = USER_POOL_FAVORITES): Promise<string[]> {
  const detail = await getUserPool(code, { ensure: true });
  return Array.isArray(detail.symbols) ? detail.symbols : [];
}

export async function addSymbolToUserPool(
  symbol: string,
  code: string = USER_POOL_FAVORITES,
): Promise<{ added: boolean; symbol: string; symbol_count: number }> {
  const resp = await axios.post(
    `${baseURL()}/stock-pools/me/${encodeURIComponent(code)}/symbols/${encodeURIComponent(symbol)}`,
    null,
    { headers: authHeaders(), timeout: 30000 },
  );
  return resp.data;
}

export async function removeSymbolFromUserPool(
  symbol: string,
  code: string = USER_POOL_FAVORITES,
): Promise<{ removed: boolean; symbol: string; symbol_count: number }> {
  const resp = await axios.delete(
    `${baseURL()}/stock-pools/me/${encodeURIComponent(code)}/symbols/${encodeURIComponent(symbol)}`,
    { headers: authHeaders(), timeout: 30000 },
  );
  return resp.data;
}
