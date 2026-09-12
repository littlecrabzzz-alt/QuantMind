import React, { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Select,
  Tag,
  Tabs,
} from "antd";
import {
  FileText,
  MessageSquare,
  Plus,
  Square,
  Upload,
  ArrowUpRight,
  Check,
} from "lucide-react";
import ReactECharts from "echarts-for-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLocation, useNavigate } from "react-router-dom";
import {
  researchAgent,
  type AgentCapabilities,
  type AgentCase,
} from "../services-v2/researchAgent";
import { SERVICE_ENDPOINTS } from "../../../config/services";
import { authService } from "../../auth/services/authService";

const labels: Record<string, string> = {
  idle: "等待你的决定",
  queued: "消息已收到",
  running: "Agent 正在处理",
  waiting_job: "计算在后台运行",
  stopping: "正在确认停止",
  paused: "已暂停",
  retrying: "模型限流，等待重试",
  completed: "已完成",
  failed: "失败",
  launching: "正在提交",
  missing: "执行结果待确认",
  blocked: "条件不足",
  cancelled: "已停止",
};
const tools: Record<string, string> = {
  inspect_research: "检查数据和作业",
  submit_plan: "提交研究计划",
  write_todos: "更新任务清单",
  read_file: "读取文件",
  write_file: "写入文件",
  edit_file: "修改文件",
  execute: "运行代码",
  submit_code_job: "启动后台计算",
  register_factor: "登记因子候选",
  register_strategy: "保存策略草稿",
  run_frozen_backtest: "启动训练和组合回测",
  ls: "查看目录",
  glob: "查找文件",
  grep: "搜索文件内容",
};
const messageState: Record<string, string> = {
  received: "已收到",
  read: "Agent 已读",
  answered: "已回复",
  interrupted: "已打断",
};
const errorText = (e: any) =>
  typeof e?.response?.data?.detail === "string"
    ? e.response.data.detail
    : "连接暂时中断，请恢复后查看状态。";
const panel = "rounded-xl border border-border bg-card p-4";

