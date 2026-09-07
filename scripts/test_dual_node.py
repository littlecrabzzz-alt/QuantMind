"""Small dependency-free regression check for the deployment boundary."""
import json
import pathlib
import subprocess
import tempfile
import unittest

from dual_node_sync import desired, topology
from dual_node_inventory import runtime_path

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeploymentBoundary(unittest.TestCase):
    def test_snapshot_links_never_share_live_inodes(self):
        rsync = "/opt/homebrew/bin/rsync" if pathlib.Path("/opt/homebrew/bin/rsync").exists() else "rsync"
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source, first, second = (root / name for name in ("live", "first", "second"))
            for path in (source, first, second):
                path.mkdir()
            (source / "input").write_text("immutable input")
            subprocess.run([rsync, "-a", str(source) + "/", str(first) + "/"], check=True)
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
        for name in ("db", "redis", "huntly", "rsshub", "qwenpaw", "data-gateway"):
            self.assertFalse(services[name].get("ports"), name)
        self.assertEqual(services["web"]["ports"][0]["published"], topology()["QM_WEB_PORT"])
        for name in ("quantmind", "celery-worker", "qwenpaw"):
            env = services[name]["environment"]
            self.assertEqual(env["TRAINING_PAUSE_OTHERS"], "false")
            self.assertEqual(env["ENABLE_REAL_TRADING"], "false")
            self.assertEqual(env["HOST_PROJECT_PATH"], topology()["QM_REMOTE_PROJECT"])
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
