import React, { useEffect, useState } from 'react';
import { Alert, Button } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { AgentCase } from '../services-v2/researchAgent';
import { strategyManagementService } from '../../../services/strategyManagementService';
import type { StrategyFile } from '../../../types/backtest/strategy';

/** Research owns provenance; native strategy/backtest/trading pages own execution. */
export default function ResearchLedgerPanel({ research }: { node: string; research: AgentCase }) {
  const navigate = useNavigate();
  const [linked, setLinked] = useState<StrategyFile[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let stopped = false;
    setLinked([]); setError('');
    strategyManagementService.loadStrategies().then(rows => {
      if (!stopped) setLinked(rows.filter(s => s.parameters?.research_case_id === research.id));
    }).catch(() => { if (!stopped) setError('关联策略读取失败。'); });
    return () => { stopped = true; };
  }, [research.id]);
  return <section className="rounded-xl border border-border bg-card p-4 space-y-3" data-testid="research-ledger-panel">
    <h3 className="font-semibold">研究产出与运行入口</h3>
    <p className="text-sm text-muted-foreground">本页保留研究问题、进展、结论与证据。代码版本、回测与持续账户在对应模块中查看。</p>
    {error && <Alert type="warning" message={error} />}
    {linked.map(s => <div key={s.id} className="flex gap-2 flex-wrap items-center">
      <span>{s.name}</span>
      <Button onClick={() => navigate(`/user-center?tab=strategies&strategyId=${s.id}`)}>策略版本与脚本</Button>
      <Button onClick={() => navigate(`/backtest?strategyId=${s.id}`)}>回测记录、对比与复跑</Button>
      <Button onClick={() => navigate(`/trading?paper=${s.id}`)}>虚拟账户与监控</Button>
    </div>)}
    {!linked.length && <p className="text-sm">尚无关联的策略版本。</p>}
    <p className="text-xs text-muted-foreground">历史附件仍保留在下方证据列表。旧脚本产生的文件不自动视为公共入口的回测记录。</p>
  </section>;
}
