"""Paper scheduler rendering and actual CLI call-site contracts, without services."""
import importlib.util
import json
from pathlib import Path
import plistlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_cli(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("paper_daily_cli_test", ROOT / "scripts/ashare_paper_daily.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = tmp_path / "repo"
    (repo / "deploy").mkdir(parents=True)
    (repo / "deploy/com.quantmind.ashare-paper.plist").write_bytes(
        (ROOT / "deploy/com.quantmind.ashare-paper.plist").read_bytes())
    monkeypatch.setattr(module, "ROOT", repo)
    return module


def test_container_install_does_not_import_host_backend_runtime(monkeypatch, tmp_path):
    cli = load_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "paper_runtime", lambda: pytest.fail("installer must not require host pandas/SQLAlchemy"))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/local/bin/docker")
    out = tmp_path / "LaunchAgents/com.quantmind.ashare-paper.plist"
    args = ["install-launchd", "--container", "quantmind-local-quantmind", "--out", str(out),
            "--user-id", "10000001", "--tenant-id", "default", "--registry-bindings",
            "/app/output/ashare-paper/registry-bindings.json"]
    assert cli.main(args) == 0
    document = plistlib.loads(out.read_bytes())
    command = document["ProgramArguments"]
    assert command[:6] == ["/usr/local/bin/docker", "exec", "quantmind-local-quantmind", "python",
                           "/app/scripts/ashare_paper_daily.py", "tick"]
    assert command[command.index("--archive-root") + 1] == "/data/tushare"
    assert command[command.index("--artifact-root") + 1] == "/app/output"
    assert command[command.index("--readiness") + 1] == "/run/quantmind-market-source/paper-readiness.json"
    assert "--manifest" not in command
    assert document["RunAtLoad"] is False
    assert document["StartInterval"] == 900
    assert "StartCalendarInterval" not in document
    before = out.stat().st_mtime_ns
    assert cli.main(args) == 0
    assert out.stat().st_mtime_ns == before


def test_cli_tick_uses_native_permission_and_scoped_runtime_call(monkeypatch, tmp_path):
    cli = load_cli(monkeypatch, tmp_path)
    bindings = {"user_id": "10000001", "tenant_id": "default", "accounts": {}}
    binding_path = tmp_path / "bindings.json"
    binding_path.write_text(json.dumps(bindings))
    calls = []
    async def authorize(value, user, tenant, names):
        calls.append(("authorize", value, user, tenant, tuple(names)))
    def tick_once(*args):
        calls.append(("tick", args))
        return {"state": "pending", "reasons": ["source QA not ready"]}
    package = ModuleType("ashare_lab")
    package.__path__ = []
    tick_module = ModuleType("ashare_lab.paper_tick")
    tick_module.tick = tick_once
    monkeypatch.setitem(sys.modules, "ashare_lab", package)
    monkeypatch.setitem(sys.modules, "ashare_lab.paper_tick", tick_module)
    monkeypatch.setattr(cli, "paper_runtime", lambda: SimpleNamespace(ACCOUNTS=("lowvol",)))
    monkeypatch.setattr(cli, "validate_bindings", authorize)
    base = tmp_path / "ledgers"
    assert cli.main(["tick", "--user-id", "10000001", "--registry-bindings", str(binding_path),
                     "--ledger-root", str(base), "--archive-root", "/data/tushare",
                     "--artifact-root", "/app/output", "--readiness", "/run/qa/paper-readiness.json"]) == 75
    assert calls[0] == ("authorize", bindings, "10000001", "default", ("lowvol",))
    actual = calls[1][1]
    assert actual[1:5] == (Path("/data/tushare"), Path("/app/output"), "RESEARCH_CURRENT.json", "CURRENT.json")
    assert actual[6].parent == base
    assert actual[8] == bindings


def test_cli_explicit_run_never_omits_bindings(monkeypatch, tmp_path):
    cli = load_cli(monkeypatch, tmp_path)
    path = tmp_path / "bindings.json"
    bindings = {"user_id": "owner", "tenant_id": "tenant", "accounts": {}}
    path.write_text(json.dumps(bindings))
    calls = []
    async def authorize(*args):
        calls.append("authorized")
    def update(*args, **kwargs):
        assert calls == ["authorized"]
        assert kwargs["bindings"] == bindings
        assert kwargs["mode"] == "replay"
        return {"lowvol": {"state": "reconciled", "new_sessions": 0}}
    monkeypatch.setattr(cli, "paper_runtime", lambda: SimpleNamespace(ACCOUNTS=("lowvol",), update=update))
    monkeypatch.setattr(cli, "validate_bindings", authorize)
    assert cli.main(["run", "--user-id", "owner", "--tenant-id", "tenant",
                     "--registry-bindings", str(path), "--manifest", str(tmp_path / "inputs.json"),
                     "--ledger-root", str(tmp_path / "ledgers")]) == 0


@pytest.mark.parametrize("matched", [True, False])
def test_independent_inception_command_writes_fresh_evidence_without_bindings(monkeypatch, tmp_path, matched):
    import hashlib
    cli = load_cli(monkeypatch, tmp_path)
    calls = []
    report = {"matched": matched, "accounts": {"lowvol": {"matched": matched}},
              "no_ledger_mutations": True}
    def reconcile(tree, manifest):
        calls.append((tree, manifest))
        return report
    package = ModuleType("ashare_lab")
    package.__path__ = []
    inception = ModuleType("ashare_lab.paper_inception")
    inception.reconcile_inception = reconcile
    monkeypatch.setitem(sys.modules, "ashare_lab", package)
    monkeypatch.setitem(sys.modules, "ashare_lab.paper_inception", inception)
    monkeypatch.setattr(cli, "paper_runtime", lambda: SimpleNamespace(
        json_bytes=lambda value: (json.dumps(value) + "\n").encode(),
        digest=lambda value: hashlib.sha256(value).hexdigest()))
    monkeypatch.setattr(cli, "validate_bindings", lambda *args: pytest.fail("evidence-only must not authorize or create accounts"))
    output, manifest = tmp_path / "inception.json", tmp_path / "inputs.json"
    source = tmp_path / "archive/trees/ashare-lab-paper/paper"
    args = ["reconcile-inception", "--source-ledgers", str(source),
            "--manifest", str(manifest), "--out", str(output)]
    assert cli.main(args) == int(not matched)
    assert json.loads(output.read_text()) == report
    assert calls == [(source.parent, manifest)]
    before = output.read_bytes()
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        cli.main(args)
    assert calls == [(source.parent, manifest)] and output.read_bytes() == before
