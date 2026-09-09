"""Node-bound model and Docker adapters. Credentials never enter research state."""
from __future__ import annotations

import json
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from backend.shared.docker_host_paths import host_path

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import run_frozen_research as frozen
from glm_research_runner import retry_delay
from verify_agent_research import reconcile

ROOT = Path("/data/research")
CODE_FILES = ("frozen_research_worker.py", "research_expression.py")


def settings():
    role = os.getenv("QM_NODE_ROLE")
    if role not in ("authority", "sandbox"):
        raise ValueError("研究需要已确认的数据角色：云端或本地沙盒")
    data = frozen.read(ROOT / "settings.json")
    if data["role"] != role or data["host_data"] != host_path("/data", runtime_only=True):
        raise ValueError("研究配置与实际运行节点不匹配")
    source = Path(data["source"])
    if not source.resolve().is_relative_to((ROOT / "inputs").resolve()):
        raise ValueError("研究快照不在本节点的隔离输入目录")
    if frozen.sha256(source / "manifest.json") != data["manifest_sha256"]:
        raise ValueError("研究输入清单发生变化")
    return data


def credentials():
    path = Path(os.getenv("RESEARCH_LLM_CONFIG_FILE", "/run/secrets/research-llm.json"))
    if path.stat().st_mode & 0o077:
        raise ValueError("研究模型凭据权限必须为 0600")
    cfg = frozen.read(path)
    if not cfg.get("api_key") or not cfg.get("base_url", "").startswith("https://"):
        raise ValueError("研究模型未配置 HTTPS 服务与凭据")
    return cfg


def models():
    cfg = credentials()
    return [name.split("[")[0] for name in cfg.get("models", cfg.get("requested_models", ["glm-5.3-flash", "glm-5.3"]))]


def code_hashes():
    return {name: frozen.sha256(SCRIPTS / name) for name in CODE_FILES}


def case_directory(case_id):
    if len(case_id) != 32 or any(c not in "0123456789abcdef" for c in case_id):
        raise ValueError("Invalid research case ID")
    path = ROOT / "cases" / case_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def freeze_code(directory, contract):
    target = directory / "code"
    target.mkdir(exist_ok=True)
    for name, expected in contract["code_hashes"].items():
        dest = target / name
        if not dest.exists():
            if frozen.sha256(SCRIPTS / name) != expected:
                raise ValueError("执行代码已更新，请重新创建研究合同")
            dest.write_bytes((SCRIPTS / name).read_bytes())
        if frozen.sha256(dest) != expected:
            raise ValueError("本课题的冻结执行代码发生变化")


@contextmanager
def docker_client():
    # The backend image already ships the Docker SDK used by training launchers.
    import docker
    client = None
    try:
        client = docker.DockerClient(base_url="unix:///var/run/docker.sock", timeout=30)
        yield client
    except docker.errors.NotFound:
        raise
    except docker.errors.DockerException:
        raise RuntimeError("Docker 服务暂时不可达，保留原容器标识等待恢复") from None
    finally:
        if client:
            client.close()


def inspect(name):
    import docker
    try:
        with docker_client() as client:
            return client.api.inspect_container(name)
    except docker.errors.NotFound:
        return None
    except docker.errors.DockerException:
        raise RuntimeError("暂时无法查询研究容器，保留原任务等待恢复") from None


def check_container(info, experiment, directory, node):
    labels = info["Config"].get("Labels") or {}
    if labels.get("quantmind.research.node") != node or labels.get("quantmind.research.id") != experiment["id"]:
        raise ValueError("容器所有权不匹配")
    if not any(m["Destination"] == "/output" and m["Source"] == host_path(str(directory), runtime_only=True) for m in info["Mounts"]):
        raise ValueError("容器输出挂载不匹配")
    if info["HostConfig"]["NetworkMode"] != "none":
        raise ValueError("研究容器没有网络隔离")


