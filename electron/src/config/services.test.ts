import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('deployment server selection', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
    delete (window as any).electronAPI;
  });
  afterEach(() => vi.unstubAllGlobals());

  it('keeps browser requests same-origin with the compatibility shim', async () => {
    await import('../utils/electronCompat');
    const services = await import('./services');
    expect(services.isElectronEnv()).toBe(false);
    expect(services.SERVICE_URLS.API_GATEWAY).toBe('');
  });

  it('recognizes real desktop IPC', async () => {
    (window as any).electronAPI = { getServerUrl: vi.fn(async () => 'http://127.0.0.1:18080') };
    expect((await import('./services')).isElectronEnv()).toBe(true);
  });

  it.each(['quantmind_server_url_v2', 'quantmind_server_url'])('retains %s while offline', async key => {
    const url = 'http://127.0.0.1:18080';
    localStorage.setItem(key, url);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    const services = await import('./services');
    await services.initDynamicServerUrl();
    expect(services.SERVICE_URLS.API_GATEWAY).toBe(url);
    expect(localStorage.getItem('quantmind_server_url_v2')).toBe(url);
    expect(fetch).not.toHaveBeenCalled();
  });
});
