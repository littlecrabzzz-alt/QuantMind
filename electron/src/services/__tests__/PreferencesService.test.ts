import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PreferencesService } from '../preferences/PreferencesService';

describe('PreferencesService theme', () => {
  let dark: boolean;
  let changes: EventTarget;
  let media: MediaQueryList;
  const unsubscribe: Array<() => void> = [];

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    dark = false;
    changes = new EventTarget();
    media = {
      get matches() { return dark; },
      addEventListener: vi.fn(changes.addEventListener.bind(changes)),
      removeEventListener: vi.fn(changes.removeEventListener.bind(changes)),
    } as unknown as MediaQueryList;
    vi.spyOn(window, 'matchMedia').mockReturnValue(media);
  });

  afterEach(() => {
    unsubscribe.splice(0).forEach(remove => remove());
    vi.restoreAllMocks();
  });

  it('persists and restores dark mode', () => {
    const service = new PreferencesService();
    service.setTheme('dark');
    expect(service.getTheme()).toBe('dark');
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(JSON.parse(localStorage.getItem('user_preferences') || '{}').theme).toBe('dark');
    expect(new PreferencesService().getEffectiveTheme()).toBe('dark');
  });

  it('follows system changes only in auto mode and removes its listener', () => {
    const service = new PreferencesService();
    const observed: string[] = [];
    service.setTheme('auto');
    const remove = service.addListener(() => observed.push(
      document.documentElement.getAttribute('data-theme') || ''
    ));
    unsubscribe.push(remove);
    dark = true;
    changes.dispatchEvent(new Event('change'));
    expect(service.getEffectiveTheme()).toBe('dark');
    expect(observed).toEqual(['dark']);
    service.setTheme('light');
    changes.dispatchEvent(new Event('change'));
    expect(observed).toEqual(['dark', 'light']);
    expect(service.getEffectiveTheme()).toBe('light');
    remove();
    expect(media.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
  });

  it('normalizes invalid stored themes and rejects invalid imports', () => {
    localStorage.setItem('user_preferences', JSON.stringify({ theme: 'broken' }));
    const service = new PreferencesService();
    expect(service.getTheme()).toBe('light');
    expect(service.importPreferences(JSON.stringify({
      ...service.getPreferences(), theme: 'broken',
    }))).toBe(false);
  });
});
