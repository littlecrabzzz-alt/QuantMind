import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Alert, Button, Select, Spin, Table, Tag } from 'antd';
import { SERVICE_ENDPOINTS } from '../../../config/services';
import { authService } from '../../../features/auth/services/authService';

type Row = Record<string, string | number | boolean | null>;
type CalendarContext = { state: string; complete: boolean; calendar_through: string | null;
    required_month_end: string; next_month_first_session: string | null; next_two_sessions: string[];
    reason: string; calendar_sha256: string };
type Schedule = { state: string; checked_at: string; source_checked_at?: string; usable_date?: string; reasons?: string[];
    wall_clock_utc?: string; wall_clock_shanghai?: string; due?: boolean | null; due_reason?: string;
    fundamentals?: { mode: string; as_of?: string; lag_note?: string } };
type Account = {
    name: string;
    state: string;
    spec: { initial_cash: number; status: string; execution?: string; margin_modelled?: boolean;
        etf_adjustment_model?: string; etf_cash_dividend_history_verified?: boolean;
        multiplier?: string; calendar_context?: string };
    error?: string;
    identity?: { created_at: string; migration: string; source_created_at?: string; code_sha256: string;
        owner: { user_id: string; tenant_id: string };
        registry: { strategy_id: string; frozen_source_id: string; runtime_code_sha256: string } };
    run?: { state: string; error?: string; last_date?: string; new_sessions?: number; calendar_context?: CalendarContext };
    schedule?: { state: string; reasons?: string[]; error?: string; last_date?: string; calendar_context?: CalendarContext };
    nav?: Row[];
    positions?: Row[];
    trades?: Row[];
    targets?: Row[];
    signals?: { date: string; weights: Record<string, number> }[];
    observations?: Row[];
    reconciliation?: Record<string, unknown>[];
    inception_reconciliation?: Record<string, unknown>[];
};

const number = (value: unknown) => typeof value === 'number'
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: 6 }) : String(value ?? '—');
const day = (value: unknown) => String(value ?? '').slice(0, 10);

function Records({ rows, fields }: { rows: Row[]; fields: string[] }) {
    return <Table<Row> size="small" scroll={{ x: true }} pagination={{ pageSize: 12 }}
        rowKey={(_, index) => String(index)} dataSource={rows}
        columns={fields.map(key => ({ title: key, dataIndex: key,
            render: (value: unknown) => key === 'date' ? day(value) : number(value) }))} />;
}

