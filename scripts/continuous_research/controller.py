#!/usr/bin/env python3
"""Local unattended research coordinator; Pi credentials never enter model context.

Usage: python scripts/continuous_research/controller.py --config <private.json>
Launchd supervises this process; PG holds tasks, leases, actions and receipts.
"""

from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.services.research_agent.glm_quota import (
    fetch_quota,
    failure_kind,
    quota_decision,
)

SYSTEM = """你是 QuantMind 的量化研究员。任务是提出可证伪假设，通过统一公共回测检验，保留失败结果。
你没有 shell、文件、网页或交易工具。只输出一个 JSON 动作，不要 Markdown、前后解释。
根据 task.kind 选择研究入口：research 为 ETF 组合研究；stock_factor 为 A股因子研究。
A股因子必须使用 {"action":"stock_factor","name":"名称","hypothesis":"可证伪假设与判别条件","expression":"表达式"}。
股票任务第一项 expression="" 跑已冻结 LightGBM+TopkDropout 基线；随后单独增加一个可解释表达式，例如 rank(mom_ret_20d)-rank(vol_std_20)。
可用列/函数/训练窗口以 stock_inventory 为准；表达式不能读未来或输入外字段。不要在股票任务提交 ETF experiment 动作。
基线是100只主板股票、1000万实验资金的模型诊断，不等于用户2–3万元策略。测试段是已暴露开发比较段，并非保留验证集。
因子评估同时看 IC/RankIC、覆盖率、与原特征的冗余、组合效果及成本；负结果有价值，不能只优化收益。
"report" 对两类任务通用，后续 topic 可选 stock_signal、stock_risk、trend、momentum、risk。

可选动作：
1. {"action":"experiment","name":"简短名称","hypothesis":"运行前假设与判别条件",
"code":"def on_signal(ctx): ...", "parameters":{...},"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}
2. {"action":"report","text":"中文研究报告：问题、全部实验编号、同条件对照、证据、局限、下一步",
"followups":[{"topic":"stock_signal 或 stock_risk 或 trend 或 momentum 或 risk","question":"一个有证据支持的新问题","reason":"具体已有结果或尚未检验的机制"}]}
parameters 必须显式带 symbols（非空字符串数组），ctx.symbols 来自该字段，不能只依赖 contract.symbols。
例如格式（仅示例；资产由课题选择，并不默认沿用 A）：
{"symbols":["510300.SH","510500.SH"],"target_weights":{"510300.SH":0.5,"510500.SH":0.5},"frequency":"monthly","lookback":1}
趋势模板 rule="sma", monthly_lookback=10, signal_on_month_end=true；动量模板 rule="momentum", monthly_lookback=13, top_n=2；
波动模板 rule="vol_target", lookback=61, annualization=252, volatility_target=0.12。这些仅说明字段，具体机制须预注册并论证。
使用给定 templates 及上下文接口，允许创建新逻辑，但禁止自己实现撮合账本。
on_signal 返回 targets(权重字典或 null)、reason、可选 state。上下文含 date,month,is_entry,is_month_end,
symbols,parameters,history,monthly_prices,snapshot,state。仅已暴露的历史；无 import/IO/while。
每任务最多6实验。第一项必须是与候选相同资产、时期、费用的简单对照，之后只改预注册关键机制。
不要无意义地扫参数。所有实验都是开发集探索，不能称样本外验证或建议实盘。
任务不修改已有 A/B 或账户，固定风险/费用/数据边界由服务器控制。不得请求保留验证区间。
时间窗口须保证信号所需预热历史和各标的数据可用；如果失败则说明并修正，不伪造收益。
SIGXCPU、timeout、资源超限与数据/代码错误属于工程无效实验，不能据此否定研究假设。先登记受阻原因，再在同条件对照下修正实现或缩小开发窗口。
读取 results 中全部已完成和失败结果再决定下一步。先完成足够对照再交报告；报告注明未经独立复核。
后续问题仅在确有具体证据缺口时提出0至3个，避免与 prior_questions 重复；不为耗 token 制造问题。
默认只提出0至1个最有决策价值的后续问题。不要反复微调同一家族的阈值或权重；深链优先总结失效机制、核对结果与跨时期稳健性。
已暴露开发数据上的阈值通过、IC符号或收益提高只能是探索证据，不能称为可部署、显著或一般规律；未做统计检验时明确说未检验。事后日期掩码只可标为诊断，不能进入候选。
"""


class APIError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, str(detail)[:2000]


