import React, { useEffect, useState } from 'react';
import { Table, Button, message, Space, Tag, Modal, Tooltip, Empty, Drawer, Alert, Descriptions } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import {
    CloudOutlined,
    DeleteOutlined,
    ReloadOutlined,
    RocketOutlined,
    ExperimentOutlined,
    ExclamationCircleOutlined
} from '@ant-design/icons';
import { strategyManagementService } from '../../../services/strategyManagementService';
import { useAuth } from '../../../features/auth/hooks';
import type { StrategyFile } from '../../../types/backtest/strategy';

const { confirm } = Modal;

const formatCreatedAt = (raw: unknown): string => {
    if (raw === null || raw === undefined) return '--';
    const text = String(raw).trim();
    if (!text || text === '0') return '--';
    const ts = Date.parse(text);
    if (Number.isNaN(ts)) {
        const asNumber = Number(text);
        if (!Number.isFinite(asNumber) || asNumber <= 0) return '--';
        return new Date(asNumber).toLocaleString('zh-CN');
    }
    return new Date(ts).toLocaleString('zh-CN');
};

const CloudStrategyManagement: React.FC = () => {
    const { user } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [loading, setLoading] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [strategies, setStrategies] = useState<StrategyFile[]>([]);
    const [selected, setSelected] = useState<StrategyFile | null>(null);
    const [pagination, setPagination] = useState({
        current: 1,
        pageSize: 10,
        total: 0,
    });

    const fetchStrategies = async (page: number = 1, pageSize: number = 10) => {
        if (!user) return;

        setLoading(true);
        try {
            // 2026-02-14 统一架构：使用 strategyManagementService 获取
            const items = await strategyManagementService.loadStrategies();
            
            // 转换为 UserStrategy 格式以适配表格（以当前类型定义为准：使用 name 字段）
            const mapped: StrategyFile[] = items.map((item: any) => ({
                ...item,
                name: item?.name ?? item?.strategy_name ?? '未命名策略',
            }));

            setStrategies(mapped);
            setPagination({
                current: page,
                pageSize,
                total: mapped.length,
            });
        } catch (error: any) {
            console.error('获取策略列表失败:', error);
            if (error.message && !error.message.includes('404')) {
                message.error('获取策略列表失败: ' + error.message);
            }
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStrategies();
    }, [user]);

    useEffect(() => {
        const id = new URLSearchParams(location.search).get('strategyId');
        if (id) setSelected(strategies.find(s => s.id === id) ?? null);
    }, [location.search, strategies]);

    const researchLink = (strategy: StrategyFile) => {
        const id = strategy.parameters?.research_case_id;
        return typeof id === 'string' && /^[a-zA-Z0-9_-]+$/.test(id)
            ? `/alpha-research?research=${encodeURIComponent(id)}` : null;
    };

    const handleDelete = (strategy: StrategyFile) => {
        confirm({
            title: '确认删除策略?',
            icon: <ExclamationCircleOutlined />,
            content: `您确定要删除策略 "${strategy.name}" 吗？此操作不可恢复。`,
            okText: '删除',
            okType: 'danger',
            cancelText: '取消',
            onOk: async () => {
                if (!user) return;
                try {
                    await strategyManagementService.deleteStrategy(strategy.id);
                    message.success('策略已删除');
                    fetchStrategies();
                } catch (error: any) {
                    message.error('删除策略失败: ' + error.message);
                }
            },
        });
    };

    const handleSyncTemplates = async () => {
        if (!user) return;
        setSyncing(true);
        try {
            const res = await strategyManagementService.syncTemplates();
            if (res.success) {
                message.success(res.message || '模板同步成功');
                fetchStrategies(1, pagination.pageSize);
            }
        } catch (error: any) {
            message.error('同步模板失败: ' + error.message);
        } finally {
            setSyncing(false);
        }
    };

    const getStatusTag = (status: string) => {
        const statusMap: Record<string, { color: string; text: string }> = {
            draft: { color: 'default', text: '草稿' },
            repository: { color: 'blue', text: '仓库' },
            live_trading: { color: 'blue', text: '交易策略' },
            active: { color: 'blue', text: '已激活' },
            inactive: { color: 'default', text: '停止' },
            archived: { color: 'warning', text: '已归档' },
            paused: { color: 'warning', text: '暂停' },
            stopped: { color: 'default', text: '未运行' },
            running: { color: 'success', text: '运行中' },
            starting: { color: 'processing', text: '启动中' },
            unknown: { color: 'default', text: '状态未提供' },
        };

        const config = statusMap[status] || { color: 'default', text: status };
        return <Tag color={config.color}>{config.text}</Tag>;
    };

    const getTypeIcon = (type: string) => {
        // Simple mapping based on type string, default to experiment
        if (type?.toLowerCase().includes('quantitative') || type?.toLowerCase().includes('live')) return <RocketOutlined />;
        return <ExperimentOutlined />;
    };

    const columns = [
        {
            title: '策略名称',
            dataIndex: 'name', // 修改为 name
            key: 'name',
            render: (text: string, record: StrategyFile) => (
                <Space>
                    {getTypeIcon(record.language || '')}
                    <button className="font-medium text-blue-600 text-left" onClick={() => setSelected(record)}>{text}</button>
                </Space>
            ),
        },
        {
            title: '类型',
            dataIndex: 'language',
            key: 'strategy_type',
            render: (text: string) => <Tag>{text || '通用'}</Tag>,
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            render: (_: string, record: StrategyFile) => (
                <Space direction="vertical" size={0}>
                    {getStatusTag((record.base_status || record.status || 'unknown').toLowerCase())}
                    {record.effective_status && getStatusTag(record.effective_status.toLowerCase())}
                </Space>
            ),
        },
        {
            title: '创建时间',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (text: string) => formatCreatedAt(text),
        },
        {
            title: '操作',
            key: 'action',
            render: (_: any, record: StrategyFile) => (
                <Space size="middle">
                    <Button size="small" onClick={() => setSelected(record)}>查看配置</Button>
                    {researchLink(record) && <Button size="small" onClick={() => navigate(researchLink(record)!)}>历史回测</Button>}
                    <Tooltip title="删除策略">
                        <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={() => handleDelete(record)}
                        />
                    </Tooltip>
                </Space>
            ),
        },
    ];

    return (
        <div className="p-0">
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h2 className="text-lg font-medium flex items-center gap-2">
                        <CloudOutlined className="text-blue-500" />
                        策略管理
                    </h2>
                    <p className="text-gray-500 text-sm mt-1">查看当前平台中的策略配置、运行状态与关联研究</p>
                </div>
                <Space>
                    <Button
                        icon={<CloudOutlined />}
                        onClick={handleSyncTemplates}
                        loading={syncing}
                    >
                        同步模板
                    </Button>
                    <Button
                        icon={<ReloadOutlined />}
                        onClick={() => fetchStrategies(pagination.current, pagination.pageSize)}
                        loading={loading}
                    >
                        刷新
                    </Button>
                </Space>
            </div>

            <Table
                columns={columns}
                dataSource={strategies}
                rowKey="id"
                loading={loading}
                pagination={{
                    ...pagination,
                    onChange: (page, pageSize) => fetchStrategies(page, pageSize),
                    showSizeChanger: true,
                    showTotal: (total) => `共 ${total} 个策略`,
                }}
                locale={{
                    emptyText: (
                        <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="暂无云端策略"
                        />
                    ),
                }}
            />
            <Drawer title={selected?.name || '策略配置'} open={!!selected} width={660} onClose={() => {
                setSelected(null);
                if (new URLSearchParams(location.search).has('strategyId')) navigate('/user-center?tab=strategies', { replace: true });
            }}>
                {selected && <div className="space-y-4">
                    <p>{selected.description || '暂无策略说明'}</p>
                    <p>保存状态：{getStatusTag((selected.base_status || selected.status || 'unknown').toLowerCase())} 运行状态：{getStatusTag(selected.effective_status || 'unknown')}</p>
                    {selected.parameters?.configuration_only === true && <Alert type="info" showIcon message="候选配置已保存，持续虚拟盘尚未启动" description="历史研究与未来虚拟盘分别记录。保存配置不会自动启动调度或成交。" />}
                    {Array.isArray(selected.parameters?.activation_blockers) && selected.parameters.activation_blockers.map((reason, i) => <Alert key={i} type="warning" message={String(reason)} />)}
                    {researchLink(selected) && <Button type="primary" onClick={() => navigate(researchLink(selected)!)}>查看历史净值、持仓与订单</Button>}
                    <h3 className="font-semibold">已保存的规则与验证约定</h3>
                    <Descriptions bordered size="small" column={1}>
                        {typeof selected.parameters?.initial_cash_cny === 'number' && <Descriptions.Item label="初始虚拟本金">{selected.parameters.initial_cash_cny.toLocaleString()} 元</Descriptions.Item>}
                        {selected.parameters?.target_weights && typeof selected.parameters.target_weights === 'object' && <Descriptions.Item label="目标配置">{Object.entries(selected.parameters.target_weights).map(([symbol, weight]) => `${symbol} ${typeof weight === 'number' ? (weight * 100).toFixed(0) + '%' : '未提供'}`).join(' / ')}</Descriptions.Item>}
                        {Object.entries({ rebalance: '建仓与调仓', daily_review: '每天做什么', inception: '启动条件', defensive_allocation: '国债与现金', intervention: '人工介入' }).map(([key, label]) => typeof selected.parameters?.[key] === 'string' && <Descriptions.Item key={key} label={label}>{String(selected.parameters[key])}</Descriptions.Item>)}
                        {selected.parameters?.validation && typeof selected.parameters.validation === 'object' && Object.entries({ seen_history_through: '已看过的历史截至', future_holdout_start: '新的验证期从何时开始', changes: '修改规则后怎么办' }).map(([key, label]) => {
                            const value = (selected.parameters!.validation as Record<string, unknown>)[key];
                            return typeof value === 'string' && <Descriptions.Item key={key} label={label}>{value}</Descriptions.Item>;
                        })}
                    </Descriptions>
                    <details><summary className="cursor-pointer">完整配置（核对用）</summary><pre className="text-xs whitespace-pre-wrap bg-slate-50 p-3 rounded mt-2">{JSON.stringify(selected.parameters, null, 2)}</pre></details>
                </div>}
            </Drawer>
        </div>
    );
};

export default CloudStrategyManagement;
