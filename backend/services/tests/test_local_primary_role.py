"""QM_NODE_ROLE=local（Mac 单节点）的角色语义，见 docs/local-primary.md。在 quantmind-oss 镜像里运行。"""

import importlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("role,allowed", [
    ("local", False), ("authority", False), ("sandbox", True), ("", True), ("archive", True),
])
def test_upstream_collection(monkeypatch, role, allowed):
    monkeypatch.setenv("QM_NODE_ROLE", role)
    from backend.shared import data_source_config
    assert data_source_config.upstream_collection_allowed() is allowed


def _beat(monkeypatch, role):
    monkeypatch.setenv("QM_NODE_ROLE", role)
    sys.modules.pop("backend.services.engine.qlib_app.celery_config", None)
    mod = importlib.import_module("backend.services.engine.qlib_app.celery_config")
    return mod.celery_app.conf.beat_schedule


def test_local_never_schedules_inapp_tushare_acquisition(monkeypatch):
    assert "tushare-acquire-continuation" not in _beat(monkeypatch, "local")


def test_local_keeps_other_market_schedules(monkeypatch):
    local = set(_beat(monkeypatch, "local"))
    sandbox = set(_beat(monkeypatch, "sandbox"))
    assert sandbox - {"tushare-acquire-continuation"} <= local


def test_research_runtime_accepts_local(monkeypatch, tmp_path):
    monkeypatch.setenv("QM_NODE_ROLE", "local")
    from backend.services.engine.research import runtime
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    with pytest.raises(Exception) as exc:
        runtime.settings()
    assert "研究需要已确认的数据角色" not in str(exc.value)


def test_research_runtime_rejects_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("QM_NODE_ROLE", "bogus")
    from backend.services.engine.research import runtime
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        runtime.settings()


def test_tushare_pipeline_authority_rejects_local(monkeypatch):
    monkeypatch.setenv("QM_NODE_ROLE", "local")
    from backend.shared import tushare_pipeline
    with pytest.raises(ValueError):
        tushare_pipeline.authority()


def test_host_path_local_uses_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("QM_NODE_ROLE", "local")
    monkeypatch.setenv("HOST_PROJECT_PATH", str(tmp_path))
    monkeypatch.setenv("HOST_RUNTIME_PATH", str(tmp_path / ".local-primary/project"))
    from backend.shared.docker_host_paths import host_path
    assert host_path("/data/x.parquet") == str(tmp_path / ".local-primary/project/data/x.parquet")
    assert host_path("/app/backend/a.py") == str(tmp_path / "backend/a.py")


