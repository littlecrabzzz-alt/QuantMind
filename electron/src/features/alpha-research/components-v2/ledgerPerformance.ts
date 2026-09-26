import type { LedgerDay } from './ledgerAdapter';

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** No deposits/withdrawals in the R01 ledger; include first-day P&L and costs. */
export function ledgerPerformance(days: LedgerDay[], initialCash: unknown) {
  const initial = finite(initialCash) && initialCash > 0 ? initialCash : null;
  const nav = days.map(d => finite(d.nav) && d.nav > 0 ? d.nav : null);
  let peak = initial;
  const drawdown = nav.map(value => {
    if (value === null) return null;
    peak = Math.max(peak ?? value, value);
    return (value / peak - 1) * 100;
  });
  const complete = nav.length > 0 && nav.every(value => value !== null);
  const last = nav.at(-1) ?? null;
  const fees = days.flatMap(d => d.orders.map(o => o.fees));
  return {
    initial, nav, drawdown,
    totalReturn: complete && initial !== null && last !== null ? last / initial - 1 : null,
    maxDrawdown: complete ? -Math.min(0, ...drawdown.filter(finite)) / 100 : null,
    totalFees: fees.every(finite) ? fees.reduce((sum, fee) => sum + fee, 0) : null,
    orderCount: days.reduce((sum, d) => sum + d.orders.length, 0),
  };
}
