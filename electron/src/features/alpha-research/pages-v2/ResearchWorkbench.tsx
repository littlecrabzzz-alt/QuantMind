import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Collapse, Empty, Input, InputNumber, Select, Space, Table, Tag, Typography } from 'antd';
import { FlaskConical, TrendingUp, Play, Pause, Square, Download, Server } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import { Layout, type PageId } from '../components-v2/layout/Layout';
import { researchRuns, type ResearchCapabilities, type ResearchExperiment, type ResearchKind, type ResearchRequest, type ResearchRun } from '../services-v2/researchRuns';
import { SERVICE_ENDPOINTS } from '../../../config/services';

const { Text, Paragraph } = Typography;
const statuses: Record<string, string> = { queued: '排队中', running: '研究中', pause_requested: '正在收尾后暂停',
  paused: '已暂停', cancel_requested: '正在停止', cancelled: '已取消', expired: '窗口已结束',
  completed: '已完成', blocked: '需要检查', failed: '失败' };
const phases: Record<string, string> = { baseline: '基线实验', propose: '提出与验证候选', select: '选择与压力验证', finish: '核验与报告' };
const activeStatuses = new Set(['queued', 'running', 'pause_requested', 'cancel_requested']);
const resumable = new Set(['paused', 'expired', 'cancelled', 'failed', 'blocked']);
const fmt = (value: number | undefined | null, percent = false) =>
  value == null || !Number.isFinite(value) ? '待计算' : percent ? `${(value * 100).toFixed(2)}%` : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
const errorText = (error: any) => typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : '连接暂时不可用，已保留任务；恢复后可重试。';
const pendingKey = (node: string) => `research-pending:${node}`;

