import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Empty, Select, Space, Table, Tag, Typography } from 'antd';
import { Pause, Square, Download, Server } from 'lucide-react';
import ReactECharts from 'echarts-for-react';
import { Layout, type PageId } from '../components-v2/layout/Layout';
import { researchRuns, type ResearchCapabilities, type ResearchExperiment, type ResearchRun } from '../services-v2/researchRuns';
import ResearchDiscussion from './ResearchDiscussion';
import { SERVICE_ENDPOINTS } from '../../../config/services';

const { Text, Paragraph } = Typography;
const statuses: Record<string, string> = { queued: '排队中', running: '研究中', pause_requested: '正在收尾后暂停',
  paused: '已暂停', cancel_requested: '正在停止', cancelled: '已取消', expired: '窗口已结束',
  completed: '已完成', blocked: '需要检查', failed: '失败' };
const phases: Record<string, string> = { baseline: '基线实验', propose: '提出与验证候选', select: '选择与压力验证', finish: '核验与报告' };
const activeStatuses = new Set(['queued', 'running', 'pause_requested', 'cancel_requested']);
const fmt = (value: number | undefined | null, percent = false) =>
  value == null || !Number.isFinite(value) ? '待计算' : percent ? `${(value * 100).toFixed(2)}%` : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
const errorText = (error: any) => typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : '连接暂时不可用，已保留任务；恢复后可重试。';

