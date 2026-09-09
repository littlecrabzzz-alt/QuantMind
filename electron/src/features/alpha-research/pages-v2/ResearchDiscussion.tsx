import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Checkbox, Collapse, Empty, Input, InputNumber, Modal, Select, Space, Tag, Typography } from 'antd';
import { researchDrafts, type ResearchCapabilities, type ResearchDraft, type DiscussionMessage, type Approval } from '../services-v2/researchRuns';

const { Text, Paragraph } = Typography;
const jobStates: Record<string, string> = { queued: '等待讨论服务', running: '正在整理回答', retrying: '服务退避中，将自动重试', completed: '回答已保存', failed: '本次回答失败', cancelled: '本次讨论已停止' };
const runStates: Record<string, string> = { queued: '等待执行', running: '正在执行', pause_requested: '等待当前实验收尾后暂停', paused: '已暂停', cancelled: '已取消', cancel_requested: '正在停止', expired: '已到截止时间', completed: '已完成', failed: '失败', blocked: '需要处理阻碍' };
const active = new Set(['queued', 'running', 'pause_requested', 'cancel_requested']);
const pendingJob = (d: ResearchDraft | null) => !!d?.job && ['queued', 'running', 'retrying'].includes(d.job.status);
const errorText = (e: any) => typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : '连接未确认，内容已保留。恢复连接后可重试。';
const bullets = (values: string[]) => <ul className="list-disc pl-5 space-y-1">{values.map((v, i) => <li key={i}>{v}</li>)}</ul>;

