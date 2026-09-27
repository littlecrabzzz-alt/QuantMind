import copy
import json
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.services.engine.research import runtime


class ContainerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.case = self.root / "case"
        self.directory = self.case / "experiments" / "e"
        self.directory.mkdir(parents=True)
        self.source = self.root / "source"
        (self.source / "snapshot").mkdir(parents=True)
        (self.source / "manifest.json").write_text("{}")
        (self.case / "code").mkdir()
        (self.case / "code/worker.py").write_text("# frozen synthetic worker")
        self.cfg = {"development_end": "2026-03-24"}
        self.experiment = {
            "id": "e",
            "container_name": "synthetic-e",
            "proposal": {"kind": "baseline"},
        }
        self.contract = {
            "node_id": "n",
            "source": str(self.source),
            "manifest_sha256": runtime.frozen.sha256(self.source / "manifest.json"),
            "image": {"Id": "sha256:expected", "Os": "linux", "Architecture": "amd64"},
            "code_hashes": {
                "worker.py": runtime.frozen.sha256(self.case / "code/worker.py")
            },
        }
        runtime.frozen.write(self.directory / "config.json", self.cfg)
        runtime.frozen.write(
            self.directory / "proposal.json", self.experiment["proposal"]
        )
        self.intent = {
            "identity": runtime.container_identity(self.directory, self.contract),
            "spec": {
                "entrypoint": "python",
                "command": ["synthetic-worker"],
                "environment": {"PYTHONPATH": "/research-code:/frozen/code"},
                "working_dir": "/output",
            },
        }
        runtime.frozen.write(self.directory / "launch-intent.json", self.intent)
        self.info = {
            "Id": "container-id",
            "Image": "sha256:expected",
            "Config": {
                "Labels": {
                    "quantmind.research.node": "n",
                    "quantmind.research.id": "e",
                },
                "Cmd": ["synthetic-worker"],
                "Entrypoint": ["python"],
                "Env": ["PYTHONPATH=/research-code:/frozen/code"],
                "WorkingDir": "/output",
            },
            "State": {"Status": "running", "Running": True},
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True},
            "Mounts": [
                {"Destination": d, "Source": str(s), "RW": rw, "Type": "bind"}
                for d, s, rw in [
                    ("/output", self.directory, True),
                    ("/frozen", self.source / "snapshot", False),
                    ("/frozen/config.json", self.directory / "config.json", False),
                    ("/research-code", self.case / "code", False),
                ]
            ],
        }
        self.path_patch = patch.object(
            runtime, "host_path", side_effect=lambda p, **_: p
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def check(self, info=None, config=None):
        runtime.check_container(
            info or self.info,
            self.experiment,
            self.directory,
            self.contract,
            self.cfg if config is None else config,
        )

    def test_same_identity_reconnects_without_docker_start(self):
        self.check()
        with (
            patch.object(runtime, "inspect", return_value=self.info),
            patch.object(
                runtime,
                "docker_client",
                side_effect=AssertionError("must not recreate"),
            ),
        ):
            self.assertEqual(
                runtime._launch(
                    self.case,
                    self.experiment,
                    self.cfg,
                    self.contract,
                    time.time() + 600,
                ),
                "container-id",
            )

    def test_changed_inspect_rejected_before_start_or_observe(self):
        changes = [
            lambda i: i.update(Image="sha256:wrong"),
            lambda i: i["HostConfig"].update(ReadonlyRootfs=False),
            lambda i: i["HostConfig"].update(NetworkMode="bridge"),
            lambda i: i["Mounts"][1].update(Source="/wrong"),
            lambda i: i["Mounts"][1].update(RW=True),
            lambda i: i["Mounts"][2].update(Source="/wrong-config"),
            lambda i: i["Mounts"][3].update(Source="/wrong-code"),
            lambda i: i["Mounts"].append(copy.deepcopy(i["Mounts"][0])),
            lambda i: i["Config"].update(Cmd=["other"]),
            lambda i: i["Config"].update(Env=["PYTHONPATH=/wrong"]),
            lambda i: i["Config"].update(WorkingDir="/wrong"),
            lambda i: i["Config"]["Labels"].update(
                {"quantmind.research.node": "other"}
            ),
        ]
        for change in changes:
            info = copy.deepcopy(self.info)
            info["State"]["Status"] = "created"
            change(info)
            with (
                self.subTest(change=change),
                patch.object(runtime, "inspect", return_value=info),
                patch.object(
                    runtime,
                    "docker_client",
                    side_effect=AssertionError("must not start or consume logs"),
                ),
            ):
                with self.assertRaises(ValueError):
                    runtime._launch(
                        self.case,
                        self.experiment,
                        self.cfg,
                        self.contract,
                        time.time() + 600,
                    )
                with self.assertRaises(ValueError):
                    runtime.observe(self.case, self.experiment, self.contract)

    def test_file_drift_and_legacy_missing_identity_fail_closed(self):
        paths = [
            self.directory / "config.json",
            self.directory / "proposal.json",
            self.case / "code/worker.py",
            self.source / "manifest.json",
        ]
        for path in paths:
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.check()
            path.write_bytes(raw)
        runtime.frozen.write(
            self.directory / "launch-intent.json", {"spec": self.intent["spec"]}
        )
        with self.assertRaises(ValueError):
            self.check()

    def test_changed_request_config_or_proposal_rejected(self):
        with self.assertRaises(ValueError):
            self.check(config={"development_end": "2026-03-25"})
        self.experiment["proposal"] = {"kind": "other"}
        with self.assertRaises(ValueError):
            self.check()

    def test_new_container_is_checked_before_start(self):
        (self.directory / "launch-intent.json").unlink()
        container = SimpleNamespace(id="created-id", start=Mock())
        client = SimpleNamespace(
            containers=SimpleNamespace(
                list=Mock(return_value=[]), create=Mock(return_value=container)
            ),
            api=SimpleNamespace(
                inspect_container=Mock(
                    return_value={**self.info, "Image": "sha256:wrong"}
                )
            ),
        )

        @contextmanager
        def fake_client():
            yield client

        docker = SimpleNamespace(errors=SimpleNamespace(DockerException=RuntimeError))
        with (
            patch.object(runtime, "inspect", return_value=None),
            patch.object(runtime, "docker_client", fake_client),
            patch.object(runtime.frozen, "verify"),
            patch.dict("sys.modules", {"docker": docker}),
        ):
            with self.assertRaises(ValueError):
                runtime._launch(
                    self.case,
                    self.experiment,
                    self.cfg,
                    self.contract,
                    time.time() + 600,
                )
        container.start.assert_not_called()
        self.assertTrue((self.directory / "launch-intent.json").exists())

    def test_created_reconnect_starts_once_without_rewriting_files(self):
        info = copy.deepcopy(self.info)
        info["State"]["Status"] = "created"
        files = [
            self.directory / name
            for name in ("launch-intent.json", "config.json", "proposal.json")
        ]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        client = SimpleNamespace(api=SimpleNamespace(start=Mock()))

        @contextmanager
        def fake_client():
            yield client

        with (
            patch.object(runtime, "inspect", return_value=info),
            patch.object(runtime, "docker_client", fake_client),
        ):
            self.assertEqual(
                runtime._launch(
                    self.case,
                    self.experiment,
                    self.cfg,
                    self.contract,
                    time.time() + 600,
                ),
                "container-id",
            )
        client.api.start.assert_called_once_with("container-id")
        self.assertEqual(
            before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        )

    def test_new_matching_container_starts_once(self):
        (self.directory / "launch-intent.json").unlink()
        container = SimpleNamespace(id="new-id", start=Mock())
        created = {}

        def create(**spec):
            created.update(spec)
            return container

        def inspect_created(ident):
            self.assertEqual(ident, "new-id")
            return {
                "Image": created["image"],
                "Config": {
                    "Labels": created["labels"],
                    "Cmd": created["command"],
                    "Entrypoint": [created["entrypoint"]],
                    "Env": [f"{k}={v}" for k, v in created["environment"].items()],
                    "WorkingDir": created["working_dir"],
                },
                "HostConfig": {
                    "NetworkMode": created["network_mode"],
                    "ReadonlyRootfs": created["read_only"],
                },
                "Mounts": [
                    {
                        "Destination": v["bind"],
                        "Source": src,
                        "RW": v["mode"] == "rw",
                        "Type": "bind",
                    }
                    for src, v in created["volumes"].items()
                ],
            }

        client = SimpleNamespace(
            containers=SimpleNamespace(
                list=Mock(return_value=[]), create=Mock(side_effect=create)
            ),
            api=SimpleNamespace(inspect_container=Mock(side_effect=inspect_created)),
        )

        @contextmanager
        def fake_client():
            yield client

        docker = SimpleNamespace(errors=SimpleNamespace(DockerException=RuntimeError))
        with (
            patch.object(runtime, "inspect", return_value=None),
            patch.object(runtime, "docker_client", fake_client),
            patch.object(runtime.frozen, "verify"),
            patch.dict("sys.modules", {"docker": docker}),
        ):
            self.assertEqual(
                runtime._launch(
                    self.case,
                    self.experiment,
                    self.cfg,
                    self.contract,
                    time.time() + 600,
                ),
                "new-id",
            )
        client.containers.create.assert_called_once()
        client.api.inspect_container.assert_called_once_with("new-id")
        container.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
