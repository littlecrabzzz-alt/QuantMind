#!/usr/bin/env python3
"""Run the normal Engine and its existing Celery worker against the Mac sandbox.

Does not restart the main service or the frozen H1 research service. Secrets are
copied through a temporary 0600 env file, never printed or included in argv.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import argparse
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--frontend-port", type=int, help="Start the local UI if this port is free"
)
parser.add_argument(
    "--continuous-research",
    action="store_true",
    help="Isolated GLM research Engine/worker; no paper scheduler",
)
startup_options = parser.parse_args()
continuous = startup_options.continuous_research
prefix = "glm-research" if continuous else "r01-platform"
engine_port = 18084 if continuous else 18083
root = Path(__file__).resolve().parents[1]
base = json.loads(subprocess.check_output(["docker", "inspect", "quantmind-dev"]))[0]
env = dict(v.split("=", 1) for v in base["Config"]["Env"])
assert env.get("QM_NODE_ROLE") == "sandbox", "Only the local sandbox is supported"
keep = {
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "HOST_PROJECT_PATH",
    "HOST_RUNTIME_PATH",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "JWT_SECRET_KEY",
    "SECRET_KEY",
    "INTERNAL_CALL_SECRET",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_PASSWORD",
    "TZ",
    "QLIB_BACKTEST_RESULT_DIR",
    "DASHSCOPE_API_KEY",
    "QWEN_API_KEY",
}
candidate = {k: v for k, v in env.items() if k in keep}
# Reuse the configured provider credential through an in-memory pipe. It never
# reaches strategy subprocesses, argv, logs, or the source archive mount.
secret = subprocess.run(
    [
        "docker",
        "exec",
        "quantmind-dev",
        "python",
        "-c",
        "from backend.shared.runtime_secrets import get_secret; print(get_secret('TUSHARE_TOKEN'), end='')",
    ],
    capture_output=True,
    text=True,
    check=True,
)
if secret.stdout.strip():
    candidate["TUSHARE_TOKEN"] = secret.stdout.strip()
candidate.update(
    QM_NODE_ROLE="sandbox",
    APP_ENV="development",
    APP_EDITION="oss",
    PYTHONPATH="/app",
    STORAGE_MODE="local",
    ENABLE_REAL_TRADING="false",
    ENABLE_VECTORIZED_MATCHER="false",
    AI_STRATEGY_WARMUP="false",
    R01_PACKAGE_ROOT="/r01/etf-daily/v2-fcbabbb7",
    R01_SPLIT_POLICY="/r01-split.json",
    R01_TASK_QUEUE="r01-platform",
    R01_VR_TASK_QUEUE="r01-platform",
    R01_VR_REGISTRY="/data/r01-platform/registry.json",
    R01_VR_MERGE_CACHE="/data/r01-platform/merged",
    R01_SOURCE_ARCHIVE="/source-archive",
    R01_VR_PLATFORM_ONLY="true",
    QLIB_CELERY_QUEUE="r01-platform",
    CELERY_WORKER_MAX_TASKS_PER_CHILD="1",
    AUTO_INFERENCE_ENABLED="false",
    NEWS_ENRICH_ENABLED="false",
    DAILY_SYNC_ENABLED="false",
    MARKET_SYNC_SCHEDULE_ENABLED="false",
    STRATEGY_LAB_SCAN_ENABLED="false",
    MARKET_SNAPSHOT_ENABLED="false",
    TUSHARE_ACQUIRE_CONTINUATION_ENABLED="false",
    R01_VIRTUAL_RUN_SCHEDULE_ENABLED="true",
)
if continuous:
    candidate.update(
        R01_TASK_QUEUE=prefix,
        QLIB_CELERY_QUEUE=prefix,
        R01_VR_TASK_QUEUE=prefix,
        R01_VIRTUAL_RUN_SCHEDULE_ENABLED="false",
    )
password = candidate.get("REDIS_PASSWORD", "")
from urllib.parse import quote

candidate["REDIS_URL"] = (
    "redis://"
    + (":" + quote(password, safe="") + "@" if password else "")
    + candidate.get("REDIS_HOST", "redis")
    + ":"
    + candidate.get("REDIS_PORT", "6379")
    + "/0"
)
runtime = Path(env["HOST_RUNTIME_PATH"])
r01 = Path.home() / "Library/Application Support/QuantMind/r01"
source_archive = Path.home() / "Library/Application Support/QuantMind/tushare"
private_registry = runtime / "data/r01-platform/registry.json"
if not private_registry.exists():
    seed = json.loads((r01 / "package-registry.json").read_text())
    for entry in seed["packages"].values():
        entry["absolute_path"] = str(
            Path("/r01") / Path(entry["absolute_path"]).relative_to(r01)
        )
    private_registry.parent.mkdir(parents=True, exist_ok=True)
    private_registry.write_text(json.dumps(seed, ensure_ascii=False, indent=2))
import sys

sys.path.insert(0, str(root))
from backend.services.simulation.replay.etf_input_package import verify_package_files

seed = json.loads(private_registry.read_text())
registry_changed = False
for entry in seed["packages"].values():
    if entry.get("kind") == "daily_increment" and not entry.get("package_sums_sha256"):
        host_path = r01 / Path(entry["absolute_path"]).relative_to("/r01")
        entry["package_sums_sha256"] = verify_package_files(host_path)
        registry_changed = True
if registry_changed and not continuous:
    private_registry.write_text(json.dumps(seed, ensure_ascii=False, indent=2))
policy = next(
    (
        p / "投资学习与研究/课题/R01-data-split-policy-v1.json"
        for p in root.parents
        if (p / "投资学习与研究/课题/R01-data-split-policy-v1.json").is_file()
    ),
    None,
)
assert policy is not None, (
    "Cannot locate the investment research split policy outside the repository"
)
mounts = []
for src, dst, ro in [
    (root / "backend", "/app/backend", True),
    (root / "scripts", "/app/scripts", True),
    (root / "config", "/app/config", True),
    (root / "strategy_templates", "/app/strategy_templates", True),
    (runtime / "data", "/data", False),
    (runtime / "logs", "/app/logs", False),
    (runtime / "models", "/app/models", False),
    (r01, "/r01", True),
    (policy, "/r01-split.json", True),
    (source_archive, "/source-archive", True),
]:
    mounts += [
        "--mount",
        f"type=bind,src={src},dst={dst}" + (",readonly" if ro else ""),
    ]
if continuous:
    mounts += ["--mount", "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock"]
with tempfile.NamedTemporaryFile(mode="w", prefix="r01-candidate-", delete=False) as f:
    env_path = f.name
    os.chmod(env_path, 0o600)
    for k, v in candidate.items():
        assert "\n" not in v
        f.write(f"{k}={v}\n")
try:
    for name, args, ports in [
        (
            prefix + "-engine",
            [
                "python",
                "-m",
                "uvicorn",
                "backend.services.engine.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            ["-p", f"127.0.0.1:{engine_port}:8000"],
        ),
        (
            prefix + "-worker",
            [
                "python",
                "-m",
                "celery",
                "-A",
                "backend.services.engine.qlib_app.celery_config:celery_app",
                "worker",
                "-Q",
                prefix,
                "--concurrency=2",
                "--loglevel=WARNING",
            ],
            [],
        ),
        (
            "r01-platform-beat",
            [
                "python",
                "-m",
                "celery",
                "-A",
                "backend.services.engine.qlib_app.celery_config:celery_app",
                "beat",
                "--schedule",
                "/data/r01-platform/celerybeat",
                "--loglevel=WARNING",
            ],
            [],
        ),
    ]:
        if continuous and name.endswith("-beat"):
            continue
        existing = subprocess.run(["docker", "inspect", name], capture_output=True)
        if existing.returncode == 0:
            print(name + " already exists; leaving it intact")
            continue
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--restart",
            "unless-stopped",
            "--network",
            "quantmind-dev_quantmind-net",
            "--env-file",
            env_path,
            *ports,
            *([] if ports else ["--no-healthcheck"]),
            *mounts,
            "--entrypoint",
            args[0],
            base["Config"]["Image"],
            *args[1:],
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        print(name + " started")
finally:
    os.unlink(env_path)

if startup_options.frontend_port:
    port = startup_options.frontend_port
    assert 1024 <= port <= 65535
    busy = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True
    )
    if busy.stdout.strip():
        print(f"Frontend port {port} is occupied; leaving the existing process intact")
    else:
        log_path = runtime / f"logs/r01-platform-vite-{port}.log"
        front_env = {
            **os.environ,
            "VITE_PORT": str(port),
            "VITE_API_URL": "http://127.0.0.1:8000",
            "VITE_ENGINE_CANDIDATE_URL": "http://127.0.0.1:18083",
            **(
                {"VITE_CONTINUOUS_RESEARCH_URL": "http://127.0.0.1:18084"}
                if continuous
                else {}
            ),
        }
        with log_path.open("a") as log:
            process = subprocess.Popen(
                [
                    shutil.which("node") or "node",
                    str(root / "node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                ],
                cwd=root / "electron",
                env=front_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (private_registry.parent / f"frontend-{port}.pid").write_text(str(process.pid))
        print(f"Frontend started at http://127.0.0.1:{port}; PID {process.pid}")