export default function ResearchWorkbench({ onNavigate }: { onNavigate: (page: PageId) => void }) {
  const [cap, setCap] = useState<ResearchCapabilities | null>(null);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [selected, setSelected] = useState<ResearchRun | null>(null);
  const selectedId = useRef<string | null>(null);
  const detailPanel = useRef<HTMLDivElement>(null);
  const [openingRun, setOpeningRun] = useState<string | null>(null);
  const [detailNavigation, setDetailNavigation] = useState<ResearchRun | null>(null);
  const node = useRef<string | null>(null);
  const scope = useRef<string | null>(null);
  const endpoint = useRef(String(SERVICE_ENDPOINTS.AI_STRATEGY));
  const [error, setError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [discussionSeed, setDiscussionSeed] = useState<ResearchRun | null>(null);
  const [filter, setFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const currentEndpoint = String(SERVICE_ENDPOINTS.AI_STRATEGY);
        if (endpoint.current !== currentEndpoint) {
          endpoint.current = currentEndpoint;
          node.current = null; selectedId.current = null;
          setSelected(null); setRuns([]); setCap(null);
        }
        const nextCap = await researchRuns.capabilities();
        if (stopped || currentEndpoint !== String(SERVICE_ENDPOINTS.AI_STRATEGY)) return;
        if (node.current !== nextCap.node_id || scope.current !== (nextCap.owner_scope || null)) {
          node.current = nextCap.node_id;
          scope.current = nextCap.owner_scope || null;
          selectedId.current = null; setSelected(null); setRuns([]); setDiscussionSeed(null);
        }
        setCap(nextCap);

        if (nextCap.node_id) {
          const nextRuns = await researchRuns.list(node.current!);
          if (stopped || node.current !== nextCap.node_id || currentEndpoint !== String(SERVICE_ENDPOINTS.AI_STRATEGY)) return;
          setRuns(nextRuns);
          const id = selectedId.current;
          if (id) {
            const detail = await researchRuns.detail(id, nextCap.node_id);
            if (!stopped && detail.node_id === node.current && (!selectedId.current || selectedId.current === id) && currentEndpoint === String(SERVICE_ENDPOINTS.AI_STRATEGY)) {
              selectedId.current = id; setSelected(detail);
            }
          }
        }
        if (!stopped) setConnectionError(null);
      } catch (err) {
        if (!stopped) {
          if ([401, 403].includes((err as any)?.response?.status)) {
            node.current = null; scope.current = null; selectedId.current = null;
            setCap(null); setRuns([]); setSelected(null);
          }
          setConnectionError(errorText(err));
        }
      } finally {
        if (!stopped) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!detailNavigation) return;
    detailPanel.current?.focus({ preventScroll: true });
    detailPanel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [detailNavigation]);

  const openRun = async (row: ResearchRun) => {
    selectedId.current = row.run_id;
    setOpeningRun(row.run_id); setError(null);
    try {
      const detail = await researchRuns.detail(row.run_id, row.node_id);
      if (node.current !== row.node_id || selectedId.current !== row.run_id) return;
      setSelected(detail);
      setDetailNavigation(detail);
    } catch (err) { setError(errorText(err)); }
    finally { if (selectedId.current === row.run_id) setOpeningRun(null); }
  };

  const control = async (action: 'pause' | 'cancel') => {
    if (!selected || selected.node_id !== node.current || submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    const requestScope = scope.current;
    try {
      await researchRuns.control(selected.run_id, selected.node_id, action);
      const detail = await researchRuns.detail(selected.run_id, selected.node_id);
      if (scope.current !== requestScope || node.current !== selected.node_id) return;
      setSelected(detail);
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
  return <Layout currentPage="home" onNavigate={onNavigate}>
    <div className="space-y-5 select-text" data-testid="research-workbench">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div><h2 className="text-2xl font-semibold mb-1">研究工作台</h2><Text type="secondary">先讨论研究什么、怎么验证；看过计划后，再决定是否执行。</Text></div>
        <Tag icon={<Server size={13} className="inline mr-1" />} color={cap?.ready ? 'green' : 'default'}>
          {cap?.environment || '正在核对执行环境'}{connectionError ? ' · 连接中断' : cap?.ready ? ' · 执行服务在线' : ''}
        </Tag>
      </div>
      {(connectionError || error) && <Alert type="error" message={connectionError || error} closable onClose={() => { setError(null); setConnectionError(null); }} />}
      {cap && !cap.ready && <Alert type="warning" message={cap.reason || '执行服务不可用'}
        description="当前任务仍保存在服务端。完成配置或恢复执行服务后即可开始；这里不会切换到演示结果。" />}
      {cap?.node_id && <fieldset disabled={!!connectionError}><ResearchDiscussion key={`${cap.node_id}:${cap.owner_scope}`} cap={cap} seed={discussionSeed}
        onRun={id => void openRun({ run_id: id, node_id: cap.node_id! } as ResearchRun)} /></fieldset>}
      <Card title="执行记录" extra={<Space>
        <Select aria-label="研究类型筛选" value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部类型' }, { value: 'strategy', label: '策略' }, { value: 'method', label: '方法 / 因子' }]} />
        <Select aria-label="研究状态筛选" value={statusFilter} onChange={setStatusFilter} options={[{ value: 'all', label: '全部状态' }, ...Object.entries(statuses).map(([value, label]) => ({ value, label }))]} />
      </Space>}>
        <Table size="small" rowKey="run_id" pagination={{ pageSize: 5 }} locale={{ emptyText: <Empty description="尚未确认执行计划；可以先在上方讨论" /> }}
          dataSource={runs.filter(r => (filter === 'all' || r.kind === filter) && (statusFilter === 'all' || r.status === statusFilter))}
          columns={[{ title: '研究', dataIndex: 'goal', render: (value: string, row: ResearchRun) => <Button type="link" className="whitespace-normal text-left h-auto" loading={openingRun === row.run_id} aria-pressed={selected?.run_id === row.run_id} onClick={() => void openRun(row)}>{value}</Button> },
            { title: '类型', dataIndex: 'kind', render: (kind: string) => kind === 'method' ? '方法 / 因子' : '策略' },
            { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={s === 'completed' ? 'green' : s === 'blocked' ? 'orange' : 'blue'}>{statuses[s] || s}</Tag> },
            { title: '已核验实验', dataIndex: 'completed_experiments' },
            { title: '开始时间', dataIndex: 'started_at', render: (s: string) => new Date(s).toLocaleString() }]} />
      </Card>
      {selected && <Card ref={detailPanel} tabIndex={-1} aria-label="研究详情" style={{ scrollMarginTop: 144 }}
        styles={{ header: { flexWrap: 'wrap', gap: 12, paddingBlock: 12 }, title: { whiteSpace: 'normal', minWidth: 180 } }}
        title={selected.goal} extra={<Space wrap>
        {activeStatuses.has(selected.status) && <><Button loading={busy} icon={<Pause size={14} />} onClick={() => void control('pause')}>暂停后续</Button>
          <Button danger loading={busy} icon={<Square size={14} />} onClick={() => void control('cancel')}>取消研究</Button></>}
        <Button disabled={busy} onClick={() => setDiscussionSeed({ ...selected })}>{selected.draft_id ? "讨论 / 修改此计划" : "基于此结果建立课题"}</Button>
        <Button disabled={!selected.report_available} icon={<Download size={14} />} onClick={() => void download()}>下载报告</Button>
      </Space>}>
        <div className="space-y-4">
          <Space wrap><Tag>{selected.environment}</Tag><Tag>{statuses[selected.status]}</Tag><Text>{phases[selected.stage] || selected.stage}</Text>
            <Text type="secondary">截止：{new Date(selected.deadline_epoch * 1000).toLocaleString()}</Text>
            <Text type="secondary">模型：{selected.model}</Text></Space>
          {selected.error && <Alert type="warning" message={selected.error} />}
          <Alert type="info" message="当前为历史开发比较，需要另做独立验证。研究完成不代表策略盈利或允许交易。" />
          <Paragraph>已核验 {selected.completed_experiments} 个实验。{selected.status === 'paused' ? '后续实验已暂停，等待你的决定。' : selected.status === 'cancelled' ? '研究已取消，已有证据保留。' : phases[selected.stage] || selected.stage}</Paragraph>
          {selected.active && <Alert type="info" message={`${selected.active.id} · ${selected.active.submitted ? '已提交计算' : '尚未提交计算'} · ${selected.active.status}`}
            description={selected.active.proposal.hypothesis} />}
          <div><h4>执行进展</h4>{selected.events?.slice(-12).map((e, i) => <div key={`${e.at}-${i}`} className="py-1"><Text type="secondary">{new Date(e.at * 1000).toLocaleTimeString()} </Text>{e.message}</div>)}</div>
          {selected.curves?.length ? <ReactECharts option={chart} style={{ height: 310 }} notMerge /> : <Empty description="尚未产生已核验净值" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          <Table size="small" rowKey="id" pagination={false} dataSource={experiments} columns={[
            { title: '实验', dataIndex: 'id' }, { title: '目的', render: (_, e) => e.proposal.kind === 'baseline' ? '基线' : e.proposal.kind === 'stress' ? '双倍费用' : '候选' },
            { title: '净收益', render: (_, e) => fmt(e.result?.summary.comparison.model.total_return, true) },
            { title: '最大回撤', render: (_, e) => fmt(e.result?.summary.comparison.model.max_drawdown, true) },
            { title: '费用（元）', render: (_, e) => fmt(e.result?.summary.comparison.model.transaction_cost) },
            { title: '结论', render: (_, e) => e.status !== 'completed' ? <Space>失败，证据保留{e.result?.artifacts['execution.log'] && <Button size="small" onClick={() => void download(e, 'execution.log')}>日志</Button>}</Space> : e.gates ? Object.values(e.gates).every(Boolean) ? '通过开发门槛' : '未通过开发门槛' : '已核验' },
          ]} />
          {experiments.filter(e => e.proposal.kind === 'candidate' && e.proposal.factor && e.result?.factor_analysis).map(e => {
            const m = e.result!.factor_analysis!.splits.valid;
            return <Card key={e.id} size="small" title={`${e.id} · 因子验证`} extra={<Space>
              <Button onClick={() => void download(e, 'factor-analysis.json')}>指标明细</Button>
              <Button disabled={busy} onClick={() => setDiscussionSeed({ ...selected })}>讨论如何使用这个因子</Button>
            </Space>}>
              <Paragraph code copyable>{e.proposal.factor?.expression}</Paragraph>
              <Space wrap><Text>验证覆盖 {fmt(m.coverage, true)}</Text><Text>IC {fmt(m.ic)}</Text><Text>Rank IC {fmt(m.rank_ic)}</Text>
                <Text>Rank ICIR {fmt(m.rank_icir)}</Text><Text>正 Rank IC 比例 {fmt(m.positive_rank_ic_fraction, true)}</Text></Space>
            </Card>;
          })}
          {selected.selection && <div><h4>模型选择记录（压力验证前生成）</h4><Paragraph>{selected.selection.reason}</Paragraph><Text type="secondary">当时提出的问题：{selected.selection.next_question}</Text></div>}

          <Text type="secondary">已完成调用 {selected.usage?.calls ?? 0} 次 · 已确认 Token {fmt(selected.usage ? selected.usage.input_tokens + selected.usage.output_tokens : null)} · 用量未知 {selected.usage?.unknown_usage ?? 0} 次 · 服务退避 {selected.usage?.retryable ?? 0} 次 · 金额未返回</Text>
        </div>
      </Card>}
    </div>
  </Layout>;
}
