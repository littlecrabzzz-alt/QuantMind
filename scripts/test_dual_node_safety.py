"""Offline failure-path checks: no production credentials, data or services."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.docker_host_paths import host_path
import dual_node_check as check
import dual_node_git as handoff
import dual_node_inventory as inv
import dual_node_snapshot as snapshot


class Isolation(unittest.TestCase):
    def test_actual_training_path_expressions(self):
        env = {"HOST_PROJECT_PATH": "/host/code", "HOST_RUNTIME_PATH": "/host/code/.local-dev/project",
               "QM_NODE_ROLE": "sandbox"}
        with patch.dict(os.environ, env, clear=True):
            for path in ("/data/quantdb", "/data/quanthk", "/data/quantus", "/data/quantbc",
                         "/data/quantfutures", "/app/db/ai_ide_tmp/runner.py", "/app/models", "/app/results"):
                self.assertTrue(host_path(path, runtime_only=True).startswith(env["HOST_RUNTIME_PATH"] + "/"))
            self.assertEqual(host_path("/app/backend"), "/host/code/backend")
            for path in ("/legacy/data", "/app/backend", "../outside"):
                with self.assertRaises(ValueError):
                    host_path(path, runtime_only=True)
            source = (ROOT / "backend/services/engine/training/local_docker_orchestrator.py").read_text()
            tree = ast.parse(source)
            nodes = [n for n in tree.body if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in {"_LOCAL_DATA_PATH", "_qdb_dir", "_QUANTDB_DATA_HOST_PATH"}
                for t in n.targets)]
            assignment = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == "host_output_dir" for t in n.targets))
            namespace = {"Path": Path, "os": os, "host_path": host_path,
                         "container_work_dir": Path("/data/training_jobs/run-1")}
            exec(compile(ast.Module(body=nodes + [assignment], type_ignores=[]), "training-paths", "exec"), namespace)
            self.assertEqual(str(namespace["host_output_dir"]), env["HOST_RUNTIME_PATH"] + "/data/training_jobs/run-1")
            self.assertEqual(namespace["_QUANTDB_DATA_HOST_PATH"], env["HOST_RUNTIME_PATH"] + "/data/quantdb")
            with patch.dict(os.environ, {"HOST_RUNTIME_PATH": "/host/code"}):
                with self.assertRaises(ValueError):
                    host_path("/data/quantdb")
        with patch.dict(os.environ, {"HOST_PROJECT_PATH": "/cloud/project"}, clear=True):
            self.assertEqual(host_path("/data/quantdb"), "/cloud/project/data/quantdb")
            self.assertEqual(host_path("/custom/data"), "/custom/data")

    def test_fixed_snapshot_can_be_older_than_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".local-dev").mkdir()
            (root / ".local-dev/SNAPSHOT_ID").write_text("snapshot-old")
            (root / "logs/cloud-snapshots/snapshot-old").mkdir(parents=True)
            (root / "logs/cloud-snapshots/snapshot-old/COMPLETE").touch()
            (root / "logs/cloud-snapshots/latest").symlink_to("snapshot-new")
            self.assertEqual(check.validate_sandbox_snapshot(root), "snapshot-old")
            (root / ".local-dev/SNAPSHOT_ID").write_text("snapshot-../../outside")
            with self.assertRaises(RuntimeError):
                check.validate_sandbox_snapshot(root)


# Commands are intercepted in an isolated fixture checkout, never on the host.
FAKE_COMMAND = '''#!PYTHON
import json, os, pathlib, sys
p=pathlib.Path(os.environ['FAKE_STATE'])
s=json.loads(p.read_text())
name=pathlib.Path(sys.argv[0]).name
a=sys.argv[1:]
s['calls'].append([name,*a])
out=''; rc=0
if name=='uname': out='Darwin'
elif name=='sleep': pass
elif name=='lsof': rc=1
elif name=='curl': rc=0 if s.get('healthy', True) else 1
elif name=='launchctl':
    if a[0]=='print': rc=0 if s.get('tunnel',False) else 1
    elif a[0]=='bootout': s['tunnel']=False
    elif a[0]=='bootstrap': s['tunnel']=True
elif name=='docker':
    if a[0]=='context': out=s.get('endpoint','unix:///var/run/docker.sock')
    elif a[0]=='info': out='Docker Desktop'
    elif a[:2]==['volume','ls']: out=s.get('volumes','')
    elif a[0]=='inspect': out='QM_NODE_ROLE=sandbox\\nHOST_RUNTIME_PATH='+os.environ['QM_LOCAL_STATE']
    elif a[0]=='ps': out=s.get('children','')
    elif a[0]=='compose':
        if 'ps' in a: out=s.get('running','')
        elif 'up' in a: rc=s.get('up_rc',0)
        elif 'stop' in a: s['stopped']=True
        elif 'down' in a: s['down']=True
p.write_text(json.dumps(s))
if out: print(out)
sys.exit(rc)
'''


class Lifecycle(unittest.TestCase):
    def invoke(self, args, state, *, initialized=True, snapshot=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'bin').mkdir()
            script = (ROOT / 'scripts/local-dev.sh').read_text().replace(
                'TUNNEL_PLIST="$HOME/Library/LaunchAgents/$TUNNEL_LABEL.plist"',
                'TUNNEL_PLIST="$PROJECT/tunnel.plist"')
            (root / 'scripts/local-dev.sh').write_text(script)
            (root / '.env.local').touch()
            (root / 'tunnel.plist').touch()
            if initialized:
                (root / '.local-dev').mkdir()
                (root / '.local-dev/READY').touch()
                (root / '.local-dev/SNAPSHOT_ID').write_text('snapshot-fixed')
            if snapshot:
                (root / 'logs/cloud-snapshots/snapshot-fixed').mkdir(parents=True)
                (root / 'logs/cloud-snapshots/snapshot-fixed/COMPLETE').touch()
                (root / 'logs/cloud-snapshots/latest').symlink_to('snapshot-fixed')
            state_file = root / 'state.json'
            state_file.write_text(json.dumps({'calls': [], **state}))
            for name in ('docker','uname','launchctl','curl','lsof','sleep'):
                binary=root / 'bin' / name
                binary.write_text(FAKE_COMMAND.replace('PYTHON', sys.executable, 1))
                binary.chmod(0o700)
            environment={k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT','QM_SCRIPT_TEXT'}}
            result=subprocess.run(['bash', str(root / 'scripts/local-dev.sh'), *args], capture_output=True, text=True,
                env={**environment,'PATH':str(root / 'bin')+':'+os.environ['PATH'],'FAKE_STATE':str(state_file)}, timeout=30)
            final=json.loads(state_file.read_text())
            self.assertFalse((root / 'logs/local-dev.lock').exists())
            return result, final

    def test_remote_context_rejected_before_mutation(self):
        result, state=self.invoke(['start'], {'endpoint':'ssh://production'})
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[0]=='launchctl' or 'compose' in c for c in state['calls']))

    def test_existing_postgres_volume_refuses_init(self):
        result,state=self.invoke(['init'], {'volumes':'quantmind-dev_postgres-data'}, initialized=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('postgres-data',result.stderr)
        self.assertFalse(any('compose' in c or 'run' in c for c in state['calls']))

    def test_repeated_start_has_no_side_effects(self):
        result,state=self.invoke(['start','core'], {'running':'db\nredis\nquantmind','healthy':True}, snapshot=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any(c[0]=='launchctl' or 'up' in c or 'stop' in c for c in state['calls']))

    def test_start_failure_restores_original_tunnel(self):
        result,state=self.invoke(['start'], {'tunnel':True,'up_rc':1})
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(state['tunnel'])
        self.assertTrue(state['stopped'])

    def test_health_failure_restores_original_tunnel(self):
        result,state=self.invoke(['start'], {'tunnel':True,'healthy':False})
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(state['tunnel'])
        self.assertTrue(state['stopped'])

    def test_failure_does_not_invent_a_tunnel(self):
        result,state=self.invoke(['start'], {'tunnel':False,'up_rc':1})
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(state['tunnel'])

    def test_partial_stack_and_invalid_mode_are_not_changed(self):
        for args,state in ((['start'],{'running':'db'}), (['start','typo'],{})):
            result,final=self.invoke(args,state)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(c[0]=='launchctl' or 'up' in c or 'stop' in c for c in final['calls']))

    def test_stop_works_without_latest_snapshot(self):
        result,state=self.invoke(['stop'], {'tunnel':False}, snapshot=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(state['down'])
        self.assertTrue(state['tunnel'])
        self.assertFalse(any('--volumes' in c or '-v' in c for c in state['calls']))

    def test_stop_refuses_an_active_sandbox_child(self):
        result, state = self.invoke(['stop'], {'children': 'qm-train-fixture'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Active sandbox child job', result.stderr)
        self.assertFalse(state.get('down'))
        self.assertFalse(any(c[0] == 'launchctl' for c in state['calls']))


class GitHandoff(unittest.TestCase):
    def test_bundle_alignment_preserves_dirty_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source'; destination=Path(directory)/'destination'
            def git(root,*args):
                return subprocess.check_output(['git','-C',str(root),*args],text=True,stderr=subprocess.DEVNULL).strip()
            source.mkdir(); git(source,'init','-b','master')
            git(source,'config','user.email','test@example.invalid'); git(source,'config','user.name','Fixture')
            (source/'file').write_text('base'); git(source,'add','file'); git(source,'commit','-m','base')
            subprocess.run(['git','clone','-q',str(source),str(destination)],check=True)
            old=git(source,'rev-parse','HEAD')
            (source/'file').write_text('committed'); git(source,'commit','-am','next')
            new=git(source,'rev-parse','HEAD')
            for root in (source,destination):
                (root/'file').write_text('uncommitted research')
                (root/'untracked').write_text('RRG')
            with tempfile.TemporaryFile() as bundle:
                with patch.object(handoff,'PROJECT',source):
                    handoff.write_bundle(new,old,bundle)
                bundle.seek(0)
                with patch.object(handoff,'PROJECT',destination), patch.object(handoff.subprocess,'check_output',return_value=json.dumps({'contentDigest':'same'})):
                    handoff.receive_bundle(old,'master',new,'same','cloud',bundle)
            self.assertEqual(git(destination,'rev-parse','HEAD'),new)
            self.assertEqual((destination/'file').read_text(),'uncommitted research')
            self.assertEqual((destination/'untracked').read_text(),'RRG')
            git(destination,'add','file')
            with patch.object(handoff,'PROJECT',destination):
                with self.assertRaisesRegex(RuntimeError,'Staged'):
                    handoff.state()

    def test_alignment_rejects_drift_before_any_git_mutation(self):
        local = {"head": "old", "branch": "master", "sync": {"contentFiles": 1, "contentDigest": "one"}}
        remote = {"head": "new", "branch": "master", "sync": {"contentFiles": 1, "contentDigest": "two"}}
        with patch.object(handoff, "write_bundle") as bundle:
            with self.assertRaisesRegex(RuntimeError, "Working trees differ"):
                check.align_git(local, remote, "cloud")
            remote["branch"] = "another-branch"
            with self.assertRaisesRegex(RuntimeError, "Branches differ"):
                check.align_git(local, remote, "cloud")
            bundle.assert_not_called()

    def test_divergent_history_cannot_be_exported_as_fast_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-b", "master"); git("config", "user.email", "test@example.invalid"); git("config", "user.name", "Fixture")
            (root / "file").write_text("base"); git("add", "file"); git("commit", "-m", "base")
            git("checkout", "-b", "other"); (root / "file").write_text("other"); git("commit", "-am", "other")
            other = git("rev-parse", "HEAD")
            git("checkout", "master"); (root / "file").write_text("main"); git("commit", "-am", "main")
            head = git("rev-parse", "HEAD")
            with patch.object(handoff, "PROJECT", root), tempfile.TemporaryFile() as stream:
                with self.assertRaises(subprocess.CalledProcessError):
                    handoff.write_bundle(head, other, stream)
            self.assertEqual(git("rev-parse", "HEAD"), head)


class SnapshotSafety(unittest.TestCase):
    def test_cache_detects_same_size_same_mtime_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'data').mkdir(); path=root/'data/input'
            path.write_text('old'); old=path.stat(); cache={}
            before=list(inv.inventory(root,cache))
            path.write_text('new'); os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
            after=list(inv.inventory(root,cache))
            self.assertNotEqual(before[0]['sha256'],after[0]['sha256'])
            self.assertEqual(after,list(inv.inventory(root)))

    def test_delta_retains_previous_snapshot_and_copies_hidden_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); live=root/'live'; stage=root/'stage'; previous=root/'previous'
            for p in (live,stage,previous): (p/'data').mkdir(parents=True)
            (live/'data/input').write_text('old'); shutil.copy2(live/'data/input',previous/'data/input')
            os.link(previous/'data/input',stage/'data/input')
            (stage/'data/deleted').write_text('gone')
            copied={r['path']:r for r in inv.inventory(stage)}
            old=(live/'data/input').stat(); (live/'data/input').write_text('new')
            os.utime(live/'data/input',ns=(old.st_atime_ns,old.st_mtime_ns))
            snapshot.copy_runtime_delta(live,stage,copied,list(inv.inventory(live)))
            self.assertEqual(list(inv.inventory(stage)),list(inv.inventory(live)))
            self.assertEqual((previous/'data/input').read_text(),'old')

    def test_validation_failure_never_publishes_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory); (target/'project/data').mkdir(parents=True)
            (target/'project/data/input').write_text('bad')
            (target/'runtime-manifest.jsonl').write_text('wrong')
            with self.assertRaises(RuntimeError): snapshot.finish_snapshot(target)
            self.assertFalse((target/'COMPLETE').exists())

    def test_restore_precedes_final_validation_even_on_failure(self):
        for fail in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory); project=root/'project'; (project/'data').mkdir(parents=True)
                (project/'data/input').write_text('fixed input'); (root/'AUTHORITY').touch()
                for volume in ('redis-data','qwenpaw-data','qwenpaw-secrets','qwenpaw-backups','qwenpaw-shared'):
                    (root/'volumes'/volume).mkdir(parents=True); (root/'volumes'/volume/'file').write_text('cold')
                events=[]
                def output(*args):
                    if args[0]=='findmnt': return 'fixture-uuid'
                    return 'quantmind\nquantmind-redis'
                def run(*args,**kwargs):
                    if args[0]=='docker':
                        events.append(args[1])
                        if args[1]=='exec': kwargs['stdout'].write(b'fixture dump')
                    else: subprocess.run(args,check=True,**kwargs)
                original=snapshot.finish_snapshot
                def finish(target):
                    self.assertIn('start',events); events.append('finish')
                    if fail: raise RuntimeError('verification failed')
                    original(target)
                with patch.object(snapshot,'PROJECT',project), patch.object(snapshot,'REMOTE',str(root)), \
                     patch.object(snapshot,'SETTINGS',{'QM_DISK_UUID':'fixture-uuid'}), \
                     patch.object(snapshot.os,'geteuid',return_value=0), \
                     patch.object(snapshot.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(300*1024**3,0,300*1024**3)), \
                     patch.object(snapshot,'output',side_effect=output), patch.object(snapshot,'run',side_effect=run), \
                     patch.object(snapshot,'finish_snapshot',side_effect=finish), contextlib.redirect_stdout(io.StringIO()):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'verification failed'): snapshot.cloud_snapshot()
                    else: snapshot.cloud_snapshot()
                self.assertEqual((root/'snapshots/latest').is_symlink(),not fail)
                self.assertLess(events.index('start'),events.index('finish'))


class ScheduledPull(unittest.TestCase):
    def test_interrupted_pull_never_publishes_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "snapshot-old"
            old.mkdir()
            (old / "COMPLETE").touch()
            (root / "latest").symlink_to(old.name)
            def run(*args, **kwargs):
                if "--exclude=/COMPLETE" in args:
                    raise OSError("disconnected")
            with patch.object(snapshot, "output", return_value=snapshot.REMOTE + "/snapshots/snapshot-new"), patch.object(snapshot, "run", side_effect=run):
                with self.assertRaises(OSError):
                    snapshot.pull_snapshot(root, True)
            self.assertEqual((root / "latest").resolve(), old.resolve())
            self.assertFalse((root / "snapshot-new/COMPLETE").exists())
            self.assertFalse((root / "snapshot-new/VERIFIED").exists())

    def test_existing_latest_stays_available_during_revalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "snapshot-old"
            target.mkdir()
            (target / "COMPLETE").touch()
            (root / "latest").symlink_to(target.name)
            def run(*args, **kwargs):
                if "--exclude=/COMPLETE" in args:
                    raise OSError("disconnected")
            with patch.object(snapshot, "output", return_value=snapshot.REMOTE + "/snapshots/snapshot-old"), patch.object(snapshot, "run", side_effect=run):
                with self.assertRaises(OSError):
                    snapshot.pull_snapshot(root, True)
            self.assertTrue((target / "COMPLETE").is_file())

    def test_noop_requires_local_verified_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "snapshot-new"
            target.mkdir()
            (root / "latest").symlink_to(target.name)
            (target / "VERIFIED").touch()
            (target / "COMPLETE").touch()
            with patch.object(snapshot, "output", return_value=snapshot.REMOTE + "/snapshots/snapshot-new"), patch.object(snapshot, "run") as run:
                snapshot.pull_snapshot(root, True)
            self.assertEqual(run.call_count, 1)  # remote COMPLETE check; no rsync

    def test_background_install_reuses_data_and_preserves_fixed_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "repo"
            original = project / "logs/cloud-snapshots"
            original.mkdir(parents=True)
            (original / "sentinel").write_text("original data")
            (project / ".local-dev").mkdir()
            fixed = project / ".local-dev/SNAPSHOT_ID"
            fixed.write_text("snapshot-fixed")
            for name in ("scripts/dual_node_snapshot.py", "scripts/dual_node_inventory.py", "scripts/dual_node_sync.py", "scripts/dual_node_check.py", "scripts/quantdb_refresh.py", "deploy/dual-node.env"):
                path = project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            with patch.object(snapshot, "PROJECT", project), patch.object(snapshot.sys, "platform", "darwin"), patch.object(Path, "home", return_value=root), patch.object(snapshot, "run"), patch.object(snapshot.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
                snapshot.install_mac_pull()
                snapshot.install_mac_pull()
            self.assertTrue(original.is_symlink())
            self.assertEqual((original / "sentinel").read_text(), "original data")
            self.assertEqual(fixed.read_text(), "snapshot-fixed")
            import plistlib
            definition = plistlib.loads((root / "Library/LaunchAgents/com.quantmind.snapshot-pull.plist").read_bytes())
            self.assertIn("/usr/local/bin", definition["EnvironmentVariables"]["PATH"].split(":"))



@unittest.skipUnless(os.getenv("QM_TEST_LOCAL_DOCKER") == "1", "explicit local Docker smoke test")
class DockerMounts(unittest.TestCase):
    def test_parent_and_child_share_only_sandbox_runtime(self):
        self.assertEqual(sys.platform, "darwin")
        self.assertFalse(os.getenv("DOCKER_HOST"))
        endpoint = subprocess.check_output(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True).strip()
        self.assertTrue(endpoint.startswith("unix://"))
        self.assertEqual(subprocess.check_output(["docker", "info", "--format", "{{.OperatingSystem}}"], text=True).strip(), "Docker Desktop")
        with tempfile.TemporaryDirectory(prefix="qm-child-mount-", dir="/private/tmp") as directory:
            code = Path(directory); runtime = code / ".local-dev/project"
            for root in (code, runtime):
                (root / "data/quantdb").mkdir(parents=True)
                (root / "data/training_jobs/probe").mkdir(parents=True)
            (code / "data/quantdb/input").write_text("OLD")
            (runtime / "data/quantdb/input").write_text("SNAPSHOT")
            prefix = ["docker", "run", "--rm", "--network", "none", "--read-only"]
            subprocess.run([*prefix, "--mount", f"type=bind,src={runtime / 'data'},dst=/data",
                "--entrypoint", "sh", "postgres:15-alpine", "-ec",
                "echo parent > /data/training_jobs/probe/config.yaml"], check=True, stdout=subprocess.DEVNULL)
            with patch.dict(os.environ, {"HOST_PROJECT_PATH": str(code), "HOST_RUNTIME_PATH": str(runtime), "QM_NODE_ROLE": "sandbox"}):
                workspace = host_path("/data/training_jobs/probe", runtime_only=True)
                data = host_path("/data/quantdb", runtime_only=True)
            subprocess.run([*prefix, "--mount", f"type=bind,src={workspace},dst=/workspace",
                "--mount", f"type=bind,src={data},dst=/input,readonly", "--entrypoint", "sh",
                "postgres:15-alpine", "-ec",
                'test "$(cat /input/input)" = SNAPSHOT; test "$(cat /workspace/config.yaml)" = parent; echo child > /workspace/output'],
                check=True, stdout=subprocess.DEVNULL)
            self.assertEqual((runtime / "data/training_jobs/probe/output").read_text().strip(), "child")
            self.assertFalse((code / "data/training_jobs/probe/output").exists())
            self.assertEqual((code / "data/quantdb/input").read_text(), "OLD")


if __name__=='__main__':
    unittest.main()
