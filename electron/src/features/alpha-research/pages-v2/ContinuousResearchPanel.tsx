import React, { useEffect, useState } from 'react';
import { Alert, Button, Progress, Select, Tag } from 'antd';
import { strategyManagementService as api } from '../../../services/strategyManagementService';

type Task = { id: string; question: string; topic: string; status: string; step: string; attempts: number;
  kind?:string; evidence?:{id:string;sha256:string;title:string;[key:string]:unknown};
  last_error?: string; last_activity?: number; retry_at?: number; usage: {input:number; output:number; unknown_calls:number};
  experiments: Record<string, {name:string; strategy_id?:string; revision_id?:string; factor_id?:string; kind?:string; backtest_id:string; hypothesis:string}>;
  reports: {text:string; at:number; followups?:{question:string;task_id?:string}[]}[]; };
type Program = { id:string; status:string; desired:string; heartbeat_stale:boolean; last_heartbeat?:number;
  runtime?:{model:string;thinking:string}; contract:{end_date:string; concurrency:number}; quota_state?:string; quota_check_at?:number;
  quota:{status:string; remaining_percent:number|null; reset_at?:number; observed_at?:number;
    reason?:string; plan?:string; weekly?:{remaining_percent:number}|null; tools?:{remaining_percent:number}|null};
  tasks:Record<string,Task>; stock_scope_history?:{at:number;reason:string;contract:{snapshot_id:string};tasks:Record<string,Task>}[];
  events:{seq:number; at:number; kind:string; task_id?:string; outcome?:string}[]; };
const labels:Record<string,string> = {running:'运行中', stopped:'已停止', starting:'正在启动', stopping:'正在停止',
  needs_attention:'有任务需要检查', waiting_compute:'等待公共计算', queued:'排队', retrying:'等待重试', waiting_quota:'等待额度恢复', quota_unknown:'额度未知，暂停派发',
  done:'已交研究报告', blocked:'需要检查', cancelled:'已停止', failed:'失败', idle:'队列已完成', available:'额度可用'};