export default function AgentWorkspace() {
  const location = useLocation(),
    navigate = useNavigate();
  const queryId = new URLSearchParams(location.search).get("research");
  const [cap, setCap] = useState<AgentCapabilities | null>(null);
  const [cases, setCases] = useState<AgentCase[]>([]);
  const [current, setCurrent] = useState<AgentCase | null>(null);
  const [creating, setCreating] = useState(!queryId);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState(""),
    [subject, setSubject] = useState(""),
    [material, setMaterial] = useState("");
  const [model, setModel] = useState("glm-5.3-flash");
  const [message, setMessage] = useState("");
  const [reviewed, setReviewed] = useState(false),
    [hours, setHours] = useState(2),
    [maxJobs, setMaxJobs] = useState(4);
  const [tab, setTab] = useState("plan");
  const [preview, setPreview] = useState<{
    path: string;
    text?: string;
    image?: string;
  } | null>(null);
  const chat = useRef<HTMLDivElement>(null),
    followChat = useRef(true);
  const scope = useRef(""),
    active = useRef(queryId),
    locked = useRef(false);
  const requestKeys = useRef(new Map<string, string>());
  const key = (value: unknown) => {
    const encoded = JSON.stringify(value);
    if (!requestKeys.current.has(encoded))
      requestKeys.current.set(encoded, crypto.randomUUID());
    return requestKeys.current.get(encoded)!;
  };
  useEffect(() => {
    active.current = queryId;
    setCreating(!queryId);
    setCurrent(null);
    setPreview(null);
    setReviewed(false);
    setTab("plan");
    setMessage("");
    followChat.current = true;
  }, [queryId]);
  useEffect(() => {
    setReviewed(false);
  }, [current?.plan?.version, current?.id]);
  useEffect(() => {
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const endpoint = String(SERVICE_ENDPOINTS.AI_STRATEGY),
        token = authService.getAccessToken();
      try {
        const next = await researchAgent.capabilities();
        if (stopped) return;
        const nextScope = `${endpoint}:${token}:${next.node_id}:${next.owner_scope}`;
        if (scope.current && scope.current !== nextScope) {
          setCurrent(null);
          setCases([]);
          setPreview(null);
          setReviewed(false);
          requestKeys.current.clear();
          setMessage("");
        }
        scope.current = nextScope;
        setCap(next);
        setConnected(next.ready);
        if (!next.ready) return;
        const rows = await researchAgent.list(next.node_id);
        if (stopped || scope.current !== nextScope) return;
        setCases(rows);
        const id = active.current;
        if (id) {
          const detail = await researchAgent.detail(next.node_id, id);
          if (!stopped && active.current === id && scope.current === nextScope)
            setCurrent(detail);
        }
      } catch (e) {
        if (!stopped) {
          setConnected(false);
          setError(errorText(e));
        }
      } finally {
        if (!stopped) timer = setTimeout(poll, 1500);
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);
  const act = async (fn: () => Promise<unknown>) => {
    if (locked.current || !connected) return;
    locked.current = true;
    setBusy(true);
    setError("");
    const original = scope.current;
    try {
      await fn();
      if (original === scope.current && active.current && cap)
        setCurrent(await researchAgent.detail(cap.node_id, active.current));
    } catch (e) {
      if (original === scope.current) setError(errorText(e));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  const open = (id: string | null) => {
    active.current = id;
    navigate({
      pathname: location.pathname,
      search: id ? `?research=${id}` : "",
    });
    setCreating(!id);
    setCurrent(null);
  };
  const create = () =>
    act(async () => {
      const data = {
        question: question.trim(),
        subject: subject.trim(),
        material,
        model,
      };
      const row = await researchAgent.create(cap!.node_id, {
        ...data,
        key: key(data),
      });
      open(row.id);
      setCurrent(row);
    });
  const send = (interrupt: boolean) =>
    act(async () => {
      const content = message.trim();
      if (!content || !current) return;
      await researchAgent.message(
        cap!.node_id,
        current.id,
        content,
        interrupt,
        key(["message", current.id, content, interrupt]),
      );
      requestKeys.current.delete(
        JSON.stringify(["message", current.id, content, interrupt]),
      );
      setMessage("");
      followChat.current = true;
    });
  const viewFile = (path: string, download = false) =>
    act(async () => {
      const blob = await researchAgent.file(cap!.node_id, current!.id, path);
      if (download) {
        const url = URL.createObjectURL(blob),
          a = document.createElement("a");
        a.href = url;
        a.download = path.split("/").pop()!;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } else if (/\.(png|jpe?g|webp|gif)$/i.test(path))
        setPreview({ path, image: URL.createObjectURL(blob) });
      else setPreview({ path, text: (await blob.text()).slice(0, 100000) });
    });
  const upload = (file: File) =>
    act(async () => {
      if (file.size > 2_000_000) {
        setError("单个材料最多 2 MB");
        return;
      }
      const base64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result).split(",")[1]);
        r.onerror = reject;
        r.readAsDataURL(file);
      });
      const result = await researchAgent.upload(
        cap!.node_id,
        current!.id,
        file.name,
        base64,
      );
      setMessage(
        `${message}${message ? "\n" : ""}请读取材料 /workspace/${result.path}，一起讨论如何研究。`,
      );
      setTab("files");
    });
  useEffect(
    () => () => {
      if (preview?.image) URL.revokeObjectURL(preview.image);
    },
    [preview],
  );
  useEffect(() => {
    if (followChat.current && chat.current)
      chat.current.scrollTop = chat.current.scrollHeight;
  }, [current?.sequence]);
  const running =
    current &&
    ["running", "queued", "waiting_job", "retrying", "stopping"].includes(
      current.status,
    );
  const latestUser = current?.messages
    ?.filter((m) => m.role !== "assistant")
    .at(-1);
  const liveText =
    latestUser?.status === "read"
      ? current?.events
          ?.filter(
            (e) => e.kind === "text_delta" && e.message_id === latestUser.id,
          )
          .map((e) => e.text)
          .join("")
      : "";
  return (
    <section data-testid="agent-workspace" className="space-y-4 select-text">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <h1 className="text-2xl font-semibold">研究工作台</h1>
          <p className="text-muted-foreground mt-1">
            从一个问题开始，一起确定方法。代码、执行过程和成果都留在同一个课题里。
          </p>
        </div>
        <Tag color={connected ? "green" : "orange"}>
          {cap?.environment || "连接研究环境"} ·{" "}
          {connected ? "Agent 在线" : "未连接"}
        </Tag>
      </div>
      {(error || cap?.reason) && (
        <Alert
          type={error ? "error" : "warning"}
          message={error || cap?.reason}
          closable
          onClose={() => setError("")}
        />
      )}
      <div className="grid grid-cols-1 xl:grid-cols-[220px_minmax(0,1fr)] gap-4">
        <aside className={`${panel} space-y-3`}>
          <Button block icon={<Plus size={15} />} onClick={() => open(null)}>
            新建课题
          </Button>
          <p className="text-xs text-muted-foreground">
            我的研究 · {cases.length}
          </p>
          {cases.map((c) => (
            <button
              key={c.id}
              onClick={() => open(c.id)}
              className={`w-full text-left p-3 rounded-lg border ${c.id === queryId ? "border-primary bg-primary/10" : "border-transparent hover:bg-secondary"}`}
            >
              <span className="block text-sm line-clamp-2">
                {c.plan?.plan.title || c.input.question}
              </span>
              <span className="block text-xs text-muted-foreground mt-2">
                {labels[c.status] || c.status}
              </span>
            </button>
          ))}
          {!cases.length && (
            <p className="text-xs text-muted-foreground">
              课题、对话和文件会保存在当前节点，关闭页面也能继续执行。
            </p>
          )}
        </aside>
        {creating ? (
          <div className={`${panel} space-y-5`}>
            <div>
              <h2 className="text-lg font-medium">这次想弄清什么？</h2>
              <p className="text-muted-foreground text-sm mt-1">
                可以从下面选一个起点，也可以写你自己的问题。
              </p>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              <button
                className="border border-border hover:border-primary p-4 rounded-lg text-left"
                onClick={() => {
                  setQuestion(
                    "我想研究当前选股策略的表现是否稳定，以及哪些改动值得验证。请先检查可用数据，和我确定基线、验证方法、判断标准及产物，提交计划供我确认。",
                  );
                  setSubject("现有 A 股选股模型与固定历史数据");
                }}
              >
                <strong>策略链路</strong>
                <p className="text-sm text-muted-foreground mt-2">
                  从选股依据、模型到组合与交易成本，找出值得验证的改动。
                </p>
              </button>
              <button
                className="border border-border hover:border-primary p-4 rounded-lg text-left"
                onClick={() => {
                  setQuestion(
                    "我想研究一个新的因子或方法。请先检查可用数据，提出两个可证伪的研究问题，让我选择；说明能写出什么代码、怎样验证、成果放在哪里。",
                  );
                  setSubject("新因子 / 方法，可一起确定具体对象");
                }}
              >
                <strong>新因子与方法</strong>
                <p className="text-sm text-muted-foreground mt-2">
                  提出假设，写出实现，用实际数据检查，留下代码和候选因子。
                </p>
              </button>
            </div>
            <label className="block text-sm">
              要回答的问题
              <Input.TextArea
                aria-label="要回答的问题"
                className="mt-2"
                rows={4}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="例如：成交量放大后，短期反转信号会更稳定吗？我希望看到数据检验和可复用的因子代码。"
              />
            </label>
            <label className="block text-sm">
              研究对象
              <Input
                className="mt-2"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="股票池、市场、现有策略，或填写“希望一起确定”"
              />
            </label>
            <label className="block text-sm">
              已有材料或限制（可选）
              <Input.TextArea
                className="mt-2"
                rows={2}
                value={material}
                onChange={(e) => setMaterial(e.target.value)}
                placeholder="已有想法、方法描述、对比目标；创建课题后也能上传文件"
              />
            </label>
            <div className="text-xs text-muted-foreground rounded-lg bg-secondary/40 p-3">
              当前可用输入：{cap?.inventory?.snapshot_id || "尚未读取"}
              。具体日期和字段会由 Agent
              检查；对象超出数据范围时，先列出准备事项。
            </div>
            <div className="flex gap-3 items-center">
              <Select
                aria-label="研究模型"
                value={model}
                onChange={setModel}
                options={cap?.models.map((value) => ({ value, label: value }))}
                style={{ minWidth: 180 }}
              />
              <Button
                type="primary"
                disabled={!question.trim() || !connected}
                loading={busy}
                onClick={create}
              >
                建立课题并讨论
              </Button>
              <span className="text-xs text-muted-foreground">
                此时只讨论，执行需要另行确认计划
              </span>
            </div>
          </div>
        ) : current ? (
          <div className="min-w-0 space-y-3">
            <div className={`${panel} flex justify-between items-center gap-3`}>
              <div>
                <h2 className="font-semibold">
                  {current.plan?.plan.title || current.input.question}
                </h2>
                <p className="text-sm text-muted-foreground mt-1">
                  {labels[current.status] || current.status}
                  {current.approval
                    ? ` · 本窗口到 ${new Date(current.approval.deadline * 1000).toLocaleTimeString()}`
                    : ""}
                </p>
              </div>
              <Button
                danger
                icon={<Square size={14} />}
                disabled={
                  !running || current.status === "stopping" || !connected
                }
                loading={busy}
                onClick={() =>
                  act(() => researchAgent.stop(cap!.node_id, current.id))
                }
              >
                打断执行
              </Button>
            </div>
            {current.error && <Alert type="warning" message={current.error} />}
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(300px,1fr)_minmax(340px,1fr)] gap-4">
              <div className={`${panel} flex flex-col min-w-0`}>
                <h3 className="font-medium flex items-center gap-2">
                  <MessageSquare size={16} /> 与 Agent 协作
                </h3>
                <div
                  className="min-h-[240px] max-h-[50vh] overflow-y-auto space-y-4 py-4"
                  ref={chat}
                  onScroll={() => {
                    if (chat.current)
                      followChat.current =
                        chat.current.scrollHeight -
                          chat.current.scrollTop -
                          chat.current.clientHeight <
                        100;
                  }}
                  aria-live="polite"
                >
                  {current.messages?.map((m) => (
                    <div
                      key={m.id}
                      className={`p-3 rounded-lg ${m.role === "assistant" ? "bg-secondary/30" : m.role === "system" ? "border border-dashed border-border text-sm" : "bg-primary/10"}`}
                    >
                      <div className="text-xs text-muted-foreground mb-2">
                        {m.role === "assistant"
                          ? "Agent"
                          : m.role === "system"
                            ? "后台作业通知"
                            : "你"}{" "}
                        · {new Date(m.at * 1000).toLocaleTimeString()}{" "}
                        {m.role === "user" &&
                          `· ${messageState[m.status] || m.status}`}
                      </div>
                      <div className="text-sm break-words [&_p]:my-2 [&_li]:ml-4 [&_li]:list-disc [&_pre]:overflow-auto [&_pre]:p-2 [&_pre]:bg-secondary/50 [&_code]:text-xs [&_h2]:font-semibold [&_h3]:font-semibold [&_table]:text-xs [&_td]:border [&_td]:p-1 [&_th]:border [&_th]:p-1">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {m.role === "system"
                            ? "后台作业已结束，Agent 将读取实际结果。详见右侧执行记录。"
                            : m.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  ))}
                  {liveText && (
                    <div className="text-sm whitespace-pre-wrap border-l-2 border-primary pl-3">
                      {liveText}
                      <span className="animate-pulse"> ▍</span>
                    </div>
                  )}
                  {current.status === "running" && !liveText && (
                    <p className="text-sm text-muted-foreground">
                      Agent 正在处理，工具动作会显示在“过程”中。
                    </p>
                  )}
                </div>
                <div className="border-t border-border pt-3 mt-auto space-y-3">
                  <Input.TextArea
                    aria-label="发送给研究Agent的消息"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    rows={3}
                    placeholder="继续讨论、询问结果，或告诉 Agent 你想调整什么…"
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="primary"
                      disabled={!message.trim() || !connected}
                      loading={busy}
                      onClick={() => send(false)}
                    >
                      发送消息
                    </Button>
                    <Button
                      disabled={!message.trim() || !connected}
                      onClick={() => send(true)}
                    >
                      打断并发送
                    </Button>
                    <label
                      className={`inline-flex items-center gap-1 px-2 text-sm cursor-pointer ${!connected || busy ? "pointer-events-none opacity-40" : ""}`}
                    >
                      <Upload size={14} /> 材料
                      <input
                        aria-label="上传研究材料"
                        type="file"
                        className="hidden"
                        onChange={(e) => {
                          if (e.target.files?.[0])
                            void upload(e.target.files[0]);
                          e.target.value = "";
                        }}
                      />
                    </label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    普通消息在本轮结束后回复；打断并发送会先停止当前工作，再讨论你的调整。
                  </p>
                </div>
              </div>
              <div className={`${panel} min-w-0`}>
                <Tabs
                  activeKey={tab}
                  onChange={setTab}
                  items={[
                    {
                      key: "plan",
                      label: "计划与决定",
                      children: current.plan ? (
                        <div className="space-y-4 text-sm">
                          <Tag>计划 v{current.plan.version}</Tag>
                          {(current.plans?.length || 0) > 1 && (
                            <details className="rounded-lg border border-border p-3">
                              <summary className="cursor-pointer">
                                查看历史计划（{current.plans!.length - 1} 版）
                              </summary>
                              {current.plans!.slice(0, -1).map((v) => (
                                <div
                                  key={v.version}
                                  className="mt-3 space-y-2 border-t border-border pt-3"
                                >
                                  <strong>
                                    v{v.version} · {v.plan.title}
                                  </strong>
                                  <p>{v.plan.question}</p>
                                  <p>对象：{v.plan.subject}</p>
                                  <p>方法：{v.plan.method}</p>
                                  <p>产物：{v.plan.outputs.join("；")}</p>
                                  <p>判断标准：{v.plan.criteria.join("；")}</p>
                                </div>
                              ))}
                            </details>
                          )}
                          <div>
                            允许的操作：
                            {current.plan.plan.allowed_tools?.map((name) => (
                              <Tag key={name}>{tools[name] || name}</Tag>
                            )) || "需要补充工具范围"}
                          </div>
                          {[
                            ["问题", current.plan.plan.question],
                            ["对象", current.plan.plan.subject],
                            ["方法", current.plan.plan.method],
                          ].map(([name, value]) => (
                            <div key={name}>
                              <h4 className="font-semibold mb-1">{name}</h4>
                              <p className="whitespace-pre-wrap">{value}</p>
                            </div>
                          ))}
                          {(
                            [
                              ["执行步骤", current.plan.plan.steps],
                              ["预期产物", current.plan.plan.outputs],
                              ["怎样判断", current.plan.plan.criteria],
                            ] as [string, string[]][]
                          ).map(([title, values]) => (
                            <div key={title}>
                              <h4 className="font-semibold mb-1">{title}</h4>
                              <ol className="list-decimal pl-5 space-y-1">
                                {values.map((v, i) => (
                                  <li key={i}>{v}</li>
                                ))}
                              </ol>
                            </div>
                          ))}
                          {!!current.plan.plan.missing.length && (
                            <Alert
                              type="warning"
                              message="需要先准备"
                              description={current.plan.plan.missing.join("；")}
                            />
                          )}
                          <div className="border-t border-border pt-4 space-y-3">
                            <div className="flex flex-wrap gap-3 items-center">
                              <label>
                                运行上限{" "}
                                <InputNumber
                                  aria-label="运行小时上限"
                                  min={0.05}
                                  max={8}
                                  step={0.5}
                                  value={hours}
                                  onChange={(v) => setHours(v || 2)}
                                />{" "}
                                小时
                              </label>
                              <label>
                                最多作业{" "}
                                <InputNumber
                                  min={1}
                                  max={20}
                                  value={maxJobs}
                                  onChange={(v) => setMaxJobs(v || 4)}
                                />
                              </label>
                            </div>
                            <Checkbox
                              checked={reviewed}
                              onChange={(e) => setReviewed(e.target.checked)}
                            >
                              我已查看本版问题、方法和产物，同意在上述范围内执行
                            </Checkbox>
                            <Button
                              block
                              type="primary"
                              loading={busy}
                              disabled={
                                !reviewed ||
                                !connected ||
                                !!running ||
                                !!current.plan.plan.missing.length ||
                                !current.plan.plan.allowed_tools?.length
                              }
                              onClick={() =>
                                act(async () => {
                                  await researchAgent.approve(
                                    cap!.node_id,
                                    current.id,
                                    current.plan!.version,
                                    hours,
                                    maxJobs,
                                    key([
                                      "approve",
                                      current.id,
                                      current.plan!.version,
                                      hours,
                                      maxJobs,
                                    ]),
                                  );
                                  requestKeys.current.delete(
                                    JSON.stringify([
                                      "approve",
                                      current.id,
                                      current.plan!.version,
                                      hours,
                                      maxJobs,
                                    ]),
                                  );
                                  setReviewed(false);
                                })
                              }
                            >
                              确认计划并执行
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <Empty description="先一起确定问题和方法，Agent 提交计划后会显示在这里。你可以随时发消息修改方向。" />
                      ),
                    },
                    {
                      key: "process",
                      label: "过程",
                      children: (
                        <div className="space-y-4 max-h-[760px] overflow-auto">
                          {!!current.todos?.length && (
                            <div className="space-y-2">
                              {current.todos.map((todo, i) => (
                                <div key={i} className="flex gap-2 text-sm">
                                  <Check
                                    size={16}
                                    className={
                                      todo.status === "completed"
                                        ? "text-green-500"
                                        : "text-muted-foreground opacity-30"
                                    }
                                  />
                                  <span>{todo.content}</span>
                                  <Tag>
                                    {todo.status === "completed"
                                      ? "完成"
                                      : todo.status === "in_progress"
                                        ? "进行中"
                                        : "待处理"}
                                  </Tag>
                                </div>
                              ))}
                            </div>
                          )}
                          {Object.values(current.jobs || {}).map((j) => (
                            <details
                              key={j.id}
                              className="border border-border rounded-lg p-3"
                              open={j.status === "running"}
                            >
                              <summary className="cursor-pointer text-sm">
                                {j.purpose} · {labels[j.status] || j.status}
                              </summary>
                              {j.command && (
                                <pre className="text-xs whitespace-pre-wrap mt-2">
                                  {j.command}
                                </pre>
                              )}
                              {(j.log || j.error) && (
                                <pre className="text-xs whitespace-pre-wrap bg-secondary/40 p-2 mt-2 max-h-56 overflow-auto">
                                  {j.log || j.error}
                                </pre>
                              )}
                            </details>
                          ))}
                          {current.events
                            ?.filter(
                              (e) => e.kind === "tool_start" || e.message,
                            )
                            .map((e) => {
                              const done = current.events.find(
                                (d) =>
                                  d.kind === "tool_end" &&
                                  d.call_id === e.call_id,
                              );
                              return (
                                <details
                                  key={e.seq}
                                  className="border-b border-border pb-2"
                                >
                                  <summary className="text-sm cursor-pointer">
                                    <span className="text-muted-foreground text-xs mr-2">
                                      {new Date(
                                        e.at * 1000,
                                      ).toLocaleTimeString()}
                                    </span>
                                    {e.name
                                      ? `${tools[e.name] || e.name} · ${done ? (done.status === "error" ? "未完成" : "已返回") : running ? "处理中" : "已中断 / 未返回"}`
                                      : e.message}
                                  </summary>
                                  {e.arguments && (
                                    <pre className="text-xs whitespace-pre-wrap bg-secondary/30 p-2 my-2">
                                      {JSON.stringify(e.arguments, null, 2)}
                                    </pre>
                                  )}
                                  {done?.output && (
                                    <pre className="text-xs whitespace-pre-wrap max-h-60 overflow-auto">
                                      {done.output}
                                    </pre>
                                  )}
                                </details>
                              );
                            })}
                          {!current.events?.length && (
                            <Empty description="工具被实际调用后显示记录" />
                          )}
                          <p className="text-xs text-muted-foreground">
                            模型已报告用量：
                            {(
                              (current.usage?.input_tokens || 0) +
                              (current.usage?.output_tokens || 0)
                            ).toLocaleString()}{" "}
                            tokens；中断响应可能缺少用量。
                          </p>
                        </div>
                      ),
                    },
                    {
                      key: "files",
                      label: `文件 ${current.files?.length || 0}`,
                      children: (
                        <div className="space-y-3">
                          {current.files?.map((f) => (
                            <div
                              key={f.path}
                              className="flex items-center gap-2 text-sm"
                            >
                              <FileText size={15} />
                              <button
                                onClick={() => viewFile(f.path)}
                                className="text-primary text-left break-all flex-1"
                              >
                                {f.path}
                              </button>
                              <span className="text-xs text-muted-foreground">
                                {Math.ceil(f.size / 1024)} KB
                              </span>
                              <Button
                                size="small"
                                onClick={() => viewFile(f.path, true)}
                              >
                                下载
                              </Button>
                            </div>
                          ))}
                          {!current.files?.length && (
                            <Empty description="上传的材料、代码和计算输出会显示在这里" />
                          )}
                          {preview && (
                            <div>
                              <div className="flex justify-between my-2 text-sm">
                                <span>{preview.path}</span>
                                <button onClick={() => setPreview(null)}>
                                  关闭
                                </button>
                              </div>
                              <>
                                {preview.image ? (
                                  <img
                                    src={preview.image}
                                    alt={preview.path}
                                    className="max-w-full max-h-[520px] object-contain"
                                  />
                                ) : (
                                  <pre className="bg-secondary/30 rounded p-3 text-xs whitespace-pre-wrap max-h-[520px] overflow-auto">
                                    {preview.text}
                                  </pre>
                                )}
                              </>
                            </div>
                          )}
                        </div>
                      ),
                    },
                    {
                      key: "outcomes",
                      label: `成果 ${current.outcomes?.length || 0}`,
                      children: (
                        <div className="space-y-4">
                          {current.outcomes?.map((o) => (
                            <div
                              key={o.id}
                              className="rounded-lg border border-border p-3 space-y-2"
                            >
                              <h4 className="font-medium">{o.name}</h4>
                              <Tag>{o.status}</Tag>
                              {o.metrics && (
                                <div className="text-sm">
                                  区间收益{" "}
                                  {(o.metrics.total_return * 100).toFixed(2)}% ·
                                  最大回撤{" "}
                                  {(o.metrics.max_drawdown * 100).toFixed(2)}%
                                </div>
                              )}
                              {o.curve && (
                                <ReactECharts
                                  style={{ height: 190 }}
                                  option={{
                                    grid: {
                                      left: 55,
                                      top: 15,
                                      right: 10,
                                      bottom: 30,
                                    },
                                    tooltip: { trigger: "axis" },
                                    xAxis: {
                                      type: "category",
                                      data: o.curve.map((p) => p.date),
                                    },
                                    yAxis: { type: "value", scale: true },
                                    series: [
                                      {
                                        type: "line",
                                        showSymbol: false,
                                        data: o.curve.map((p) => p.value),
                                      },
                                    ],
                                  }}
                                />
                              )}
                              <a
                                className="text-primary text-sm inline-flex items-center gap-1"
                                href={o.href}
                              >
                                在
                                {o.kind === "factor"
                                  ? "因子库"
                                  : o.kind === "strategy"
                                    ? "AI-IDE"
                                    : "回测中心"}
                                打开 <ArrowUpRight size={14} />
                              </a>
                              {o.path && (
                                <Button
                                  size="small"
                                  onClick={() => viewFile(o.path)}
                                >
                                  查看代码
                                </Button>
                              )}
                            </div>
                          ))}
                          {!current.outcomes?.length && (
                            <Empty description="尚未登记成果。完成的因子候选与回测结果会显示实际平台入口。" />
                          )}
                        </div>
                      ),
                    },
                  ]}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className={panel}>
            <Empty
              description={connected ? "正在加载课题…" : "等待连接研究服务"}
            />
          </div>
        )}
      </div>
    </section>
  );
}