@pytest.fixture
def managed_runtime_fixture(tmp_path, monkeypatch):
    """Exercise only the embedded file installer, never Docker or launchd."""
    if shutil.which("git") is None:
        pytest.skip("Runtime source selection requires Git")
    home = tmp_path / "home"
    library = home / "Library/Application Support/QuantMind"
    artifacts = library / "primary-artifacts"
    for name in ("data", "reports"):
        (artifacts / "ashare-takeover/trees/ashare-lab" / name).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    source = tmp_path / "source"
    source.mkdir()
    contents = {
        ".gitignore": "vendor/\nelectron/dist-react/\n.env.local\nconfig/runtime.env\n",
        "docker-compose.yml": "services: {}\n",
        ".dockerignore": "node_modules\n",
        "requirements.txt": "# fixture requirements\n",
        "backend/main_oss.py": "INITIAL = True\n",
        "backend/models/position.py": "class Position: pass\n",
        "backend/CLAUDE.md": "POLICY FIXTURE MUST NOT BE COPIED\n",
        "backend/.agents/rules.md": "POLICY DIRECTORY FIXTURE\n",
        "backend/node_modules/dependency.js": "DEPENDENCY\n",
        "backend/venv/dependency.py": "DEPENDENCY\n",
        "scripts/local-primary.sh": "#!/bin/sh\nexit 0\n",
        "deploy/compose.local-primary.yml": "services: {}\n",
        "docs/runtime.md": "Source documentation fixture\n",
        "alphaagent/__init__.py": "ALPHA = True\n",
        "alphaagent/log/logger.py": "LOGGER_CODE = True\n",
        "TradingAgents-astock/tradingagents/__init__.py": "AGENTS_CODE = True\n",
        "TradingAgents-astock/tradingagents/default_config.py": "DEFAULT_CONFIG = {}\n",
        "TradingAgents-astock/cli/__init__.py": "",
        "TradingAgents-astock/cli/stats_handler.py": "class StatsCallbackHandler: pass\n",
        "TradingAgents-astock/cli/static/welcome.txt": "CLI resource\n",
        "TradingAgents-astock/README.md": "Package readme\n",
        "TradingAgents-astock/LICENSE": "Package license\n",
        "TradingAgents-astock/NOTICE": "Package attribution\n",
        "TradingAgents-astock/pyproject.toml": "[project]\nname = 'fixture'\n",
        "TradingAgents-astock/requirements.txt": ".\n",
        "TradingAgents-astock/web/app.py": "RETIRED_UI = True\n",
        "TradingAgents-astock/.streamlit/config.toml": "[server]\n",
        "TradingAgents-astock/.dockerignore": "Fixture deployment shell\n",
        "TradingAgents-astock/Dockerfile": "FROM fixture\n",
        "TradingAgents-astock/docker-compose.yml": "services: {}\n",
        "TradingAgents-astock/assets/screenshot.png": "MARKETING\n",
        "TradingAgents-astock/tests/test_upstream.py": "UPSTREAM_TEST = True\n",
        "TradingAgents-astock/examples/demo.py": "UPSTREAM_EXAMPLE = True\n",
        "TradingAgents-astock/scripts/smoke.py": "UPSTREAM_SCRIPT = True\n",
        "rd-agent/dependency.py": "DEPENDENCY\n",
        "data/user.json": "USER DATA\n",
        "models/weights.pt": "MODEL DATA\n",
        "logs/runtime.log": "RUNTIME LOG\n",
        "user_notes.txt": "USER FILE\n",
        "vendor/ashare-lab/src/ashare_lab/__init__.py": "FROZEN_SOURCE = True\n",
        "vendor/ashare-lab/src/ashare_lab/AGENTS.md": "POLICY FIXTURE\n",
        "vendor/ashare-lab/frozen-source.json": "{}\n",
        "vendor/ashare-lab/frozen-data.json": "{}\n",
        "vendor/ashare-lab/requirements.txt": "# frozen requirements\n",
        "vendor/ashare-lab/experiments/not-runtime.py": "EXPERIMENT\n",
        "electron/dist-react/index.html": "<html>existing build</html>\n",
        "electron/dist-react/assets/app.js": "EXISTING_BUILD = true;\n",
        ".env.local": "EXISTING_PRIVATE_FIXTURE=local\n",
        "config/runtime.env": "EXISTING_PRIVATE_FIXTURE=runtime\n",
    }
    for relative, value in contents.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def git(root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git(source, "init", "-q")
    git(source, "add", ".")
    git(source, "-c", "user.name=Runtime Fixture", "-c", "user.email=fixture@localhost",
        "commit", "-qm", "source fixture")
    (source / "backend/main_oss.py").write_text("CURRENT_WORKTREE = True\n")
    (source / "scripts/new-staged.py").write_text("STAGED_SOURCE = True\n")
    git(source, "add", "scripts/new-staged.py")
    (source / "scripts/new-staged.py").write_text("CURRENT_STAGED_WORKTREE = True\n")
    (source / "backend/untracked.py").write_text("UNTRACKED_MUST_NOT_DEPLOY = True\n")
    script = Path(__file__).resolve().parents[3] / "scripts/local-primary.sh"
    installer = script.read_text().split("<<'PY_INSTALL_RUNTIME'\n", 1)[1].split("\nPY_INSTALL_RUNTIME", 1)[0]

    def install(target):
        return subprocess.run([sys.executable, "-c", installer, str(source), str(target), str(artifacts)],
                              capture_output=True, text=True)

    return source, library, artifacts, git, install


def test_install_runtime_keeps_integrated_vendor_resources_only(managed_runtime_fixture):
    source, library, artifacts, git, install = managed_runtime_fixture
    target = library / "primary-runtime-vendor-fixture"
    result = install(target)
    assert result.returncode == 0, result.stderr
    vendor = Path("TradingAgents-astock")
    for relative in ("tradingagents/__init__.py", "tradingagents/default_config.py",
                     "cli/__init__.py", "cli/stats_handler.py", "cli/static/welcome.txt",
                     "README.md", "LICENSE", "NOTICE", "pyproject.toml", "requirements.txt"):
        assert (target / vendor / relative).read_bytes() == (source / vendor / relative).read_bytes()
    for relative in ("web", ".streamlit", ".dockerignore", "Dockerfile", "docker-compose.yml",
                     "assets", "tests", "examples", "scripts"):
        assert not os.path.lexists(target / vendor / relative)
    assert (source / vendor / "tests/test_upstream.py").is_file()


def test_install_runtime_copies_only_current_source_and_links_artifacts(managed_runtime_fixture):
    source, library, artifacts, git, install = managed_runtime_fixture
    target = library / "primary-runtime-fixture"
    result = install(target)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    manifest_path = target / "MAIN_CODE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    assert receipt["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest["source_project"] == str(source.resolve())
    assert manifest["source_commit"] == git(source, "rev-parse", "HEAD")
    for name in ("backend/main_oss.py", "scripts/new-staged.py", "backend/models/position.py",
                 "alphaagent/log/logger.py", "vendor/ashare-lab/src/ashare_lab/__init__.py",
                 "electron/dist-react/index.html"):
        assert (target / name).read_bytes() == (source / name).read_bytes()
        assert manifest["files"][name]["sha256"] == hashlib.sha256((target / name).read_bytes()).hexdigest()
        assert manifest["files"][name]["size"] == (target / name).stat().st_size
    for name in (".env.local", "config/runtime.env"):
        assert (target / name).read_bytes() == (source / name).read_bytes()
        assert (target / name).stat().st_mode & 0o777 == 0o600
    for name in (".git", "backend/untracked.py", "backend/node_modules", "backend/venv",
                 "rd-agent", "data", "models", "logs", "user_notes.txt", ".local-primary",
                 "backend/CLAUDE.md", "backend/.agents", "vendor/ashare-lab/experiments",
                 "vendor/ashare-lab/src/ashare_lab/AGENTS.md"):
        assert not os.path.lexists(target / name)
    assert (target / "output").is_symlink()
    assert (target / "output").resolve() == artifacts.resolve()
    for name in ("data", "reports"):
        assert (target / "vendor/ashare-lab" / name).resolve() == (
            artifacts / "ashare-takeover/trees/ashare-lab" / name).resolve()


@pytest.mark.parametrize("kind", ["existing-directory", "existing-link", "outside-library", "linked-parent", "inside-artifacts"])
def test_install_runtime_rejects_existing_or_escaped_destination(managed_runtime_fixture, tmp_path, kind):
    _, library, artifacts, _, install = managed_runtime_fixture
    target = library / "refused-runtime"
    if kind == "existing-directory":
        target.mkdir()
        (target / "retain").write_text("unchanged")
    elif kind == "existing-link":
        target.symlink_to(library / "missing-target")
    elif kind == "outside-library":
        target = tmp_path / "outside-runtime"
    elif kind == "inside-artifacts":
        target = artifacts / "refused-runtime"
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        parent = library / "linked-parent"
        parent.symlink_to(outside, target_is_directory=True)
        target = parent / "runtime"
    result = install(target)
    assert result.returncode != 0
    assert not (target / "MAIN_CODE_MANIFEST.json").exists()
    if kind == "existing-directory":
        assert (target / "retain").read_text() == "unchanged"
    elif kind == "existing-link":
        assert target.is_symlink()
    else:
        assert not target.exists()


def test_install_runtime_uses_nested_repositories_own_tracked_source(managed_runtime_fixture):
    source, library, _, git, install = managed_runtime_fixture
    for name, tracked_file in (("alphaagent", "__init__.py"),
                               ("TradingAgents-astock", "tradingagents/__init__.py")):
        nested = source / name
        git(nested, "init", "-q")
        git(nested, "add", tracked_file)
        git(nested, "-c", "user.name=Runtime Fixture", "-c", "user.email=fixture@localhost",
            "commit", "-qm", "nested source fixture")
        (nested / "not-tracked.py").write_text("NOT_TRACKED_BY_NESTED_REPO = True\n")
    target = library / "nested-runtime"
    result = install(target)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((target / "MAIN_CODE_MANIFEST.json").read_text())
    for name in ("alphaagent", "TradingAgents-astock"):
        assert manifest["nested_repositories"][name] == git(source / name, "rev-parse", "HEAD")
        assert not (target / name / "not-tracked.py").exists()
    assert not (target / "alphaagent/log/logger.py").exists()


def test_install_runtime_refuses_code_links_to_user_files(managed_runtime_fixture, tmp_path):
    source, library, _, git, install = managed_runtime_fixture
    private = tmp_path / "user-file.txt"
    private.write_text("USER FILE MUST NOT ENTER SNAPSHOT\n")
    (source / "backend/linked.py").symlink_to(private)
    git(source, "add", "backend/linked.py")
    target = library / "escaped-source"
    result = install(target)
    assert result.returncode != 0
    assert not (target / "MAIN_CODE_MANIFEST.json").exists()
    assert private.read_text() == "USER FILE MUST NOT ENTER SNAPSHOT\n"
