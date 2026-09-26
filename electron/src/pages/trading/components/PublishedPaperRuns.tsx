import React, { useEffect, useState } from 'react';
import { Alert, Button, Descriptions, Table, Tag } from 'antd';
import { strategyManagementService as service } from '../../../services/strategyManagementService';

const money = (n: unknown) => typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '未产生';
export default function PublishedPaperRuns({ compact = false }: { compact?: boolean }) {
  const [showArchived, setShowArchived] = useState(false);
  const [runs, setRuns] = useState<any[]>([]), [error, setError] = useState('');
  const load = async () => {
    try { setRuns(await service.executionRequest('strategy-paper-runs')); setError(''); }
    catch (e: any) { setError(String(e?.response?.data?.detail || '虚拟运行状态读取失败')); }
  };
  useEffect(() => { void load(); const t = setInterval(() => void load(), 10000); return () => clearInterval(t); }, []);
  if (!runs.length && !error) return compact ? null : <div className="p-6">尚无已冻结的策略账户。请在策略管理中完成公共回测，再冻结版本。</div>;
  return <section className="bg-white border rounded-xl p-4 m-2 space-y-3" data-testid="published-paper-runs">
    <div className="flex justify-between"><h3 className="font-semibold">已冻结策略 · 持续虚拟账户</h3><Button size="small" onClick={() => void load()}>刷新</Button></div>
    {error && <Alert type="error" message={error} />}
    {!compact && <Button size="small" onClick={() => setShowArchived(!showArchived)}>{showArchived ? '隐藏已归档账户' : '查看已归档账户'}</Button>}
    {runs.filter(r => (showArchived && !compact) || r.observation_status !== 'archived').map(r => {
      const ctl = r.control;
      const state = r.observation_status === 'archived' ? '已归档' : r.error ? '运行异常' : ctl?.command === 'stop' && ctl?.state === 'effective' ? '已停止' :
        r.risk?.status === 'paused' ? '风险暂停' : r.last_day?.outcome === 'data_blocked' ? '数据受阻' :
        r.last_day?.outcome === 'completed' ? '已完成最近交易日' : r.last_day?.outcome === 'not_trade_day' ? '休市等待' :
        r.last_day?.outcome ? r.last_day.outcome : '已配置，等待首个决策日';
      const stale = !r.dispatcher_heartbeat || Date.now() - Date.parse(r.dispatcher_heartbeat) > 900000;
      return <article key={r.ledger_run_id} className="border rounded p-3 space-y-2">
        <div className="flex flex-wrap gap-2 items-center"><strong>{r.strategy_name} · v{r.strategy_version}</strong><Tag color={r.error ? 'red' : 'blue'}>{state}</Tag><Tag>虚拟观察</Tag></div>
        <p className="text-xs break-all">账户 / 账本：{r.ledger_run_id}</p>
        <div className="flex flex-wrap gap-2 text-blue-600 text-sm">
          <a href={`#/user-center?tab=strategies&strategyId=${r.strategy_id}`}>冻结版本与代码</a>
          <a href={`#/backtest?backtest=${r.backtest_id}`}>准入回测</a>
          <a href={`#/alpha-research?research=${r.research_case_id}`}>研究来源</a>
        </div>
        <p>数据日期：{r.data_date || '尚无账本数据'} · 权益：{money(r.nav)} · 现金：{money(r.cash)}</p>
        <p>风险：{r.risk ? (r.risk.status === 'paused' ? '暂停买入，等待风险确认' : '未触发暂停') : '尚未产生估值与风险记录'}{typeof r.nav === 'number' && r.risk?.high_water_mark > 0 ? ` · 当前回撤 ${((1 - r.nav / r.risk.high_water_mark) * 100).toFixed(2)}%` : ''}</p>
        <p>最近决策：{r.latest_decision?.reason || r.latest_decision?.no_trade_reason || '尚未生成'}</p>
        {(r.error || r.last_day?.detail) && <Alert type={r.error ? 'error' : 'info'} message={r.error || r.last_day.detail} />}
        {stale && <Alert type="warning" message="调度心跳缺失或陈旧，不能据此判定运行成功。" />}
        {!compact && <>
          <Descriptions size="small" column={{ xs: 1, sm: 1, md: 2 }}>
            <Descriptions.Item label="初始本金">{money(r.initial_cash)}</Descriptions.Item>
            <Descriptions.Item label="最早观察日期">{r.start_date}</Descriptions.Item>
            <Descriptions.Item label="每天决策">{r.decision_time} 起；最迟次开市日 {r.decision_deadline_time} 前</Descriptions.Item>
            <Descriptions.Item label="盘后记账">{r.accounting_time}（北京时间）</Descriptions.Item>
            <Descriptions.Item label="调度心跳">{r.dispatcher_heartbeat || '未收到'}</Descriptions.Item>
            <Descriptions.Item label="执行心跳">{r.last_heartbeat || '未运行'}</Descriptions.Item>
            <Descriptions.Item label="最近成功">{r.status?.last_success_at || '未产生'}</Descriptions.Item>
            <Descriptions.Item label="下次运行">{ctl?.command === 'stop' && ctl?.state === 'effective' ? '已停止' : r.status?.next_run_at || '等待交易日历和首次调度'}</Descriptions.Item>
          </Descriptions>
          <p className="text-sm">每日输入：{r.publisher?.status === 'published' ? '输入包已发布' : r.publisher?.status === 'blocked' ? '发布受阻' : '尚未发布'} · 最新数据 {r.publisher?.data_date || '未确认'}{r.publisher?.error ? ` · ${r.publisher.error}` : ''}</p>
          <p className="text-xs text-slate-500">前一日冻结决策，次一交易日开盘价作为成交假设，日线完整后记账。不是早盘实时撮合；新账户不会导入历史回测盈利。</p>
          {r.positions ? <Table size="small" pagination={false} rowKey="symbol" dataSource={Object.entries(r.positions).map(([s, p]: any) => ({ symbol: s, ...p }))}
            columns={[{ title: '标的', dataIndex: 'symbol' }, { title: '数量', dataIndex: 'qty' }, { title: '市值', dataIndex: 'market_value', render: money }]} /> : <p>持仓：尚未产生。初始本金 {money(r.initial_cash)} 元单独保留。</p>}
          <details><summary>风险、订单及最近运行证据</summary><pre className="text-xs whitespace-pre-wrap max-h-96 overflow-auto">{JSON.stringify({ risk: r.risk, orders: r.orders, recent_days: r.recent_days }, null, 2)}</pre></details>
          <div className="flex gap-2"><Button onClick={async () => {
            try { await service.executionRequest(`strategy-paper-runs/${r.ledger_run_id}/control`, { command: 'stop' }); await load(); }
            catch (e: any) { setError(String(e?.response?.data?.detail || e.message)); }
          }}>请求停止</Button>
            <Button disabled={ctl?.command !== 'stop' || ctl?.state !== 'effective'} onClick={async () => {
              try { await service.executionRequest(`strategy-paper-runs/${r.ledger_run_id}/control`, { command: 'resume' }); await load(); }
              catch (e: any) { setError(String(e?.response?.data?.detail || e.message)); }
            }}>恢复调度</Button>
            {ctl?.command === 'stop' && ctl?.state === 'effective' && r.enabled && <Button onClick={async () => { try { await service.executionRequest(`strategy-paper-runs/${r.ledger_run_id}/control`, { command: 'archive' }); await load(); } catch (e: any) { setError(String(e?.response?.data?.detail || e.message)); } }}>归档已停止账户</Button>}
            {ctl && <span>控制：{ctl.command} · {ctl.state}</span>}
          </div>
        </>}
      </article>;
    })}
  </section>;
}
