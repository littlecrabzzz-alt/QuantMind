import React, { useEffect, useState } from 'react';
import { Alert, Button, Select, Tag } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { AgentCase } from '../services-v2/researchAgent';
import { researchAgent } from '../services-v2/researchAgent';
import { strategyManagementService } from '../../../services/strategyManagementService';
import type { StrategyFile } from '../../../types/backtest/strategy';
import LedgerDetailView from './LedgerDetailView';

/** Render the existing registered files; never import history as virtual fills. */
export default function ResearchLedgerPanel({ node, research }: { node: string; research: AgentCase }) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState('');
  const [linked, setLinked] = useState<StrategyFile[]>([]);
  const [error, setError] = useState('');
  const artifacts = (research.external?.artifacts ?? [])
    .filter(a => /(?:view|evidence)\.json$/i.test(a.name))
    .sort((a, b) => Number(!a.name.endsWith('-view.json')) - Number(!b.name.endsWith('-view.json')) || a.name.localeCompare(b.name));
  const artifact = artifacts.find(a => a.uri === selected) ?? artifacts[0];

  useEffect(() => {
    let stopped = false;
    setLinked([]);
    setSelected('');
    setError('');
    strategyManagementService.loadStrategies().then(strategies => {
      if (!stopped) setLinked(strategies.filter(s => s.parameters?.research_case_id === research.id));
    }).catch(() => { if (!stopped) setError('关联策略暂时无法读取；历史账本仍可单独查看。'); });
    return () => { stopped = true; };
  }, [research.id]);

  if (!artifact) return null;
  const resultLabel = (name: string) => {
    for (const strategy of linked) {
      const results = strategy.parameters?.historical_results;
      if (!Array.isArray(results)) continue;
      const result = results.find(r => r.name === name);
      if (typeof result?.label === 'string') return `${result.label} · ${name}`;
    }
    return name;
  };
  const download = async () => {
    try {
      const path = artifact.uri.startsWith('node://') ? artifact.uri.split('/workspace/')[1] : artifact.uri;
      if (!path) throw new Error('文件路径无效');
      const blob = await researchAgent.file(node, research.id, path);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = artifact.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { setError('原件下载失败，请检查节点连接后重试。'); }
  };

  return <section className="rounded-xl border border-border bg-card p-4 space-y-3" data-testid="research-ledger-panel">
    <h3 className="font-semibold text-lg">历史回测 · 净值与逐日账本</h3>
    <p className="text-sm text-muted-foreground">读取课题已登记的原件并核对 SHA256。历史研究、未来虚拟盘分别记账；这里的曲线不会产生模拟账户成交。</p>
    {linked.map(strategy => {
      const parameters = strategy.parameters ?? {};
      const review = parameters.research_review as { summary?: string } | undefined;
      return <div key={strategy.id} className="space-y-2">
        <div className="flex flex-wrap gap-2 items-center">
          <Button onClick={() => navigate(`/user-center?tab=strategies&strategyId=${encodeURIComponent(strategy.id)}`)}>关联策略 #{strategy.id} · 查看配置</Button>
          {parameters.configuration_only === true && <Tag>持续虚拟盘：尚未启动</Tag>}
        </div>
        {review?.summary && <Alert type="warning" showIcon message="历史结果待执行规则修复后重跑" description={review.summary} />}
        {Array.isArray(parameters.activation_blockers) && <details>
          <summary className="cursor-pointer text-sm">虚拟盘待完成项（{parameters.activation_blockers.length}）</summary>
          <ul className="list-disc pl-5 text-sm mt-2">{parameters.activation_blockers.map((reason, i) => <li key={i}>{String(reason)}</li>)}</ul>
        </details>}
      </div>;
    })}
    {error && <Alert type="warning" message={error} />}
    <div className="flex flex-wrap gap-2 items-center">
      <Select aria-label="历史回测结果" style={{ minWidth: 270 }} value={artifact.uri} onChange={setSelected}
        options={artifacts.map(a => ({ value: a.uri, label: resultLabel(a.name) + (a.fixture ? '（工程样例）' : '') }))} />
      <Button onClick={() => void download()}>下载当前原件</Button>
      <span className="text-xs font-mono">SHA256 {artifact.sha256.slice(0, 12)}…</span>
    </div>
    <LedgerDetailView key={`${research.id}:${artifact.uri}:${artifact.sha256}`} node={node} caseId={research.id} artifact={artifact} showCurve />
  </section>;
}