export default function FrozenPaperPage({ tenantId }: { tenantId: string }) {
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [scheduler, setScheduler] = useState<Schedule | null>(null);
    const [selected, setSelected] = useState('lowvol');
    const [loading, setLoading] = useState(false);
    const [updating, setUpdating] = useState(false);
    const [error, setError] = useState('');
    const refresh = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const token = authService.getAccessToken();
            const response = await axios.get<{ accounts: Account[]; scheduler?: Schedule }>(
                `${SERVICE_ENDPOINTS.API_GATEWAY}/simulation/frozen-paper/accounts`,
                { headers: { 'X-Tenant-ID': tenantId, ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
            setUpdating(false);
            setAccounts(response.data.accounts);
            setScheduler(response.data.scheduler ?? null);
        } catch (failure) {
            if (axios.isAxiosError(failure) && failure.response?.status === 409
                && failure.response.data?.detail?.state === 'updating') {
                setUpdating(true);
            } else {
                setUpdating(false);
                setError(failure instanceof Error ? failure.message : String(failure));
            }
        } finally { setLoading(false); }
    }, [tenantId]);
    useEffect(() => {
        setAccounts([]);
        setScheduler(null);
        setUpdating(false);
        void refresh();
    }, [refresh]);
    const account = accounts.find(item => item.name === selected);
    const latest = account?.nav?.[account.nav.length - 1];
    const positions = account?.positions?.filter(row => day(row.date) === day(latest?.date)) ?? [];
    const fees = account?.trades?.reduce((sum, row) => sum + Number(row.fee), 0);
    const calendarContext = account?.schedule?.calendar_context ?? account?.run?.calendar_context;
    return <div className="h-full overflow-auto p-5 space-y-4">
        <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold">冻结纸面观察</h2><Tag color="orange">OBSERVATION · 无交易权限</Tag>
            <Button onClick={() => void refresh()} loading={loading}>刷新账本</Button>
        </div>
        <Alert type="warning" showIcon message="历史补跑全部标记 replay，不计为历史真实前向证据；不代表策略通过或实盘授权。"
            description="原三个账户保留原账本字节和开户时间；其余账户使用本次真实创建时间，历史重放单独记录。期货为整手、合约乘数、逐日结算和双边移仓费用；不模拟保证金、强平或现金利息。页面只读，与每日命令读取同一份持久账本。" />
        {error && <Alert type="error" message={error} />}
        {updating && <Alert type="info" showIcon message="账本更新中（updating）"
            description={latest
                ? `本次没有读取财务；保留上次成功读取的真实账本（末日 ${day(latest.date)}），不是本次更新结果。可在日更完成后手动刷新。`
                : '本作用域尚无已读取的真实财务快照；更新期间不生成或填充现金、余额、持仓。可在日更完成后手动刷新。'} />}
        {scheduler && <Alert type={scheduler.state === 'blocked' ? 'error' : 'info'} showIcon
            message={`自动日更：${scheduler.state} · QA可用末日 ${scheduler.usable_date || '未就绪'}`}
            description={`UTC ${scheduler.wall_clock_utc || scheduler.checked_at}；上海 ${scheduler.wall_clock_shanghai || '未知'}；due=${String(scheduler.due)} ${scheduler.due_reason || ''}；来源QA ${scheduler.source_checked_at || '尚未发布'}；${scheduler.reasons?.join('；') || '逐户状态如下，不代表八户全部通过。'}${scheduler.fundamentals?.mode === 'pinned' ? `；PIT固定截至 ${scheduler.fundamentals.as_of}：${scheduler.fundamentals.lag_note}` : ''}`} />}
        <Spin spinning={loading}>
            <Table<Account> size="small" rowKey="name" pagination={false} dataSource={accounts}
                columns={[
                    { title: '账户', dataIndex: 'name' },
                    { title: '授权资金', render: (_, row) => number(row.spec.initial_cash) },
                    { title: '账本状态', render: (_, row) => row.run?.state === 'blocked' || row.run?.state === 'pending'
                        ? <Tag color={row.run.state === 'blocked' ? 'error' : 'gold'}>{row.run.state}</Tag> : row.state },
                    { title: '日更/来源准入', render: (_, row) => row.schedule?.state || '未触发' },
                    { title: '末日', render: (_, row) => day(row.nav?.[row.nav.length - 1]?.date) || '—' },
                    { title: '阻断原因', render: (_, row) => row.schedule?.error || row.schedule?.reasons?.join('；') || row.run?.error || row.error || '—' },
                ]} />
            <Select value={selected} onChange={setSelected} className="w-72 my-4"
                options={accounts.map(item => ({ value: item.name, label: item.name }))} />
            {account?.error && <Alert type="error" message={account.error} />}
            {account?.run?.error && <Alert type={account.run.state === 'pending' ? 'warning' : 'error'} message={account.run.error} />}
            {account?.schedule && (account.schedule.error || account.schedule.reasons?.length) ? <Alert type="warning"
                message={account.schedule.error || account.schedule.reasons?.join('；')} /> : null}
            {account?.spec.etf_adjustment_model && <Alert type="warning" showIcon
                message="ETF 复权份额 proxy 不是现金分红账本"
                description="原引擎按复权因子调整份额，不模拟真实派息现金。实际前日持有期间遇非 1/缺失因子比或已知 fund_div 除息事件即阻断追加，不凭因子造现金或新股；未观察到事件不代表完整现金分红历史已核验。旧报告与冻结参数不重写。" />}
            {account?.spec.calendar_context && <Alert type="info" showIcon
                message="I7 需完整月界日历，只有下一开市日不等于月末已确认"
                description="从重放起始月到可用末日所在月末必须有完整真实 SSE 开/闭市行，并确认下一月首个开市日及可用日后两个开市日。截断日历仅使 I7 pending；不把样本末日当月末、不改 TOM 规则，其余账户独立准入。" />}
            {calendarContext && <details><summary>I7 真实日历上下文证明：{calendarContext.state}</summary>
                <pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(calendarContext, null, 2)}</pre>
            </details>}
            {account?.spec.multiplier && <Alert type="info" showIcon
                message="商品期货消费有来源证据的 normalized_multiplier"
                description="官方 fut_basic 的 raw multiplier 仅适用国债/指数期货，商品 null 合法。数据源按真实交易/报价单位归一名义乘数（JD 5 吨/每 500 千克 = 10），保留原字段、公式和对象哈希；runtime 不直接复制 per_unit、不重复换算。实际 warmup/replay 合同闭包单位未知则阻断，无关历史缺值不伪永久阻塞；45 品种及冻结信号/参数不变。" />}
            {account?.identity && <div className="text-xs break-all space-y-1">
                <div>真实创建：{account.identity.created_at}；原账户创建：{account.identity.source_created_at || '不存在来源账户'}</div>
                <div>迁移状态：{account.identity.migration}；代码 SHA256：{account.identity.code_sha256}</div>
                <div>执行口径：{account.spec.execution || '冻结原策略次一交易日开盘'}；累计实际记账费用：{number(fees)}</div>
                <div>归属：{account.identity.owner.user_id} / {account.identity.owner.tenant_id}；
                    注册策略：{account.identity.registry.strategy_id}；冻结版本：{account.identity.registry.frozen_source_id}</div>
                <details><summary>冻结参数 / 费用模型与官方证据</summary>
                    <pre className="whitespace-pre-wrap">{JSON.stringify(account.spec, null, 2)}</pre>
                </details>
            </div>}
            {latest && <>
                <h3 className="font-bold mt-4">现金 / 净值 / 仓位</h3>
                <div>账本末日 {day(latest.date)}；现金 {number(latest.cash)}；NAV {number(latest.nav)}；敞口 {number(latest.exposure)}</div>
                <Records rows={positions} fields={['date', 'code', 'shares']} />
                <h3 className="font-bold mt-4">逐日账本</h3>
                <Records rows={account?.nav ?? []} fields={['date', 'cash', 'nav', 'exposure']} />
                <h3 className="font-bold mt-4">成交与费用</h3>
                <Records rows={account?.trades ?? []} fields={['date', 'code', 'side', 'shares', 'price', 'value', 'fee']} />
                <h3 className="font-bold mt-4">已生成信号（收盘日）</h3>
                <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(account?.signals, null, 2)}</pre>
                {account?.inception_reconciliation && <details>
                    <summary>原 t13 pending / 已发表目标 / 当前 runtime 全精度对账</summary>
                    <pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(account.inception_reconciliation, null, 2)}</pre>
                </details>}
                <h3 className="font-bold mt-4">执行目标</h3>
                <Records rows={account?.targets ?? []} fields={['date', 'code', 'weight']} />
                <h3 className="font-bold mt-4">观察记录（重放 / 及时前向明确分列）</h3>
                <Records rows={account?.observations ?? []} fields={['date', 'kind', 'recorded_at', 'input_version', 'historical_forward_evidence']} />
                <details><summary>来源与目标逐日对账 / 版本证据</summary>
                    <pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(account?.reconciliation, null, 2)}</pre>
                </details>
            </>}
        </Spin>
    </div>;
}
