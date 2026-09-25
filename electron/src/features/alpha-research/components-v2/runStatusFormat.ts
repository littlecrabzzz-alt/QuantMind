/**
 * 持续虚拟运行状态显示语义（H2-AC03 修复）：缺失/未知与真实零值三分。
 * 纯函数便于单测与页面同源消费。
 */

/** 数值字段：null/undefined => 缺失/未计算；真实 0 显示 0；不参与运算伪装。 */
export function displayNumber(
  value: number | null | undefined,
  suffix = "",
): string {
  if (value === null || value === undefined) return "缺失/未计算";
  return `${value}${suffix}`;
}

/** 回撤：null/undefined => 缺失/未计算；真实 0 才显示 0.00%。 */
export function displayDrawdown(value: number | null | undefined): string {
  if (value === null || value === undefined) return "缺失/未计算";
  return `${(value * 100).toFixed(2)}%`;
}

export interface ScheduleLike {
  configured: boolean;
  next_run_at?: string | null;
}

/** 调度文案：configured+next_run_at 组合四态（不推测时间）。 */
export function scheduleText(schedule: ScheduleLike | undefined): string {
  if (!schedule || schedule.configured === false) {
    return "待启用（无已配置调度）";
  }
  if (schedule.next_run_at) {
    return `${schedule.next_run_at}（来源：runner 报告的已配置调度 quantmind:r01:vr:schedule）`;
  }
  return "已配置；下一时刻未知/等待日历";
}