export default function ResearchWorkbench({ onNavigate }: { onNavigate: (page: PageId) => void }) {
  const [cap, setCap] = useState<ResearchCapabilities | null>(null);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [selected, setSelected] = useState<ResearchRun | null>(null);
  const selectedId = useRef<string | null>(null);
  const node = useRef<string | null>(null);
  const scope = useRef<string | null>(null);
  const endpoint = useRef(String(SERVICE_ENDPOINTS.AI_STRATEGY));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [goal, setGoal] = useState('');
  const [hours, setHours] = useState(2);
  const [model, setModel] = useState('glm-5.3-flash');
  const [candidates, setCandidates] = useState(2);
  const [expression, setExpression] = useState('');
  const [source, setSource] = useState('');
  const [filter, setFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pending, setPending] = useState<ResearchRequest | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const currentEndpoint = String(SERVICE_ENDPOINTS.AI_STRATEGY);
        if (endpoint.current !== currentEndpoint) {
          endpoint.current = currentEndpoint;
          node.current = null; selectedId.current = null;
          setSelected(null); setRuns([]); setPending(null); setCap(null);
        }
        const nextCap = await researchRuns.capabilities();
        if (stopped || currentEndpoint !== String(SERVICE_ENDPOINTS.AI_STRATEGY)) return;
        if (node.current !== nextCap.node_id || scope.current !== (nextCap.owner_scope || null)) {
          node.current = nextCap.node_id;
          scope.current = nextCap.owner_scope || null;
          selectedId.current = null; setSelected(null); setRuns([]);
          const saved = scope.current ? sessionStorage.getItem(pendingKey(scope.current)) : null;
          try { setPending(saved ? JSON.parse(saved) : null); } catch { setPending(null); }
        }
        setCap(nextCap);

        if (nextCap.node_id) {
          const nextRuns = await researchRuns.list(node.current!);
          if (stopped || node.current !== nextCap.node_id || currentEndpoint !== String(SERVICE_ENDPOINTS.AI_STRATEGY)) return;
          setRuns(nextRuns);
          const id = selectedId.current || nextRuns[0]?.run_id;
          if (id) {
            const detail = await researchRuns.detail(id, nextCap.node_id);
            if (!stopped && detail.node_id === node.current && (!selectedId.current || selectedId.current === id) && currentEndpoint === String(SERVICE_ENDPOINTS.AI_STRATEGY)) {
              selectedId.current = id; setSelected(detail);
            }
          }
        }
      } catch (err) {
        if (!stopped) {
          node.current = null; scope.current = null; selectedId.current = null;
          setCap(null); setRuns([]); setSelected(null); setPending(null);
          setError(errorText(err));
        }
      } finally {
        if (!stopped) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (cap?.models.length && !cap.models.includes(model)) setModel(cap.models[0]);
  }, [cap, model]);

  const create = async (request: ResearchRequest) => {
    if (submitting.current || request.node_id !== node.current) return;
    submitting.current = true; setBusy(true); setError(null);
    const requestScope = scope.current!;
    try {
      sessionStorage.setItem(pendingKey(requestScope), JSON.stringify(request));
      setPending(request);
      const created = await researchRuns.create(request);
      if (created.node_id !== node.current || scope.current !== requestScope) return;
      sessionStorage.removeItem(pendingKey(requestScope)); setPending(null);
      selectedId.current = created.run_id;
      const detail = await researchRuns.detail(created.run_id, request.node_id);
      if (scope.current === requestScope && node.current === request.node_id) setSelected(detail);
      const list = await researchRuns.list(request.node_id);
      if (scope.current === requestScope && node.current === request.node_id) setRuns(list);
    } catch (err: any) {
      if (scope.current !== requestScope) return;
      if ([400, 409, 422].includes(err?.response?.status)) {
        sessionStorage.removeItem(pendingKey(requestScope)); setPending(null);
      }
      setError(errorText(err));
    }
    finally { submitting.current = false; setBusy(false); }
  };

  const start = (kind: ResearchKind, parent?: ResearchExperiment) => {
    if (!cap?.ready || !cap.node_id || pending) return;
    void create({ idempotency_key: crypto.randomUUID(), node_id: cap.node_id, kind, goal,
      hours, candidate_limit: candidates, model, expression: kind === 'method' ? expression : '', source_text: source,
      ...(parent && selected ? { source_run_id: selected.run_id, source_experiment_id: parent.id } : {}) });
  };

  const control = async (action: 'pause' | 'cancel' | 'continue') => {
    if (!selected || selected.node_id !== node.current || submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    const requestScope = scope.current;
    try {
      if (action === 'continue') {
        const next = await researchRuns.resume(selected.run_id, selected.node_id, hours, crypto.randomUUID());
        const detail = await researchRuns.detail(next.run_id, selected.node_id);
        if (scope.current !== requestScope || node.current !== selected.node_id) return;
        selectedId.current = next.run_id; setSelected(detail);
      } else {
        await researchRuns.control(selected.run_id, selected.node_id, action);
        const detail = await researchRuns.detail(selected.run_id, selected.node_id);
        if (scope.current !== requestScope || node.current !== selected.node_id) return;
        setSelected(detail);
      }
      const list = await researchRuns.list(selected.node_id);
      if (scope.current === requestScope && node.current === selected.node_id) setRuns(list);
    } catch (err) { setError(errorText(err)); }
    finally { submitting.current = false; setBusy(false); }
  };
  const download = async (experiment?: ResearchExperiment, name?: string) => {
    if (!selected || selected.node_id !== node.current) return;
    try {
      await researchRuns.download(selected.run_id, selected.node_id,
        experiment && name ? `artifacts/${experiment.id}/${name}` : undefined, name);
    } catch (err) { setError(errorText(err)); }
  };

  const chart = { tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmt(v) },
    legend: { type: 'scroll', bottom: 0 }, grid: { left: 55, right: 25, top: 20, bottom: 65 },
    xAxis: { type: 'category', data: selected?.curves?.[0]?.values.map(v => v.date) || [] },
    yAxis: { type: 'value', scale: true, name: '净值' },
    series: selected?.curves?.map(s => ({ name: s.name, type: 'line', showSymbol: false,
      data: s.values.map(v => [v.date, v.nav]) })) || [] };
  const experiments = selected?.experiments || [];
  const card = (kind: ResearchKind, title: string, description: string) => <Card className="h-full" key={kind}>
    <div className="flex gap-3 items-center mb-3">
      {kind === 'strategy' ? <TrendingUp className="text-blue-500" /> : <FlaskConical className="text-violet-500" />}
      <h3 className="text-lg font-semibold m-0">{title}</h3>
    </div>
    <Paragraph type="secondary" className="min-h-12">{description}</Paragraph>
    <Button type="primary" block icon={<Play size={15} />} loading={busy}
      disabled={!cap?.ready || !!pending} onClick={() => start(kind)}>{`开始${title}`}</Button>
  </Card>;

  return <Layout currentPage="home" onNavigate={onNavigate}>
    <div className="space-y-5 select-text" data-testid="research-workbench">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div><h2 className="text-2xl font-semibold mb-1">研究工作台</h2><Text type="secondary">把一个假设推进到可核验的结果，随时回来查看。</Text></div>
        <Tag icon={<Server size={13} className="inline mr-1" />} color={cap?.ready ? 'green' : 'default'}>
          {cap?.environment || '正在核对执行环境'}{cap?.ready ? ' · 可运行' : ''}
        </Tag>
      </div>
      {error && <Alert type="error" message={error} closable onClose={() => setError(null)} />}
      {cap && !cap.ready && <Alert type="warning" message={cap.reason || '执行服务不可用'}
        description="当前任务仍保存在服务端。完成配置或恢复执行服务后即可开始；这里不会切换到演示结果。" />}
      {pending && <Alert type="info" message="上次提交尚待确认，重试会沿用同一任务标识。"
        action={<Button loading={busy} onClick={() => void create(pending)}>重试上次提交</Button>} />}
      <Input.TextArea aria-label="研究目标" placeholder="研究目标（可选）：例如检验动量与成交量组合是否带来稳定增量"
        value={goal} onChange={e => setGoal(e.target.value)} maxLength={1200} autoSize={{ minRows: 2, maxRows: 4 }} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {card('strategy', '策略研究', '复现基线，训练和推理，比较候选，验证交易成本与稳定性。')}
        {card('method', '方法 / 新因子研究', '实现可执行因子假设，检查 IC、覆盖和稳定性，验证相对基线的增量。')}
      </div>
      <Collapse items={[{ key: 'settings', label: `研究设置 · 最长 ${hours} 小时 · ${model} · ${candidates} 个候选`, children:
        <div className="space-y-3">
          <Space wrap><label>最长运行小时 <InputNumber aria-label="最长运行小时" min={0.1} max={8} step={0.5} value={hours} onChange={n => setHours(n || 2)} /></label>
            <Select aria-label="研究模型" style={{ minWidth: 180 }} value={model} onChange={setModel} options={(cap?.models || []).map(value => ({ value, label: value }))} />
            <Select aria-label="候选数量" value={candidates} onChange={setCandidates} options={[{ value: 1, label: '1 个候选' }, { value: 2, label: '2 个候选' }]} />
          </Space>
          <div><Text type="secondary">数据模板：{cap?.snapshot_id || '待配置'}；固定本金：{fmt(cap?.base_config?.portfolio.initial_capital)} 元。开发比较区间：{cap?.base_config?.split.test?.join(' 至 ') || '待配置'}。</Text></div>
          <Input aria-label="因子公式" value={expression} onChange={e => setExpression(e.target.value)} maxLength={800}
            placeholder="方法研究的可选公式，例如 rank(mom_ret_20d) * rank(amt_ratio_5_20)" />
          <Text type="secondary">可用特征：{cap?.base_config?.features.join('、') || '待加载'}。支持 rank、abs、log1p_abs、lag、mean、std 与四则运算。</Text>
          <Input.TextArea aria-label="方法说明或论文内容" value={source} onChange={e => setSource(e.target.value)} maxLength={12000}
            placeholder="可选：粘贴方法说明或论文中待验证的公式及依据。未提供的正文不会被视为已阅读或已复现。" autoSize={{ minRows: 2, maxRows: 6 }} />
          <Text type="secondary">窗口结束会保存并停止；继续研究会开新窗口，保留累计尝试记录。本地计算依赖本机保持运行。</Text>
        </div> }]} />
      <Card title="研究记录" extra={<Space>
        <Select aria-label="研究类型筛选" value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部类型' }, { value: 'strategy', label: '策略' }, { value: 'method', label: '方法 / 因子' }]} />
        <Select aria-label="研究状态筛选" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statuses).map(([value, label]) => ({ value, label }))]} />
      </Space>}>
        <Table size="small" rowKey="run_id" pagination={{ pageSize: 5 }} locale={{ emptyText: <Empty description="还没有研究，选择上方模板开始" /> }}
          dataSource={runs.filter(r => (filter === 'all' || r.kind === filter) && (statusFilter === 'all' || r.status === statusFilter))}
          columns={[{ title: '研究', dataIndex: 'goal', render: (value: string, row: ResearchRun) => <Button type="link" className="whitespace-normal text-left h-auto" onClick={() => { selectedId.current = row.run_id; void researchRuns.detail(row.run_id, row.node_id).then(detail => { if (node.current === row.node_id && selectedId.current === row.run_id) setSelected(detail); }).catch(e => setError(errorText(e))); }}>{value}</Button> },
            { title: '类型', dataIndex: 'kind', render: (kind: string) => kind === 'method' ? '方法 / 因子' : '策略' },
            { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={s === 'completed' ? 'green' : s === 'blocked' ? 'orange' : 'blue'}>{statuses[s] || s}</Tag> },
            { title: '已核验实验', dataIndex: 'completed_experiments' },
            { title: '开始时间', dataIndex: 'started_at', render: (s: string) => new Date(s).toLocaleString() }]} />
      </Card>
      {selected && <Card title={selected.goal} extra={<Space wrap>
        {activeStatuses.has(selected.status) && <><Button loading={busy} icon={<Pause size={14} />} onClick={() => void control('pause')}>暂停后续</Button>
          <Button danger loading={busy} icon={<Square size={14} />} onClick={() => void control('cancel')}>取消研究</Button></>}
        {resumable.has(selected.status) && <Button loading={busy} icon={<Play size={14} />} onClick={() => void control('continue')}>继续研究</Button>}
        <Button disabled={!selected.report_available} icon={<Download size={14} />} onClick={() => void download()}>下载报告</Button>
      </Space>}>
        <div className="space-y-4">
          <Space wrap><Tag>{selected.environment}</Tag><Tag>{statuses[selected.status]}</Tag><Text>{phases[selected.stage] || selected.stage}</Text>
            <Text type="secondary">截止：{new Date(selected.deadline_epoch * 1000).toLocaleString()}</Text>
            <Text type="secondary">模型：{selected.model}</Text></Space>
          {selected.error && <Alert type="warning" message={selected.error} />}
          <Alert type="info" message="当前为历史开发比较，需要另做独立验证。研究完成不代表策略盈利或允许交易。" />
          {selected.active && <Paragraph>当前实验 {selected.active.id}：{selected.active.proposal.hypothesis}</Paragraph>}
          {selected.curves?.length ? <ReactECharts option={chart} style={{ height: 310 }} notMerge /> : <Empty description="尚未产生已核验净值" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          <Table size="small" rowKey="id" pagination={false} dataSource={experiments} columns={[
            { title: '实验', dataIndex: 'id' }, { title: '目的', render: (_, e) => e.proposal.kind === 'baseline' ? '基线' : e.proposal.kind === 'stress' ? '双倍费用' : '候选' },
            { title: '净收益', render: (_, e) => fmt(e.result?.summary.comparison.model.total_return, true) },
            { title: '最大回撤', render: (_, e) => fmt(e.result?.summary.comparison.model.max_drawdown, true) },
            { title: '费用（元）', render: (_, e) => fmt(e.result?.summary.comparison.model.transaction_cost) },
            { title: '结论', render: (_, e) => e.status !== 'completed' ? '失败，证据保留' : e.gates ? Object.values(e.gates).every(Boolean) ? '通过开发门槛' : '未通过开发门槛' : '已核验' },
          ]} />
          {experiments.filter(e => e.result?.factor_analysis).map(e => {
            const m = e.result!.factor_analysis!.splits.valid;
            return <Card key={e.id} size="small" title={`${e.id} · 因子验证`} extra={<Space>
              <Button onClick={() => void download(e, 'factor-analysis.json')}>指标明细</Button>
              <Button disabled={selected.status !== 'completed' || !!pending || busy} onClick={() => start('strategy', e)}>以此创建策略研究</Button>
            </Space>}>
              <Paragraph code copyable>{e.proposal.factor?.expression}</Paragraph>
              <Space wrap><Text>验证覆盖 {fmt(m.coverage, true)}</Text><Text>IC {fmt(m.ic)}</Text><Text>Rank IC {fmt(m.rank_ic)}</Text>
                <Text>Rank ICIR {fmt(m.rank_icir)}</Text><Text>正 Rank IC 比例 {fmt(m.positive_rank_ic_fraction, true)}</Text></Space>
            </Card>;
          })}
          {selected.selection && <div><h4>模型选择说明</h4><Paragraph>{selected.selection.reason}</Paragraph><Text type="secondary">下一问题：{selected.selection.next_question}</Text></div>}
          <div><h4>研究进展</h4>{selected.events?.slice(-12).map((e, i) => <div key={`${e.at}-${i}`} className="py-1"><Text type="secondary">{new Date(e.at * 1000).toLocaleTimeString()} </Text>{e.message}</div>)}</div>
          <Text type="secondary">已记录调用 {selected.usage?.calls ?? 0} 次 · Token {fmt(selected.usage ? selected.usage.input_tokens + selected.usage.output_tokens : null)} · 限流重试 {selected.usage?.retryable ?? 0} 次 · 金额未返回</Text>
        </div>
      </Card>}
    </div>
  </Layout>;
}
