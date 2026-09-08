"""Deployment regression checks; the embedded UI check uses frontend jsdom."""
import json
import ast
import os
import pathlib
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

import dual_node_deploy
import check_cloud_health
from dual_node_sync import content_digest, desired, topology
from dual_node_inventory import runtime_path

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeploymentBoundary(unittest.TestCase):
    def test_embedded_agent_images_use_the_proxy_prefix(self):
        tree = ast.parse((ROOT / "backend/services/api/routers/qwenpaw_ui_proxy.py").read_text())
        script = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "_API_REWRITE_SCRIPT" for t in n.targets))
        js = script.removeprefix("<script>").removesuffix("</script>")
        code = """const {JSDOM}=require('jsdom');
const w=new JSDOM('',{url:'http://localhost:18080',runScripts:'outside-only'}).window;
w.fetch=async()=>{};
w.eval(require('fs').readFileSync(0,'utf8'));
const img=w.document.createElement('img');
img.src='/qwenpaw.png';
require('assert').equal(img.getAttribute('src'),'/api/v1/qwenpaw-ui/qwenpaw.png');
img.setAttribute('src','/logo-light.svg');
require('assert').equal(img.getAttribute('src'),'/api/v1/qwenpaw-ui/logo-light.svg');
w.close();"""
        subprocess.run(["node", "-e", code], input=js, text=True, cwd=ROOT, check=True)

    def test_mac_guard_selects_no_default_services(self):
        services = subprocess.check_output([
            "docker", "compose", "--env-file", ".env.local", "-f", "docker-compose.yml",
            "-f", "deploy/compose.mac-client.yml", "config", "--services"], cwd=ROOT, text=True)
        self.assertEqual(services.strip(), "")

    def test_source_digest_includes_secrets_and_rejects_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / ".env.local").write_text("SECRET=fixture-one")
            nodes = [{"name": ".env.local", "type": "FILE_INFO_TYPE_FILE"}]
            original = content_digest(root, nodes)
            self.assertEqual(original["contentFiles"], 1)
            (root / ".env.local").write_text("SECRET=fixture-two")
            self.assertNotEqual(original, content_digest(root, nodes))
            conflict = "source.sync-conflict-test.py"
            (root / conflict).touch()
            with self.assertRaisesRegex(RuntimeError, "conflict"):
                content_digest(root, [{"name": conflict, "type": "FILE_INFO_TYPE_FILE"}])

    def test_health_requires_all_four_child_services(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        with patch.object(check_cloud_health.urllib.request, "build_opener", return_value=opener):
            self.assertTrue(check_cloud_health.healthy())
            self.assertEqual(opener.open.call_count, 4)
            opener.open.side_effect = [opener.open.return_value, OSError("engine down")]
            self.assertFalse(check_cloud_health.healthy())

    def test_embedded_worker_can_be_disabled_without_importing_app(self):
        tree = ast.parse((ROOT / "backend/main_oss.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_all_services")
        branch = next(n for n in function.body if isinstance(n, ast.If) and "OSS_EMBEDDED_CELERY" in ast.unparse(n))
        for value, expected in (("true", 1), ("false", 0)):
            namespace = {"os": os, "services": [], "run_celery_worker": None}
            with patch.dict(os.environ, {"OSS_EMBEDDED_CELERY": value}):
                exec(compile(ast.Module(body=[branch], type_ignores=[]), "worker-switch", "exec"), namespace)
            self.assertEqual(len(namespace["services"]), expected)

    def test_copy_dest_reuses_changed_backup_blocks(self):
        rsync = "/opt/homebrew/bin/rsync" if pathlib.Path("/opt/homebrew/bin/rsync").exists() else "rsync"
        with tempfile.TemporaryDirectory() as directory:
            source, basis, target = (pathlib.Path(directory) / p for p in ("source", "basis", "target"))
            for p in (source, basis, target):
                p.mkdir()
            original = os.urandom(2 * 1024 * 1024)
            (basis / "postgres.dump").write_bytes(original)
            (source / "postgres.dump").write_bytes(b"changed header" + original[14:])
            stats = subprocess.check_output([rsync, "-a", "--checksum", "--no-whole-file", "--stats",
                "--copy-dest=" + str(basis), str(source) + "/", str(target) + "/"],
                text=True, env={**os.environ, "LC_ALL": "C"})
            literal = next(line for line in stats.splitlines() if line.startswith("Literal data:"))
            self.assertLess(int(literal.split()[2].replace(",", "")), 65536)
            self.assertEqual((target / "postgres.dump").read_bytes(), (source / "postgres.dump").read_bytes())
            self.assertEqual((basis / "postgres.dump").read_bytes(), original)

    def test_completed_initial_snapshot_is_reused(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        with patch.object(dual_node_deploy, "remote", return_value=subprocess.CompletedProcess([], 0)) as remote, \
             patch.object(dual_node_deploy, "stage"), \
             patch.object(dual_node_deploy, "run") as run, \
             patch.object(dual_node_deploy, "ready"), \
             patch.object(dual_node_deploy.urllib.request, "build_opener", return_value=opener):
            dual_node_deploy.deploy(None)
        self.assertEqual(remote.call_count, 2)
        self.assertIn("snapshots/latest/COMPLETE", remote.call_args.args[0])
        self.assertEqual(run.call_count, 2)
        run.assert_called_with("python3", "scripts/dual_node_snapshot.py", "pull")

    def test_resume_refuses_running_writer(self):
        (ROOT / "logs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dual-node-test-", dir=ROOT / "logs") as directory:
            backup = pathlib.Path(directory)
            for name in ("postgres.dump", "postgres-counts.txt", "redis-data.tar.gz",
                         "qwenpaw-data.tar.gz", "qwenpaw-secrets.tar.gz",
                         "qwenpaw-backups.tar.gz", "qwenpaw-shared.tar.gz"):
                (backup / name).write_text("fixture")
            binaries = backup / "bin"
            binaries.mkdir()
            for name, code in {"ssh": "exit 0", "mkdir": "exit 0", "rmdir": "exit 0",
                               "docker": '[ "$1" != inspect ] || echo true'}.items():
                command = binaries / name
                command.write_text("#!/bin/sh\n" + code + "\n")
                command.chmod(0o700)
            result = subprocess.run(["bash", "scripts/dual-node-cutover.sh", "--resume", str(backup)],
                cwd=ROOT, env={**os.environ, "PATH": str(binaries) + ":" + os.environ["PATH"]},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Refusing resume: quantmind is still running", result.stderr)

    def test_busy_cutover_waits_before_health_checks(self):
        cutover = Mock(side_effect=[subprocess.CalledProcessError(75, "cutover"), None])
        with patch.object(dual_node_deploy, "remote", return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(dual_node_deploy, "stage"), \
             patch.object(dual_node_deploy, "run", cutover), \
             patch.object(dual_node_deploy, "ready", side_effect=RuntimeError("health boundary")), \
             patch.object(dual_node_deploy.time, "sleep") as sleep, \
             patch.object(dual_node_deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, "health boundary"):
                dual_node_deploy.deploy(None)
        self.assertEqual(cutover.call_count, 2)
        sleep.assert_called_once_with(30)

    def test_transport_retry_never_retries_failed_cutover(self):
        authority = Mock(side_effect=[subprocess.CompletedProcess([], 255),
                                      subprocess.CompletedProcess([], 1)])
        phases = Mock()
        cutover = Mock(side_effect=subprocess.CalledProcessError(1, "cutover"))
        with patch.object(dual_node_deploy, "remote", authority), \
             patch.object(dual_node_deploy, "stage", phases), \
             patch.object(dual_node_deploy, "run", cutover), \
             patch.object(dual_node_deploy.time, "sleep"), \
             patch.object(dual_node_deploy.subprocess, "run", side_effect=[
                 subprocess.CompletedProcess([], 30), subprocess.CompletedProcess([], 0)]):
            with self.assertRaises(subprocess.CalledProcessError):
                dual_node_deploy.deploy(None)
        self.assertEqual(authority.call_count, 2)
        cutover.assert_called_once_with("bash", "scripts/dual-node-cutover.sh")
        self.assertNotIn("installing_local_tunnel", [call.args[0] for call in phases.call_args_list])

    def test_reconnecting_tunnel_uses_only_loopback(self):
        config = plistlib.loads((ROOT / "deploy/com.quantmind.cloud-tunnel.plist").read_bytes())
        self.assertTrue(config["KeepAlive"])
        args = config["ProgramArguments"]
        forwards = [args[index + 1] for index, value in enumerate(args) if value == "-L"]
        self.assertEqual(forwards, ["127.0.0.1:8000:127.0.0.1:" + topology()["QM_WEB_PORT"],
                                    "127.0.0.1:18080:127.0.0.1:" + topology()["QM_WEB_PORT"]])
        self.assertEqual(args[-1], topology()["QM_SSH_TARGET"])

    def test_snapshot_links_never_share_live_inodes(self):
        rsync = "/opt/homebrew/bin/rsync" if pathlib.Path("/opt/homebrew/bin/rsync").exists() else "rsync"
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source, first, second = (root / name for name in ("live", "first", "second"))
            for path in (source, first, second):
                path.mkdir()
            (source / "input").write_text("immutable input")
            subprocess.run([rsync, "-a", "--copy-dest=" + str(source), str(source) + "/", str(first) + "/"], check=True)
            subprocess.run([rsync, "-a", "--link-dest=" + str(first), str(source) + "/", str(second) + "/"], check=True)
            self.assertEqual((first / "input").stat().st_ino, (second / "input").stat().st_ino)
            self.assertNotEqual((source / "input").stat().st_ino, (first / "input").stat().st_ino)
            (source / "input").write_text("changed live input")
            self.assertEqual((second / "input").read_text(), "immutable input")

    def test_running_shell_ignores_later_file_updates(self):
        prefix = (ROOT / "scripts/dual-node.sh").read_text().split("PROJECT=", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            script = pathlib.Path(directory) / "run.sh"
            original = prefix + 'echo READY\nread -r signal\necho DONE\n'
            script.write_text(original)
            process = subprocess.Popen(["bash", str(script)], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(process.stdout.readline().strip(), "READY")
            script.write_text(original + 'echo UNEXPECTED_FILE_UPDATE\n')
            stdout, stderr = process.communicate("continue\n", timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "DONE")

    def test_runtime_manifest_scope(self):
        for path in ("data/quantdb/state.sqlite", "db/qlib_data/data.bin", "results/snapshot/data.parquet"):
            self.assertTrue(runtime_path(pathlib.Path(path)))
        for path in ("data/stocks/SH600036.json", "data/upgrade_v1.sql", "db/sql/schema.sql", "data/.rsync-partial/file"):
            self.assertFalse(runtime_path(pathlib.Path(path)))

    def test_shared_topology(self):
        config = topology()
        self.assertTrue(3000 <= int(config["QM_WEB_PORT"]) <= 4000)
        for role in ("mac", "cloud"):
            folder = desired(role, config)
            self.assertEqual(folder["type"], "sendreceive")
            self.assertEqual(folder["maxConflicts"], 10)
        self.assertEqual(desired("cloud", config)["path"], config["QM_REMOTE_PROJECT"])

    def test_compose_isolation(self):
        raw = subprocess.check_output([
            "docker", "compose", "--env-file", ".env.local", "-f", "docker-compose.yml",
            "-f", "deploy/compose.cloud.yml", "--project-directory", str(ROOT),
            "config", "--format", "json"], cwd=ROOT)
        config = json.loads(raw)
        services = config["services"]
        self.assertEqual(int(services["quantmind"]["mem_limit"]), 12 * 1024**3)
        for name in ("db", "redis", "huntly", "rsshub", "qwenpaw", "data-gateway"):
            self.assertFalse(services[name].get("ports"), name)
        self.assertEqual(services["web"]["ports"][0]["published"], topology()["QM_WEB_PORT"])
        for name in ("quantmind", "celery-worker", "qwenpaw"):
            env = services[name]["environment"]
            self.assertEqual(env["TRAINING_PAUSE_OTHERS"], "false")
            self.assertEqual(env["ENABLE_REAL_TRADING"], "false")
            self.assertEqual(env["HOST_PROJECT_PATH"], topology()["QM_REMOTE_PROJECT"])
        self.assertEqual(services["quantmind"]["environment"]["TRAINING_MEMORY_LIMIT_GB"], "4")
        self.assertEqual(services["quantmind"]["environment"]["OSS_EMBEDDED_CELERY"], "false")
        self.assertIn("/app/scripts/check_cloud_health.py", services["quantmind"]["healthcheck"]["test"])
        self.assertIn("-S", services["quantmind"]["healthcheck"]["test"])
        for volume in config["volumes"].values():
            self.assertTrue(volume["driver_opts"]["device"].startswith(
                topology()["QM_REMOTE_ROOT"] + "/volumes/"))

    def test_code_excludes_runtime_but_not_secrets(self):
        rules = (ROOT / ".sync-code-ignore").read_text().splitlines()
        for runtime in (".git", ".stversions", "/results*", "/models", "/data/*", "/db/*"):
            self.assertIn(runtime, rules)
        self.assertNotIn(".env.local", rules)
        self.assertNotIn("config/runtime.env", rules)


if __name__ == "__main__":
    unittest.main()
