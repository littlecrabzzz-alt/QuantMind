import { describe, expect, it } from 'vitest';
import { ledgerPerformance } from './ledgerPerformance';
import type { LedgerDay } from './ledgerAdapter';

const days = (...navs: Array<number | undefined>): LedgerDay[] => navs.map((nav, i) => ({ date: `2026-09-${21 + i}`, nav, positions: [], orders: [] }));

describe('ledger performance from frozen initial capital', () => {
  it('includes first-day costs and loss in both return and high-water drawdown', () => {
    const result = ledgerPerformance(days(90, 99), 100);
    expect(result.totalReturn).toBeCloseTo(-0.01);
    expect(result.maxDrawdown).toBeCloseTo(0.10);
    expect(result.drawdown).toEqual([-9.999999999999998, -1.0000000000000009]);
  });
  it('does not hide missing daily NAV by connecting the surrounding points', () => {
    const result = ledgerPerformance(days(100, undefined, 110), 100);
    expect(result.nav).toEqual([100, null, 110]);
    expect(result.totalReturn).toBeNull();
    expect(result.maxDrawdown).toBeNull();
  });
  it('does not invent initial capital or missing fees', () => {
    const rows = days(100, 110);
    rows[0].orders = [{ fees: null } as LedgerDay['orders'][number]];
    const result = ledgerPerformance(rows, undefined);
    expect(result.totalReturn).toBeNull();
    expect(result.totalFees).toBeNull();
  });
});