export default function ResearchDiscussion({ cap, seed, onRun }: {
  cap: ResearchCapabilities; seed: { run_id: string; goal: string; draft_id?: string } | null; onRun: (id: string) => void;
}) {
  const node = cap.node_id!;
  const [list, setList] = useState<ResearchDraft[]>([]);
  const [draft, setDraft] = useState<ResearchDraft | null>(null);
  const selected = useRef<string | null>(null);
  const alive = useRef(true);
  const panel = useRef<HTMLDivElement>(null);
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [subject, setSubject] = useState('');
  const [material, setMaterial] = useState('');
  const [sourceRun, setSourceRun] = useState<string | undefined>();
  const [content, setContent] = useState('');
  const [mode, setMode] = useState<DiscussionMessage['mode']>('ask');
  const [model, setModel] = useState(cap.models[0] || 'glm-5.3-flash');
  const [version, setVersion] = useState<number | null>(null);
  const [review, setReview] = useState<Approval | null>(null);
  const [checked, setChecked] = useState(false);
  const [hours, setHours] = useState(2);
  const retryMessage = useRef<{ id: string; data: DiscussionMessage } | null>(null);

  const accept = (d: ResearchDraft) => {
    if (alive.current && selected.current === d.draft_id) setDraft(d);
  };
  const perform = async (action: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await action(); } catch (e) { if (alive.current) setError(errorText(e)); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  };
  const open = (id: string) => {
    selected.current = id; setDraft(null); setVersion(null); setContent(''); setReview(null); retryMessage.current = null;
    void perform(async () => { accept(await researchDrafts.detail(node, id)); });
  };
  useEffect(() => {
    alive.current = true;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const rows = await researchDrafts.list(node);
        if (stopped) return;
        setList(rows);
        const id = selected.current;
        if (id) { const next = await researchDrafts.detail(node, id); if (!stopped) accept(next); }
      } catch (e) { if (!stopped) setError(errorText(e)); }
      finally { if (!stopped) timer = setTimeout(poll, 3000); }
    };
    void poll();
    return () => { stopped = true; alive.current = false; clearTimeout(timer); };
  }, [node]);
  useEffect(() => {
    if (!seed) return;
    panel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (seed.draft_id) { open(seed.draft_id); return; }
    selected.current = null; setDraft(null); setVersion(null); setReview(null);
    setQuestion(`基于“${seed.goal}”，讨论下一步要验证什么以及如何验证`);
    setSubject(''); setMaterial(''); setSourceRun(seed.run_id);
  }, [seed]);

  const create = () => void perform(async () => {
    const d = await researchDrafts.create(node, { question, subject, material, ...(sourceRun ? { source_run_id: sourceRun } : {}) });
    if (!alive.current) return;
    selected.current = d.draft_id; setDraft(d); setVersion(null); setContent('');
    setList(await researchDrafts.list(node));
  });
  const send = (chosenMode = mode, text = content) => {
    if (!draft || !text.trim()) return;
    const old = retryMessage.current;
    const data = old?.id === draft.draft_id && old.data.content === text && old.data.mode === chosenMode && old.data.model === model
      ? old.data : { key: crypto.randomUUID(), revision: draft.revision, mode: chosenMode, content: text, model };
    retryMessage.current = { id: draft.draft_id, data };
    void perform(async () => {
      const d = await researchDrafts.message(node, draft.draft_id, data);
      accept(d); if (alive.current && selected.current === d.draft_id) { setContent(''); setVersion(null); retryMessage.current = null; }
    });
  };
  const entry = version ? draft?.plans?.find(p => p.version === version) : draft?.plan;
  const latest = entry?.version === draft?.plan?.version;
  const plan = entry?.plan;
  const canApprove = !!entry?.admission.ready && latest && !draft?.needs_plan && !pendingJob(draft);
  const beginReview = (action: Approval['action']) => {
    if (!draft || !entry) return;
    setChecked(false);
    setReview({ version: entry.version, action, reviewed: true, hours, candidate_limit: entry.plan.candidate_limit,
      model, key: action === 'resume' ? `resume:${draft.draft_id}:${entry.version}:${draft.run_id}` : `plan:${draft.draft_id}:${entry.version}`,
      ...(action === 'resume' && draft.run_id ? { parent_run_id: draft.run_id } : {}) });
  };
  const execute = () => {
    if (!draft || !review || !checked) return;
    void perform(async () => {
      const result = await researchDrafts.execute(node, draft.draft_id, review);
      const next = await researchDrafts.detail(node, draft.draft_id);
      accept(next); if (alive.current) { setReview(null); onRun(result.run_id); }
    });
  };
  const newTopic = () => {
    selected.current = null; setDraft(null); setVersion(null); setReview(null); setQuestion(''); setSubject(''); setMaterial(''); setSourceRun(undefined); setError(''); retryMessage.current = null;
  };
  return <div ref={panel} className="space-y-4" style={{ scrollMarginTop: 140 }}>
    <Card title="课题与计划" extra={<Button disabled={busy} onClick={newTopic}>新建课题</Button>}>
      <Space wrap className="mb-4">
        <Select aria-label="选择课题" placeholder="打开已保存课题" style={{ width: 360, maxWidth: '100%' }} value={draft?.draft_id}
          disabled={busy} onChange={open} options={list.map(d => ({ value: d.draft_id, label: d.plan?.plan.title || d.input.question }))} />
        <Text type="secondary">创建课题和查看记录不会启动实验</Text>
      </Space>
      {error && <Alert className="mb-3" type="error" message={error} closable onClose={() => setError('')} />}
      {!draft && <div className="space-y-4">
        <Paragraph>从一个想弄清的问题开始。可以是新想法、一份材料，也可以接着已有结果继续讨论。</Paragraph>
        <Space wrap>
          <Button onClick={() => { setQuestion('我想研究一种降低股票策略回撤的方法，先帮我明确研究对象、对照和验证方法。'); setSourceRun(undefined); }}>新想法示例</Button>
          <Button onClick={() => { setQuestion('我想验证下面材料中的方法。先判断需要什么数据、能否实现，以及怎样判断它有没有用。'); setSourceRun(undefined); }}>从材料开始</Button>
        </Space>
        <label className="block">你想弄清什么？<Input.TextArea aria-label="想弄清的问题" value={question} onChange={e => setQuestion(e.target.value)} maxLength={1200}
          placeholder="例如：成交量变化能否帮助判断动量什么时候容易失效？也可以先说你的困惑。" autoSize={{ minRows: 2, maxRows: 5 }} /></label>
        <label className="block">研究对象（还没想好可以留空）<Input aria-label="研究对象" value={subject} onChange={e => setSubject(e.target.value)} maxLength={1200}
          placeholder="例如：A股、某类ETF、一条已有策略，或一组因子" /></label>
        <label className="block">参考材料（可选）<Input.TextArea aria-label="参考材料" value={material} onChange={e => setMaterial(e.target.value)} maxLength={12000}
          placeholder="粘贴方法说明、公式或文章段落。目前不会自动打开链接阅读全文。" autoSize={{ minRows: 3, maxRows: 7 }} /></label>
        {sourceRun && <Tag>已关联原研究结果，建立后可讨论</Tag>}
        <Button type="primary" loading={busy} disabled={!question.trim()} onClick={create}>保存课题，进入讨论</Button>
      </div>}
      {draft && <div className="space-y-4">
        <h3 className="text-xl font-semibold">{draft.input.question}</h3>
        <Text>研究对象：{draft.input.subject || '尚未确定，可以在讨论中一起明确'}</Text>
        {draft.input.material && <Collapse items={[{ key: 'source', label: '原始参考材料', children: <Paragraph className="whitespace-pre-wrap">{draft.input.material}</Paragraph> }]} />}
        <div className="border rounded p-4 space-y-4" aria-label="课题讨论记录">
          {!draft.messages?.length && <Paragraph>课题已保存。先说明你希望得到什么结果、有什么疑问；也可以让助手整理一份待讨论的计划。</Paragraph>}
          {draft.messages?.map((m, i) => <div key={`${m.job_id}-${i}`}>
            <Text strong>{m.role === 'user' ? '你' : '研究助手'}</Text><Text type="secondary"> · {new Date(m.at * 1000).toLocaleString()}</Text>
            {m.mode && <Tag>{m.mode === 'ask' ? '讨论' : '提出计划修改'}</Tag>}
            <Paragraph className="whitespace-pre-wrap mt-1 mb-0">{m.content}</Paragraph>
          </div>)}
          {draft.job && <Alert type={draft.job.status === 'failed' ? 'error' : 'info'} message={jobStates[draft.job.status] || draft.job.status}
            description={draft.job.error || (pendingJob(draft) ? '请求已保存在服务端，离开页面也会继续处理。此处只讨论，不启动实验。' : undefined)}
            action={pendingJob(draft) ? <Button loading={busy} onClick={() => void perform(async () => accept(await researchDrafts.cancelMessage(node, draft.draft_id)))}>停止本次讨论</Button> : undefined} />}
        </div>
        <Space wrap>
          <Select aria-label="消息目的" value={mode} onChange={setMode} options={[{ value: 'ask', label: '讨论 / 提问' }, { value: 'revise', label: '调整计划（先暂停执行）' }]} />
          <Select aria-label="讨论模型" value={model} onChange={setModel} options={cap.models.map(value => ({ value, label: value }))} style={{ minWidth: 180 }} />
        </Space>
        <Input.TextArea aria-label="讨论内容" value={content} onChange={e => setContent(e.target.value)} maxLength={6000} disabled={busy}
          placeholder={mode === 'ask' ? '例如：我不确定该研究哪些股票，你需要我做什么选择？' : '例如：先不追求收益，改为比较不同市场阶段的稳定性。请重新列出需要的数据与步骤。'} autoSize={{ minRows: 3, maxRows: 6 }} />
        <Space wrap><Button type="primary" loading={busy} disabled={pendingJob(draft) || !content.trim()} onClick={() => send()}>{mode === 'ask' ? '发送讨论' : '暂停并提出修改'}</Button>
          {!draft.plan && <Button disabled={busy || pendingJob(draft)} onClick={() => send('plan', content.trim() || '根据原始问题和已有讨论，形成一份可审阅的研究计划。未确定的事情请列出，不要擅自替我决定。')}>整理第一版计划</Button>}
          <Text type="secondary">讨论不会更改执行；调整计划会申请暂停，等待你确认新版本。</Text></Space>
        {draft.discussion_usage && <Text type="secondary">讨论已完成调用 {draft.discussion_usage.calls} 次 · 已确认 Token {draft.discussion_usage.input_tokens + draft.discussion_usage.output_tokens} · 用量未知 {draft.discussion_usage.unknown_usage} 次</Text>}
      </div>}
    </Card>
    {draft && <Card title="研究计划" extra={draft.plans?.length ? <Select aria-label="计划版本" value={entry?.version} onChange={setVersion}
      options={draft.plans.map(p => ({ value: p.version, label: `第 ${p.version} 版${p.run_id ? ' · 已确认过执行' : ''}` }))} /> : undefined}>
      {!plan || !entry ? <Empty description="还没有计划。先讨论，或点击“整理第一版计划”。" /> : <div className="space-y-4">
        <Space wrap><Tag color={entry.admission.ready ? 'green' : 'orange'}>{entry.admission.ready ? '具备当前工具执行条件，待你确认' : '准备方案：有缺项，暂不能执行'}</Tag>
          {!latest && <Tag>历史版本，仅供查看</Tag>}{draft.needs_plan && <Tag color="orange">修改处理中，旧计划不能启动</Tag>}</Space>
        <h3 className="text-lg font-semibold">{plan.title}</h3>
        <div><Text strong>要回答的问题</Text><Paragraph>{plan.question}</Paragraph></div>
        <div><Text strong>对象与范围</Text><Paragraph>{plan.subject}</Paragraph></div>
        <div><Text strong>怎样研究</Text><Paragraph>{plan.method}</Paragraph><Text type="secondary">本版计划至多 {plan.candidate_limit} 个候选</Text></div>
        <div className="grid md:grid-cols-2 gap-4">
          <div><Text strong>执行步骤</Text><ol className="list-decimal pl-5 space-y-1">{plan.steps.map((v, i) => <li key={i}>{v}</li>)}</ol></div>
          <div><Text strong>你会拿到什么</Text>{bullets(plan.outputs)}</div>
          <div><Text strong>与什么比较</Text>{bullets(plan.baselines)}</div>
          <div><Text strong>怎样判断结果</Text>{bullets(plan.criteria)}</div>
        </div>
        {plan.questions.length > 0 && <Alert type="warning" message="这些事情需要先讨论确定" description={bullets(plan.questions)} />}
        <div><Text strong>准备情况</Text>{entry.admission.checks.map(c => <div key={c.name} className="py-1"><Tag color={c.ready ? 'green' : 'orange'}>{c.ready ? '已具备' : '待准备'}</Tag><Text strong>{c.name}：</Text>{c.detail}</div>)}</div>
        <div><Text strong>这次不能说明什么</Text>{bullets(plan.limitations)}</div>
        {plan.expression && <Paragraph code>{plan.expression}</Paragraph>}
        {draft.inventory && <Collapse items={[{ key: 'data', label: '核对实际数据范围与现有工具边界', children: <div className="space-y-2">
          <Paragraph>数据版本：{draft.inventory.snapshot_id} · {draft.inventory.market} · {draft.inventory.universe?.size} 只股票</Paragraph>
          {Object.entries(draft.inventory.dates).map(([name, dates]) => <div key={name}>{({ train: '训练区间', valid: '验证区间', test: '开发比较区间' } as Record<string, string>)[name] || name}：{dates.join(' 至 ')}</div>)}
          <Paragraph>当前模板字段：{draft.inventory.features.join('、')}</Paragraph>{bullets(draft.inventory.unavailable.map(v => `尚未支持：${v}`))}
        </div> }]} />}
        <Space wrap>
          {!entry.run_id && <Button type="primary" disabled={!canApprove || busy || !cap.ready || !!draft.run && active.has(draft.run.status)} onClick={() => beginReview('start')}>审阅并确认执行</Button>}
          {entry.run_id && latest && draft.run_id && <Button onClick={() => onRun(draft.run_id!)}>查看本计划的执行过程</Button>}
          {entry.run_id && latest && draft.run && !active.has(draft.run.status) && draft.run.status !== 'completed' && <Button disabled={!canApprove || busy || !cap.ready} onClick={() => beginReview('resume')}>审阅并继续此计划</Button>}
          <Button disabled={busy || pendingJob(draft)} onClick={() => { setMode('revise'); panel.current?.scrollIntoView({ behavior: 'smooth' }); }}>我想调整，先讨论</Button>
        </Space>
        {draft.run && <Alert type="info" message={`关联执行：${runStates[draft.run.status] || draft.run.status} · 已核验 ${draft.run.completed_experiments} 个实验`}
          description={draft.run.active ? `${draft.run.active.submitted ? '当前实验已提交计算' : '当前实验尚未提交计算'}：${draft.run.active.proposal.hypothesis}` : '详细步骤、实验结果与暂停/取消操作见执行过程。'} />}
      </div>}
    </Card>}
    <Modal title={`确认${review?.action === 'resume' ? '继续' : '执行'}第 ${review?.version} 版计划`} open={!!review} onCancel={() => { if (!busy) setReview(null); }}
      onOk={execute} confirmLoading={busy} okText="确认，开始执行" okButtonProps={{ disabled: !checked || !canApprove || review?.version !== draft?.plan?.version }} cancelText="返回讨论">
      <div className="space-y-4">
        <Paragraph strong>{plan?.question}</Paragraph><Paragraph>{plan?.subject}</Paragraph>
        <Paragraph>{review?.action === 'resume' ? '继续原计划的检查点，沿用原执行模型和候选设置。' : '将按上方计划创建一次执行；重复确认会打开同一次执行。'}执行节点：{cap.environment}。</Paragraph>
        <label className="block">最长运行小时 <InputNumber aria-label="执行时限" value={review?.hours} min={0.1} max={8} step={0.5} disabled={busy}
          onChange={v => { const n = v || 2; setHours(n); if (review) setReview({ ...review, hours: n }); }} /></label>
        {review?.action === 'start' && <Space wrap><Select aria-label="执行模型" value={review.model} onChange={v => setReview({ ...review, model: v })} options={cap.models.map(value => ({ value, label: value }))} />
          <Text>本计划至多 {review.candidate_limit} 个候选；改变数量请返回调整计划。</Text></Space>}
        <Paragraph>到时停止并保存；你可以中途暂停、取消，或提出修改后重新确认。实际结果可能否定假设，也可能因数据或工具问题无法完成。</Paragraph>
        <Checkbox checked={checked} onChange={e => setChecked(e.target.checked)}>我已核对问题、对象、步骤和产出，同意执行这版计划</Checkbox>
        {error && <Alert type="error" message={error} />}
      </div>
    </Modal>
  </div>;
}