def launch(case_dir, experiment, config, contract, deadline):
    with (ROOT / "launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _launch(case_dir, experiment, config, contract, deadline)


def _launch(case_dir, experiment, config, contract, deadline):
    """Stable Docker name plus pre-recorded intent make retries inspect, not rerun."""
    directory = case_dir / "experiments" / experiment["id"]
    directory.mkdir(parents=True, exist_ok=True)
    info = inspect(experiment["container_name"])
    if info:
        check_container(info, experiment, directory, contract["node_id"])
        if info["State"]["Status"] == "created":
            with docker_client() as client:
                client.api.start(info["Id"])
        return info["Id"]
    if (directory / "launch-intent.json").exists():
        raise ValueError("容器提交结果不明且未找到原容器，需查看证据后继续")
    with docker_client() as client:
        if client.containers.list(filters={"label": f"quantmind.research.node={contract['node_id']}"}):
            return None  # One heavy experiment per node; other cases remain visible.
    remaining = int(deadline-time.time()-30)
    if remaining < 90:
        return None
    freeze_code(case_dir, contract)
    source = Path(contract["source"])
    frozen.verify(source)
    remaining = int(deadline-time.time()-30)
    if remaining < 30:
        return None
    frozen.write(directory / "config.json", config)
    frozen.write(directory / "proposal.json", experiment["proposal"])
    host_dir = Path(host_path(str(directory), runtime_only=True))
    watchdog = ("import os,sys,time; remaining=int(float(sys.argv[1])-time.time()-10); "
                "sys.exit(124) if remaining<1 else os.execvp('timeout', "
                "['timeout','--signal=TERM','--kill-after=10',str(remaining),"
                "'python','/research-code/frozen_research_worker.py'])")
    spec = {"image": contract["image"]["Id"], "name": experiment["container_name"],
        "platform": contract["image"]["Os"]+"/"+contract["image"]["Architecture"],
        "network_mode": "none", "read_only": True, "nano_cpus": 2_000_000_000,
        "healthcheck": {"test": ["NONE"]},
        "mem_limit": "8g", "tmpfs": {"/tmp": "rw,size=1g"}, "working_dir": "/output",
        "labels": {"quantmind.research.node": contract["node_id"], "quantmind.research.id": experiment["id"]},
        "volumes": {
            host_path(str(source / "snapshot"), runtime_only=True): {"bind": "/frozen", "mode": "ro"},
            str(host_dir): {"bind": "/output", "mode": "rw"},
            str(host_dir / "config.json"): {"bind": "/frozen/config.json", "mode": "ro"},
            host_path(str(case_dir / "code"), runtime_only=True): {"bind": "/research-code", "mode": "ro"}},
        "environment": {"PYTHONPATH": "/research-code:/frozen/code:/frozen/code/docker/training:/frozen/code/scripts",
            "PYTHONDONTWRITEBYTECODE": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True", "HOME": "/tmp",
            "OMP_NUM_THREADS": "4", "PYTHONHASHSEED": "42", "QM_QUANTDB_DATA_DIR": "/frozen/quantdb",
            "QUANTDB_DATA_DIR": "/frozen/quantdb", "QLIB_PROVIDER_URI": "/frozen/qlib"},
        "entrypoint": "python", "command": ["-c", watchdog, str(deadline)]}
    frozen.write(directory / "launch-intent.json", {"spec": spec, "deadline_epoch": deadline, "created_epoch": time.time()})
    import docker
    try:
        with docker_client() as client:
            container = client.containers.create(**spec)
            container.start()
            return container.id
    except docker.errors.DockerException:
        raise RuntimeError("容器提交响应不明，下次推进先核对相同容器名") from None


def observe(case_dir, experiment, contract, stop=False):
    directory = case_dir / "experiments" / experiment["id"]
    info = inspect(experiment["container_name"])
    if info is None:
        raise ValueError("已提交的容器不存在，不能证明实验已停止或完成")
    check_container(info, experiment, directory, contract["node_id"])
    if stop and info["State"]["Running"]:
        with docker_client() as client:
            client.api.stop(experiment["container_name"], timeout=10)
        info = inspect(experiment["container_name"])
    if info["State"]["Running"]:
        return None
    if not (directory / "execution.log").exists():
        with docker_client() as client:
            log = client.api.logs(info["Id"], stdout=True, stderr=True, tail=2000)
        (directory / "execution.log").write_bytes(log)
    experiment["container_id"] = info["Id"]
    experiment["exit_code"] = info["State"]["ExitCode"]
    experiment["finished_at"] = info["State"]["FinishedAt"]
    if stop:
        experiment["status"] = "cancelled"
        return {"stopped": True}
    if info["State"]["ExitCode"] != 0:
        experiment["status"] = "failed"
        experiment["result"] = {"summary": {"comparison": {"model": {}}},
            "failure": "计算进程退出失败，查看 execution.log",
            "artifacts": {name: frozen.sha256(directory/name) for name in
                          ("execution.log", "config.json", "proposal.json") if (directory/name).exists()}}
        raise ValueError("研究计算退出失败；日志与产物已保留")
    summary = frozen.read(directory / "summary.json")
    if not summary.get("checks_passed"):
        raise ValueError("研究计算未通过内部核验")
    cfg = frozen.read(directory / "config.json")
    verification = {name: reconcile(directory, name, cfg["portfolio"]["initial_capital"], metrics)
                    for name, metrics in summary["comparison"].items()}
    frozen.verify(Path(contract["source"]))
    artifacts = {p.name: frozen.sha256(p) for p in directory.iterdir() if p.is_file() and p.name != "verification.json"}
    result = {"summary": summary, "verification": verification,
              "model_metrics": frozen.read(directory / "model-metadata.json"), "artifacts": artifacts}
    if (directory / "factor-analysis.json").exists():
        result["factor_analysis"] = frozen.read(directory / "factor-analysis.json")
    frozen.write(directory / "verification.json", result)
    experiment["status"] = "completed"
    return result


class InvalidDecision(ValueError):
    """An observed response can be repaired without repeating an uncertain request."""


def model_decision(folder, contract, name, properties, prompt, deadline):
    """One network attempt per tick; 429/503 retries do not block other research."""
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"model": contract["model"], "reasoning_effort": contract.get("reasoning_effort", "high"), "max_tokens": contract.get("max_tokens", 6000),
        "messages": [{"role": "system", "content": "你是受限量化研究助手。仅调用指定函数一次；所有结论须基于给定实验。区分假设、已验证证据和开发区间表现。用中文解释，不宣称独立验证或真实盈利。"},
                     {"role": "user", "content": prompt}],
        "tools": [{"type": "function", "function": {"name": name, "parameters": {
            "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}}],
        "tool_choice": "auto"}
    if (folder / "request.json").exists() and frozen.read(folder / "request.json") != payload:
        raise ValueError("已有模型请求内容发生变化，拒绝重复调用")
    frozen.write(folder / "request.json", payload)
    response_file = folder / "response.json"
    if response_file.exists():
        response = frozen.read(response_file)
    else:
        attempts = sorted(folder.glob("attempt-*.json"))
        if attempts:
            previous = frozen.read(attempts[-1])
            if previous["status"] not in ("retryable", "uncertain", "intent"):
                raise ValueError("上次模型调用被服务拒绝，保留调用证据等待检查")
            # Model calls only propose text: replay cannot submit an experiment.
            # Keep unknown usage and wait out a crashed request before another call.
            retry_at = previous.get("retry_at", attempts[-1].stat().st_mtime +
                                    (210 if previous["status"] == "intent" else retry_delay(len(attempts), None)))
            if time.time() < retry_at:
                return None
        if deadline-time.time() < 60:
            return None
        credentials_config = credentials()
        if credentials_config["base_url"] != contract["model_base_url"]:
            raise ValueError("模型服务配置已改变，不能继续原调用合同")
        attempt_file = folder / f"attempt-{len(attempts)+1:04d}.json"
        started = time.time()
        frozen.write(attempt_file, {"status": "intent", "started_epoch": started, "usage": None})
        request = urllib.request.Request(credentials_config["base_url"].rstrip("/")+"/chat/completions",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
            "Authorization": "Bearer "+credentials_config["api_key"]})
        try:
            with urllib.request.urlopen(request, timeout=min(180, deadline-time.time()-30)) as stream:
                response = json.load(stream)
            frozen.write(response_file, response)
            frozen.write(attempt_file, {"status": "completed", "usage": response.get("usage"),
                                       "seconds": time.time()-started})
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code <= 599:
                delay = retry_delay(len(attempts)+1, exc.headers.get("Retry-After"))
                frozen.write(attempt_file, {"status": "retryable", "http_status": exc.code,
                    "retry_at": time.time()+delay, "usage": None})
                return None
            frozen.write(attempt_file, {"status": "failed", "http_status": exc.code, "usage": None})
            raise ValueError(f"模型服务 HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            frozen.write(attempt_file, {"status": "uncertain", "usage": None,
                "retry_at": time.time()+retry_delay(len(attempts)+1, None)})
            return None
    try:
        calls = response["choices"][0]["message"].get("tool_calls") or []
        if len(calls) != 1 or calls[0]["function"]["name"] != name:
            raise ValueError("模型没有返回单个允许的工具调用")
        args = json.loads(calls[0]["function"]["arguments"])
        if not isinstance(args, dict) or set(args) != set(properties):
            raise ValueError("模型工具参数不符合研究合同")
        frozen.write(folder / "tool-call.json", {"id": calls[0]["id"], "name": name, "arguments": args})
        return args
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise InvalidDecision("模型响应格式需要修正：" + str(exc)) from None
