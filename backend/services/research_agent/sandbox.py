"""Deep Agents' standard sandbox adapter backed by bounded Docker jobs."""

import asyncio
import base64
import hashlib
import json
import os
import shlex
import stat
import time
from contextlib import closing
from pathlib import PurePosixPath
from uuid import uuid4

import docker
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)


def read_file(root, relative, limit=1_000_000):
    """Open every component without following model-created symlinks (including races)."""
    parts = PurePosixPath(relative.removeprefix("/workspace/")).parts
    if not parts or any(p in ("..", "/", ".") for p in parts):
        raise ValueError("请选择工作区内的文件")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("只能读取限制大小内的普通文件")
        with os.fdopen(os.dup(fd), "rb") as stream:
            return stream.read(limit + 1)
    finally:
        os.close(fd)


def files(root):
    result = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (root / directory / d).is_symlink()]
        for name in names:
            path = root / directory / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                result.append(
                    {
                        "path": str(path.relative_to(root)),
                        "size": info.st_size,
                        "modified_at": info.st_mtime,
                    }
                )
            if len(result) >= 500:
                return result
    return sorted(result, key=lambda r: r["path"])


class Sandbox(BaseSandbox):
    def __init__(self, settings, ident):
        self.settings, self.ident = settings, ident
        self.root = settings.workspace(ident)
        self.active = set()

    @property
    def id(self):
        return "qm-agent-" + self.ident

    def client(self):
        return closing(docker.from_env(timeout=15))

    def inspect(self, name):
        with self.client() as client:
            try:
                info = client.api.inspect_container(name)
            except docker.errors.NotFound:
                return None
        labels = info["Config"].get("Labels", {})
        if (
            labels.get("quantmind.agent.case") != self.ident
            or labels.get("quantmind.agent.node") != self.settings.node
        ):
            raise ValueError("计算容器归属不匹配")
        return info

    def launch(self, name, command, deadline):
        existing = self.inspect(name)
        if existing:
            return existing["Id"]
        if deadline <= time.time():
            raise ValueError("执行窗口已结束")
        # The absolute deadline survives worker exit/restart. No host credentials/network.
        watchdog = "import os,sys,time; n=int(float(sys.argv[1])-time.time()); sys.exit(124) if n<1 else os.execvp('timeout',['timeout','--signal=TERM','--kill-after=5',str(n),'sh','-c',sys.argv[2]])"
        cfg = self.settings.cfg
        with self.client() as client:
            container = client.containers.create(
                image=cfg["image"]["Id"],
                name=name,
                platform=cfg["image"]["Os"] + "/" + cfg["image"]["Architecture"],
                entrypoint="python",
                command=["-c", watchdog, str(deadline), command],
                user="65534:65534",
                network_mode="none",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                mem_limit="4g",
                nano_cpus=1_000_000_000,
                pids_limit=64,
                tmpfs={"/tmp": "rw,nosuid,size=256m"},
                working_dir="/workspace",
                healthcheck={"test": ["NONE"]},
                labels={
                    "quantmind.agent.case": self.ident,
                    "quantmind.agent.node": self.settings.node,
                },
                volumes={
                    self.settings.host_path(self.root): {
                        "bind": "/workspace",
                        "mode": "rw",
                    },
                    self.settings.host_path(self.settings.source / "snapshot"): {
                        "bind": "/frozen",
                        "mode": "ro",
                    },
                },
                environment={
                    "HOME": "/tmp",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "PYTHONPATH": "/frozen/code:/frozen/code/docker/training:/frozen/code/scripts",
                    "QLIB_PROVIDER_URI": "/frozen/qlib",
                    "QUANTDB_DATA_DIR": "/frozen/quantdb",
                },
                log_config=docker.types.LogConfig(
                    type="json-file", config={"max-size": "2m", "max-file": "1"}
                ),
            )
            container.start()
            return container.id

    def stop_container(self, name, remove=False):
        info = self.inspect(name)
        if info is None:
            return
        with self.client() as client:
            if info["State"]["Running"]:
                client.api.kill(info["Id"])
            info = self.inspect(name)
            if info and info["State"]["Running"]:
                raise RuntimeError("尚未确认容器停止")
            if remove:
                client.api.remove_container(name)

    def stop_all(self):
        with self.client() as client:
            containers = client.containers.list(
                all=True,
                filters={
                    "label": [
                        f"quantmind.agent.case={self.ident}",
                        f"quantmind.agent.node={self.settings.node}",
                    ]
                },
            )
        for container in containers:
            self.stop_container(container.name)

    def observe(self, name):
        info = self.inspect(name)
        if info is None:
            return {
                "status": "missing",
                "error": "原容器不存在，不能确定执行结果；不会自动重跑",
            }
        with self.client() as client:
            log = client.api.logs(name, tail=80).decode(errors="replace")[-12000:]
        return {
            "status": "running"
            if info["State"]["Running"]
            else ("completed" if info["State"]["ExitCode"] == 0 else "failed"),
            "exit_code": info["State"]["ExitCode"],
            "log": log,
        }

    async def aexecute(self, command, *, timeout=None):
        name = self.id + "-" + uuid4().hex[:12]
        self.active.add(name)
        launch = asyncio.create_task(
            asyncio.to_thread(
                self.launch, name, command, time.time() + min(timeout or 60, 60)
            )
        )
        try:
            await asyncio.shield(launch)
            while True:
                result = await asyncio.to_thread(self.observe, name)
                if result["status"] != "running":
                    return ExecuteResponse(
                        result.get("log", result.get("error", "")),
                        result.get("exit_code", 1),
                    )
                await asyncio.sleep(0.3)
        finally:
            # Creation can finish after task cancellation; wait then stop the actual container.
            try:
                await launch
            finally:
                await asyncio.to_thread(self.stop_container, name, True)
                self.active.discard(name)

    def execute(self, command, *, timeout=None):
        return asyncio.run(self.aexecute(command, timeout=timeout))

    def upload_files(self, uploads):
        result = []
        for path, content in uploads:
            code = f"import pathlib,base64; p=pathlib.Path({path!r}); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(base64.b64decode({base64.b64encode(content).decode()!r}))"
            response = self.execute("python -c " + shlex.quote(code))
            result.append(
                FileUploadResponse(
                    path=path,
                    error=None if response.exit_code == 0 else "permission_denied",
                )
            )
        return result

    def download_files(self, paths):
        result = []
        for path in paths:
            try:
                content = read_file(self.root, path)
                result.append(
                    FileDownloadResponse(path=path, content=content, error=None)
                )
            except (ValueError, OSError):
                result.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
        return result

    def snapshot_file(self, path):
        content = read_file(self.root, path)
        return {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "content": content.decode("utf-8"),
        }
