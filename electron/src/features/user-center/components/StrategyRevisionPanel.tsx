import React, { useEffect, useState } from 'react';
import { Alert, Button, Input, Select, Space, Tag } from 'antd';
import { useNavigate } from 'react-router-dom';
import { strategyManagementService as service } from '../../../services/strategyManagementService';

export default function StrategyRevisionPanel({ strategyId }: { strategyId: string }) {
  const navigate = useNavigate();
  const [versions, setVersions] = useState<any[]>([]);
  const [revision, setRevision] = useState<any>(null);
  const [source, setSource] = useState('');
  const [sourceName, setSourceName] = useState('strategy.py');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState('2014-08-01');
  const [end, setEnd] = useState('2026-03-24');
  const [edit, setEdit] = useState(false);
  const [parameters, setParameters] = useState('');
  const [execution, setExecution] = useState('');
  const [extraFiles, setExtraFiles] = useState<any[]>([]);
  const fail = (e: any) => setError(String(e?.response?.data?.detail || e.message || '请求失败'));
  const select = async (id: string) => {
    const r = await service.executionRequest(`strategies/${strategyId}/revisions/${id}`);
    setRevision(r); setSource(r.code); setSourceName('strategy.py'); setParameters(JSON.stringify(r.parameters, null, 2));
    setExecution(JSON.stringify(r.execution, null, 2)); setEnd(r.data_binding.development_end); setEdit(false);
  };
  const load = async () => {
    const rows = await service.executionRequest<any[]>(`strategies/${strategyId}/revisions`);
    setVersions(rows);
    if (rows.length) await select(rows[0].revision_id);
  };
  useEffect(() => { setRevision(null); setVersions([]); void load().catch(fail); }, [strategyId]);
  const act = async (fn: () => Promise<void>) => { setBusy(true); setError(''); try { await fn(); } catch (e) { fail(e); } finally { setBusy(false); } };
  return <section className="space-y-3 border rounded-lg p-3" data-testid="strategy-revisions">
    <h3 className="font-semibold">可执行版本</h3>
    {error && <Alert type="error" message={error} />}
    {!versions.length && <p>尚未发布可执行版本。研究草稿不自动成为运行候选。</p>}
    {!!versions.length && <Select className="w-full" aria-label="策略版本" value={revision?.revision_id}
      options={versions.map(r => ({ value: r.revision_id, label: `v${r.version} · ${r.revision_id.slice(0, 12)} · ${r.created_at}` }))}
      onChange={id => void act(() => select(id))} />}
    {revision && <>
      <Space wrap><Tag color="blue">公共 ETF 账本</Tag><Tag>开发回测</Tag>
        <Button size="small" onClick={() => navigate(`/alpha-research?research=${revision.research_case_id}`)}>来源研究</Button>
        <Button size="small" onClick={() => navigate(`/backtest?strategyId=${strategyId}`)}>回测记录与对比</Button>
        <Button size="small" onClick={() => navigate(`/trading?paper=${strategyId}`)}>虚拟账户与监控</Button>
      </Space>
      <p className="text-xs break-all">数据：{revision.data_binding.package_id} · {revision.data_binding.manifest_sha256.slice(0, 12)}<br />代码：{revision.code_sha256.slice(0, 12)} · 执行引擎：{revision.engine_sha256.slice(0, 12)}</p>
      <Alert type="info" message={`开发回测截至 ${revision.data_binding.development_end}；保留段 ${revision.data_binding.holdout_start} 至 ${revision.data_binding.holdout_end} 禁止用于开发。${revision.exposure === 'already_used' ? '该研究此前看过全历史，保留段不能称为盲测。' : ''}`} />
      <Space wrap><label>开始 <Input type="date" value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>结束 <Input type="date" value={end} max={revision.data_binding.development_end} onChange={e => setEnd(e.target.value)} /></label>
        <Button loading={busy} type="primary" onClick={() => void act(async () => {
          const run = await service.executionRequest(`strategies/${strategyId}/backtests`, { revision_id: revision.revision_id,
            key: crypto.randomUUID(), start_date: start, end_date: end });
          navigate(`/backtest?backtest=${run.backtest_id}`);
        })}>运行并登记回测</Button>
      </Space>
      <Button loading={busy} onClick={() => void act(async () => {
        await service.executionRequest(`strategies/${strategyId}/paper-runs`, { revision_id: revision.revision_id });
        navigate(`/trading?paper=${strategyId}`);
      })}>冻结此版本到独立虚拟账户</Button>
      <details><summary>代码、参数与原始脚本（已保存到平台）</summary>
        <Space wrap className="my-2"><Button size="small" onClick={() => { setSource(revision.code); setSourceName('strategy.py'); setEdit(false); }}>可执行 strategy.py</Button>
          {revision.source_files.map((f: any) => <Button key={f.name} size="small" onClick={() => { setSource(f.content); setSourceName(f.name); setEdit(false); }}>{f.name}</Button>)}
          <Button size="small" onClick={() => { const u = URL.createObjectURL(new Blob([source], { type: 'text/plain' })); const a = document.createElement('a'); a.href = u; a.download = sourceName; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000); }}>下载当前代码</Button>
        </Space>
        <pre className="text-xs whitespace-pre-wrap max-h-80 overflow-auto bg-slate-50 p-2">{source}</pre>
        <pre className="text-xs whitespace-pre-wrap">{JSON.stringify({ parameters: revision.parameters, execution: revision.execution }, null, 2)}</pre>
      </details>
      <Button onClick={() => { setEdit(!edit); setSource(revision.code); }}>编辑并发布新版本</Button>
      {edit && <div className="space-y-2">
        <label>策略代码<Input.TextArea aria-label="策略代码" rows={12} value={source} onChange={e => setSource(e.target.value)} /></label>
        <label>参数 JSON<Input.TextArea rows={5} value={parameters} onChange={e => setParameters(e.target.value)} /></label>
        <label>执行与风险 JSON<Input.TextArea rows={5} value={execution} onChange={e => setExecution(e.target.value)} /></label>
        <label>附加原始脚本<input type="file" multiple accept=".py,.json,.md" onChange={e => void Promise.all(Array.from(e.target.files || []).map(async f => ({ name: f.name, content: await f.text(), source_revision: 'user-upload' }))).then(setExtraFiles)} /></label>
        <Button loading={busy} onClick={() => void act(async () => {
          const p = JSON.parse(parameters), x = JSON.parse(execution);
          await service.updateStrategy(strategyId, { code: source });
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source)))).map(b => b.toString(16).padStart(2, '0')).join('');
          await service.executionRequest(`strategies/${strategyId}/revisions`, {
            expected_code_sha256: hash, research_case_id: revision.research_case_id, group: revision.group,
            parameters: p, execution: x, exposure: revision.exposure, source_revision: 'platform-edit',
            source_files: [...revision.source_files.filter((f: any) => !extraFiles.some(n => n.name === f.name)), ...extraFiles]
              .map(({ name, content, source_revision }: any) => ({ name, content, source_revision })),
          }); await load(); setEdit(false);
        })}>保存不可变版本</Button>
      </div>}
    </>}
  </section>;
}