class Client:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.cfg = json.loads(path.read_text())
        from urllib.parse import urlsplit

        for key in ("engine_url", "auth_url"):
            url = urlsplit(self.cfg[key])
            if (
                url.scheme != "http"
                or url.hostname != "127.0.0.1"
                or not url.port
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("local sandbox endpoint required")
        self.worker = uuid.uuid4().hex
        self.program = self.cfg["program_id"]

    def save(self):
        temp = self.path.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.cfg, f)
        os.replace(temp, self.path)

    def call(self, op, task=None, data=None):
        body = {"op": op, "worker": self.worker, "data": data or {}}
        if task:
            body.update(task_id=task["id"], lease=task["lease"])
        for attempt in range(2):
            session = requests.Session()
            session.trust_env = False
            r = session.post(
                self.cfg["engine_url"]
                + f"/api/v1/continuous-research/{self.program}/command",
                headers={"Authorization": "Bearer " + self.cfg["access_token"]},
                json=body,
                timeout=(5, 90),
            )
            if r.status_code == 401 and attempt == 0:
                with self.lock:
                    rr = session.post(
                        self.cfg["auth_url"] + "/api/v1/auth/refresh",
                        json={"refresh_token": self.cfg["refresh_token"]},
                        timeout=20,
                    )
                    if rr.status_code != 200:
                        raise APIError(401, "platform_auth_refresh_failed")
                    tokens = rr.json().get("data", rr.json())
                    self.cfg.update(
                        access_token=tokens["access_token"],
                        refresh_token=tokens["refresh_token"],
                    )
                    self.save()
                continue
            if r.status_code >= 400:
                try:
                    detail = r.json().get("detail", "api_error")
                except Exception:
                    detail = "api_error"
                raise APIError(r.status_code, detail)
            return r.json()
        raise APIError(401, "platform_auth_failed")