const date = (v?:number) => v ? new Date(v*1000).toLocaleString('zh-CN',{hour12:false}) : '未记录';
export default function ContinuousResearchPanel() {
  const [programs,setPrograms]=useState<Program[]>([]), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  const [taskFilter,setTaskFilter]=useState('all');
  const refresh=async()=>{try{setPrograms(await api.executionRequest('continuous-research'));setError('');}
    catch{setError('持续研究服务暂不可达；这里不据此判定任务成功或失败。');}};
  useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),10000);return()=>clearInterval(timer);},[]);
  const control=async(id:string,op:string,task_id?:string)=>{setBusy(true);try{await api.executionRequest(`continuous-research/${id}/command`,{op,...(task_id?{task_id}: {})});await refresh();}
    catch(e:any){setError(e?.response?.data?.detail||'操作失败');}finally{setBusy(false);}};
  if(!programs.length) return error ? <Alert type="warning" message={error}/> : null;
  return <div data-testid="continuous-research" className="rounded-xl border border-border p-4 space-y-4">
    <div className="flex justify-between"><div><h2 className="font-semibold text-lg">GLM 持续研究</h2>
      <p className="text-sm text-muted-foreground">研究数据完整性、方法与证据，探索 A股因子和资产配置。因子、策略、回测进入原生模块，复核报告关联原始证据。</p></div>
      <Button onClick={()=>void refresh()}>刷新</Button></div>
    {error&&<Alert type="warning" message={error}/>}
    {programs.map(p=><div key={p.id} className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center"><Tag color={p.heartbeat_stale?'orange':'green'}>
        {p.heartbeat_stale?'协调程序心跳陈旧':labels[p.status]||p.status}</Tag><span className="text-sm">{p.runtime?.model||"GLM"} · effort {p.runtime?.thinking||"等待运行上报"} · 并发 {p.contract.concurrency} · 开发数据截止 {p.contract.end_date}</span>
        <Button loading={busy} disabled={p.desired==='running'} onClick={()=>void control(p.id,'start')}>启动 / 接续</Button>
        <Button loading={busy} disabled={p.desired==='stopped'} onClick={()=>void control(p.id,'stop')}>停止派发与模型调用</Button>
      </div>
      <div className="text-sm rounded bg-muted p-3">
        共 {Object.keys(p.tasks).length} 个研究问题 · 已交报告 {Object.values(p.tasks).filter(t=>t.reports.length).length} 个 · 待检查 {Object.values(p.tasks).filter(t=>t.status==='blocked'||t.status==='failed').length} 个 · 独立公共回测 {new Set(Object.values(p.tasks).flatMap(t=>Object.values(t.experiments).map(e=>e.backtest_id))).size} 份
        <p>累计模型上报：输入 {Object.values(p.tasks).reduce((n,t)=>n+t.usage.input,0).toLocaleString()} / 输出 {Object.values(p.tasks).reduce((n,t)=>n+t.usage.output,0).toLocaleString()} token；跨额度窗口累计，不等于当前窗口消耗。报告均为开发研究，数量不代表已验证策略。</p>
      </div>
      <div className="grid md:grid-cols-2 gap-4 text-sm">
        <div><b>5 小时额度余量：{p.quota.status==='known'&&p.quota.remaining_percent!==null?`${p.quota.remaining_percent}%${Date.now()/1000-(p.quota.observed_at||0)>180?'（上次查询）':''}`:'未知'}</b>
          <Progress percent={p.quota.remaining_percent??0} showInfo={false} status={p.quota.status==='known'?'normal':'exception'}/>
          <p>{labels[p.quota_state||'']||'等待查询'} · 查询：{date(p.quota.observed_at)}</p>
          <p>供应商重置提示：{date(p.quota.reset_at)}；恢复前会再次核验余额。</p>
          <p>{p.quota.weekly?`接口返回周额度余量 ${p.quota.weekly.remaining_percent}%`:'接口未返回周额度，不设置周额度限制'}
            {p.quota.tools?` · MCP 工具额度另计，余量 ${p.quota.tools.remaining_percent}%`:''}</p>
        </div><div><p>心跳：{date(p.last_heartbeat)}</p><p>额度是供应商报告的百分比，不能换算为精确剩余 token 数。</p>
          <p>保留验证集不开放；开发结果均待独立复核，不自动进入虚拟盘或实盘。</p>
          <p>停止会撤销研究写入租约；已经提交的公共回测可以继续完成并留存。</p></div>
      </div>
      <Select aria-label="研究任务类型" value={taskFilter} onChange={setTaskFilter} style={{minWidth:220}} options={[{value:'all',label:'全部研究任务'},{value:'evidence_review',label:'数据检查与证据复核'},{value:'experiments',label:'因子与策略实验'}]}/>
      <div className="space-y-2">{Object.values(p.tasks).filter(t=>taskFilter==='all'||(taskFilter==='evidence_review'?t.kind==='evidence_review':t.kind!=='evidence_review')).sort((a,b)=>(b.last_activity||0)-(a.last_activity||0)).map(t=><details key={t.id} className="border border-border rounded p-3" open={t.status==='running'}>
        <summary className="cursor-pointer"><Tag>{labels[t.status]||t.status}</Tag>{t.kind==='evidence_review'&&<Tag color="blue">数据/证据复核</Tag>}{t.question}</summary>
        <p className="text-sm mt-2">当前：{t.step} · 领取 {t.attempts} 次 · 最近进展 {date(t.last_activity)}</p>
        {t.evidence&&<details className="my-2 text-sm"><summary className="cursor-pointer">只读证据包：{t.evidence.title} · {t.evidence.sha256.slice(0,12)}</summary>
          <p>证据复核不要求新回测，模型结论仍待独立核验。</p><Button size="small" onClick={()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(t.evidence,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`evidence-${t.evidence!.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}>下载原始证据包</Button>
          <pre className="whitespace-pre-wrap max-h-80 overflow-auto">{JSON.stringify(t.evidence,null,2)}</pre></details>}
        {!!t.retry_at&&['retrying','waiting_quota'].includes(t.status)&&<p className="text-sm">下次可尝试：{date(t.retry_at)}，仍需额度通过。</p>}
        <p className="text-sm text-amber-700">{t.last_error&&t.last_error!=="cancelled"?`最近受阻原因：${t.last_error}`:""}</p>
        {["blocked","failed"].includes(t.status)&&<Button size="small" onClick={()=>void control(p.id,"retry_task",t.id)}>问题处理后重新入队</Button>}
        <p className="text-sm">已报告输入 {t.usage.input.toLocaleString()} / 输出 {t.usage.output.toLocaleString()} token
          {t.usage.unknown_calls?`；${t.usage.unknown_calls} 次调用用量未返回`:''}</p>
        {Object.entries(t.experiments).map(([key,x])=><div key={key} className="my-2 text-sm">
          <b>{x.name}</b> · {x.strategy_id?<a className="text-blue-500 underline" href={`#/user-center?tab=strategies&strategyId=${encodeURIComponent(x.strategy_id)}`}>策略 {x.strategy_id} / 版本 {x.revision_id?.slice(0,10)}</a>:x.factor_id?<a className="text-blue-500 underline" href={`#/alpha-research?page=library&factor=${encodeURIComponent(x.factor_id)}`}>因子库候选</a>:<span>股票冻结基线</span>} · <a className="text-blue-500 underline" href={`#/backtest?backtest=${encodeURIComponent(x.backtest_id)}`}>查看公共回测</a>
          <details><summary className="cursor-pointer text-muted-foreground">预登记假设与判别条件</summary><p>{x.hypothesis}</p></details></div>)}
        {t.reports.map((r,i)=><details key={i}><summary className="cursor-pointer">研究报告 · {date(r.at)} · 待独立复核</summary><pre className="whitespace-pre-wrap text-sm bg-muted p-3 mt-2">{r.text}</pre>
          {r.followups?.filter(f=>!f.task_id).map((f,j)=><p key={j} className="text-sm">后续问题已保存，等待队列空位：{f.question}</p>)}</details>)}
      </details>)}</div>
      {!!p.stock_scope_history?.length&&<details><summary className="cursor-pointer text-sm">工程输入修复归档（不计为因子研究结论）</summary>
        {p.stock_scope_history.map((h,i)=><div key={i} className="text-sm mt-2"><p>{date(h.at)} · {h.contract.snapshot_id} · {h.reason}</p>
          {Object.values(h.tasks).flatMap(t=>Object.values(t.experiments)).map((e,j)=><p key={j}><a className="text-blue-500 underline" href={`#/backtest?backtest=${encodeURIComponent(e.backtest_id)}`}>{e.name} · 原回测记录</a></p>)}</div>)}
      </details>}
      <details><summary className="cursor-pointer text-sm">最近事件</summary><div className="text-xs space-y-1 mt-2">{p.events.slice(-20).reverse().map(e=><p key={e.seq}>{date(e.at)} · {e.kind} · {e.task_id?.slice(0,8)} {e.outcome&&`· ${labels[e.outcome]||e.outcome}`}</p>)}</div></details>
    </div>)}
  </div>;
}