class Controller:
    def __init__(self, client):
        self.api = client
        self.stop = threading.Event()
        self.children = {}
        self.child_lock = threading.Lock()
        self.home = client.path.parent / "pi-isolated"
        self.home.mkdir(mode=0o700, exist_ok=True)
        # Copy provider routing/model metadata, NEVER the credential or other
        # personal providers, extensions, prompts, skills or context files.
        src = json.loads((Path.home() / ".pi/agent/models.json").read_text())[
            "providers"
        ]["glm"]
        provider = {k: v for k, v in src.items() if k in ("baseUrl", "api", "models")}
        if provider["baseUrl"] != "https://open.bigmodel.cn/api/coding/paas/v4":
            raise ValueError("unexpected_glm_endpoint")
        provider["models"] = [
            {
                k: v
                for k, v in m.items()
                if k
                in (
                    "id",
                    "name",
                    "api",
                    "reasoning",
                    "input",
                    "cost",
                    "contextWindow",
                    "maxTokens",
                    "compat",
                )
            }
            for m in provider["models"]
        ]
        provider["apiKey"] = "${QM_GLM_KEY}"
        (self.home / "models.json").write_text(
            json.dumps({"providers": {"glm": provider}})
        )
        (self.home / "settings.json").write_text(
            json.dumps(
                {
                    "retry": {"enabled": False},
                    "quietStartup": True,
                    "defaultThinkingLevel": "max",
                }
            )
        )
        self.pi = client.cfg.get("pi", "/opt/homebrew/bin/pi")

    def credential(self):
        r = subprocess.run(
            [self.pi, "auth", "print-api-key", "--provider", "glm"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode or not r.stdout.strip():
            raise RuntimeError("glm_credential_unavailable")
        return r.stdout.strip()

    def model(self, context, task):
        env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "LANG", "TMPDIR")
        }
        env.update(PI_CODING_AGENT_DIR=str(self.home), QM_GLM_KEY=self.credential())
        argv = [
            self.pi,
            "--mode",
            "json",
            "--print",
            "--provider",
            "glm",
            "--model",
            "glm-5.3",
            "--thinking",
            "max",
            "--no-session",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--no-themes",
            "--no-approve",
            "--offline",
            "--system-prompt",
            SYSTEM,
        ]
        p = subprocess.Popen(
            argv,
            cwd=self.home,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with self.child_lock:
            self.children[task["id"]] = p
        try:
            # communicate drains continuously. No raw stream is written to disk
            # or platform; only final text and explicit usage are consumed.
            output, _ = p.communicate(
                json.dumps(context, ensure_ascii=False).encode(), timeout=900
            )
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            p.communicate()
            return None, "retrying", {"unknown_calls": 1}
        finally:
            with self.child_lock:
                self.children.pop(task["id"], None)
        messages = []
        for line in output.split(b"\n"):
            try:
                item = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if (
                item.get("type") == "message_end"
                and item.get("message", {}).get("role") == "assistant"
            ):
                messages.append(item["message"])
        usage = {"input": 0, "output": 0, "unknown_calls": 0}
        for m in messages:
            u = m.get("usage")
            if u:
                usage["input"] += (
                    int(u.get("input", 0))
                    + int(u.get("cacheRead", 0))
                    + int(u.get("cacheWrite", 0))
                )
                usage["output"] += int(u.get("output", 0))
            else:
                usage["unknown_calls"] += 1
        if not messages:
            return None, "retrying", {"unknown_calls": 1}
        m = messages[-1]
        if m.get("stopReason") in ("error", "aborted") or m.get("errorMessage"):
            return None, failure_kind(m.get("errorMessage", "stream_read_error")), usage
        content = "".join(
            x.get("text", "") for x in m.get("content", []) if x.get("type") == "text"
        ).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            action = json.loads(content)
            if not isinstance(action, dict):
                raise ValueError()
            return action, None, usage
        except ValueError:
            return None, "invalid_action_json", usage

    def work(self, task):
        outcome = "blocked"
        reason = "step_limit_or_invalid_action"
        try:
            malformed = 0
            for _ in range(40):
                if self.stop.is_set():
                    outcome = "retrying"
                    break
                ctx = self.api.call("context", task)
                if ctx["task"]["reports"]:
                    outcome = "done"
                    break
                if any(
                    x["status"] in ("pending", "running")
                    for x in ctx["results"].values()
                ):
                    # Release this model slot while the independent public
                    # worker computes; other ready questions can use it.
                    outcome = "waiting_compute"
                    reason = "等待公共计算结果，已让出模型执行槽"
                    break
                if ctx["task"]["kind"] == "stock_factor" and any(
                    x["status"] == "failed" for x in ctx["results"].values()
                ):
                    outcome = "blocked"
                    reason = "股票计算失败，保留工程证据，需修复后重新冻结；不能据此判定因子无效"
                    break
                action = ctx["task"].get("pending_action")
                if not action and ctx["quota_state"] != "available":
                    outcome = ctx["quota_state"]
                    break
                if not action:
                    self.api.call(
                        "usage", task, {"step": "GLM 分析假设、代码与实验结果"}
                    )
                    action, error, usage = self.model(ctx, task)
                    usage["calls"] = 1
                    self.api.call("usage", task, usage)
                    if error:
                        if error == "invalid_action_json" and malformed < 2:
                            malformed += 1
                            self.api.call(
                                "feedback",
                                task,
                                {
                                    "message": "上次输出不是单个合法 JSON，请严格使用动作合同。"
                                },
                            )
                            continue
                        reason = error
                        outcome = (
                            error
                            if error
                            in (
                                "waiting_quota",
                                "retrying",
                                "auth_error",
                                "quota_unknown",
                            )
                            else "blocked"
                        )
                        break
                    self.api.call("stage", task, {"action": action})
                try:
                    self.api.call("action", task, {"action": action})
                except APIError as e:
                    if e.status in (400, 409, 422) and malformed < 3:
                        malformed += 1
                        self.api.call("feedback", task, {"message": e.detail})
                        continue
                    raise
                if action.get("action") == "report":
                    outcome = "done"
                    break
        except APIError as e:
            reason = "platform_http_" + str(e.status) + ": " + e.detail[:300]
            outcome = "retrying" if e.status >= 500 else "blocked"
            if "lease" in e.detail or "controller" in e.detail:
                return
        except (requests.RequestException, OSError, RuntimeError) as exc:
            reason = type(exc).__name__
            outcome = "retrying"
        finally:
            try:
                self.api.call(
                    "settle",
                    task,
                    {"outcome": outcome, "reason": reason if outcome != "done" else ""},
                )
            except Exception:
                pass  # expired lease is recovered by the next coordinator

    def kill_children(self, allowed=None):
        with self.child_lock:
            for ident, p in self.children.items():
                if allowed is None or ident not in allowed:
                    try:
                        os.killpg(p.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass

    def run(self):
        futures = {}
        quota = {"status": "unknown", "remaining_percent": None}
        check_at = 0
        with ThreadPoolExecutor(max_workers=3) as pool:
            while not self.stop.is_set():
                now = time.time()
                try:
                    if now >= check_at:
                        quota = fetch_quota(self.credential())
                        check_at = now + 60
                    state = self.api.call(
                        "pulse",
                        data={
                            "quota": quota,
                            "runtime": {
                                "provider": "glm",
                                "model": "glm-5.3",
                                "thinking": "max",
                            },
                        },
                    )
                    active = {
                        k for k, t in state["tasks"].items() if t["status"] == "running"
                    }
                    self.kill_children(
                        active if state["desired"] == "running" else set()
                    )
                    futures = {k: f for k, f in futures.items() if not f.done()}
                    for _ in range(state["contract"]["concurrency"] - len(futures)):
                        reply = self.api.call("claim")
                        task = reply.get("task")
                        if not task:
                            break
                        futures[task["id"]] = pool.submit(self.work, task)
                except Exception as exc:
                    # Deliberately no exception string / response / command argv.
                    print(
                        json.dumps(
                            {
                                "at": time.time(),
                                "event": "controller_error",
                                "type": type(exc).__name__,
                            }
                        ),
                        flush=True,
                    )
                self.stop.wait(10)
            self.kill_children()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    args = p.parse_args()
    if args.config.stat().st_mode & 0o077:
        raise SystemExit("private config must be mode 0600")
    import fcntl

    with open(args.config.with_suffix(".lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("coordinator already running") from None
        c = Controller(Client(args.config))
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: c.stop.set())
        c.run()


if __name__ == "__main__":
    main()
