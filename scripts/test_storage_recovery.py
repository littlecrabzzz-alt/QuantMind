import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dual_node_inventory as inv
import dual_node_snapshot as snapshot
import local_market_source as source


class StorageRecoveryTests(unittest.TestCase):
    def test_snapshot_scope_preserves_receipts_and_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ['data/local-market-source/incoming/A/huge',
                     'data/local-market-source/backups/huge',
                     'data/local-market-source/A-receipt.json',
                     'data/frozen-inputs/research/file', 'data/quantdb/file']
            for name in names:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(name)
            self.assertEqual(len(list(inv.inventory(root))), 5)
            self.assertEqual({r['path'] for r in inv.inventory(root, scope='snapshot-v2')}, set(names[2:]))
            self.assertEqual(set(snapshot.runtime_stats(root, scope='snapshot-v2')), set(names[2:]))

    def test_legacy_snapshot_manifest_still_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'project/data/local-market-source/incoming/old'
            p.parent.mkdir(parents=True)
            p.write_text('legacy')
            (root / 'runtime-manifest.jsonl').write_text(snapshot.manifest(root / 'project'))
            snapshot.finish_snapshot(root)
            self.assertTrue((root / 'COMPLETE').exists())

    def test_capacity_rejects_cost_plus_reserve(self):
        import storage_guard as guard
        with patch.object(guard.shutil, 'disk_usage') as usage:
            usage.return_value.free = guard.RESERVE + 10
            with self.assertRaisesRegex(RuntimeError, 'reserve'):
                guard.require_capacity(Path('/'), 11)
            guard.require_capacity(Path('/'), 10)

    def test_research_experiments_and_autonomous_turns_are_protected(self):
        self.assertTrue('qm-research-case-experiment'.startswith(snapshot.RESEARCH_PREFIXES))
        with patch.object(snapshot, 'output', return_value='1'):
            with self.assertRaises(snapshot.BusyError):
                snapshot.require_agent_idle(['quantmind-research-agent'])
        with patch.object(snapshot, 'output', return_value='0'):
            snapshot.require_agent_idle(['quantmind-research-agent'])

    def test_rsync_estimate_parses_bytes(self):
        import storage_guard as guard
        self.assertEqual(guard.transfer_bytes('Total transferred file size: 1,234 bytes\n'), 1234)
        with self.assertRaises(RuntimeError):
            guard.transfer_bytes('bad result')

    def test_guard_stops_child_when_free_space_drops(self):
        import storage_guard as guard
        import sys
        import subprocess
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        with patch.object(guard.subprocess, 'Popen', return_value=process), patch.object(guard, 'require_capacity', side_effect=[None, RuntimeError('reserve')]):
            with self.assertRaisesRegex(RuntimeError, 'reserve'):
                guard.guarded_run(['fixture'], Path('/'))
        self.assertIsNotNone(process.poll())

    def test_signal_cleanup_keeps_lock_until_child_exits(self):
        import storage_guard as guard
        import signal
        import subprocess
        import sys
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            child = root / 'child.py'
            child.write_text("import os,pathlib,time\npathlib.Path('pid').write_text(str(os.getpid()))\ntime.sleep(30)\n")
            parent = root / 'parent.py'
            parent.write_text(
                "import sys\nfrom pathlib import Path\n"
                + "sys.path.insert(0," + repr(str(Path(guard.__file__).parent)) + ")\n"
                + "import storage_guard as g\ng.require_capacity=lambda *a,**kw: None\ng.install_signal_handlers()\n"
                + "with g.storage_lock(Path('.')): g.guarded_run([sys.executable,'child.py'], Path('.'))\n")
            for sig in (signal.SIGTERM, signal.SIGHUP):
                (root / 'pid').unlink(missing_ok=True)
                proc = subprocess.Popen([sys.executable, str(parent)], cwd=root, stderr=subprocess.DEVNULL)
                try:
                    for _ in range(100):
                        if (root / 'pid').exists():
                            break
                        time.sleep(0.01)
                    self.assertTrue((root / 'pid').exists())
                    pid = int((root / 'pid').read_text())
                    with self.assertRaises(BlockingIOError):
                        with guard.storage_lock(root):
                            pass
                    proc.send_signal(sig)
                    proc.wait(timeout=10)
                    self.assertNotEqual(proc.returncode, 0)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
                    with guard.storage_lock(root):
                        pass
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()

    def test_bulk_operations_share_an_exclusive_lock(self):
        import storage_guard as guard
        with tempfile.TemporaryDirectory() as tmp:
            with guard.storage_lock(Path(tmp)):
                with self.assertRaises(BlockingIOError):
                    with guard.storage_lock(Path(tmp)):
                        self.fail('second writer admitted')

    def test_managed_rotation_preserves_unknown_and_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = []
            for i in range(5):
                p = root / ('market-' + str(i) * 64)
                p.mkdir()
                (p / 'VERIFIED').touch()
                if i != 0:
                    (p / 'MANAGED-v2').touch()
                os.utime(p, (i + 1, i + 1))
                dirs.append(p)
            removed = source.retain_transport_copies(root, protected=[dirs[1].name], managed_only=True)
            self.assertEqual(removed, [dirs[2].name])
            self.assertTrue(dirs[0].exists())
            self.assertTrue(dirs[1].exists())

    def test_receive_cli_guards_once_and_worker_does_not_recurse(self):
        args = ['local_market_source.py', 'receive', '--root', '/data/local-market-source',
                '--market', 'A', '--release', 'market-' + 'a' * 64]
        with patch.object(source.sys, 'argv', args), patch.object(source, 'install_signal_handlers'), patch.object(source, 'guarded_run') as guard, patch.object(source, 'receive') as receive:
            source.main()
            guard.assert_called_once()
            self.assertEqual(guard.call_args.args[0][-1], '--_storage-worker')
            receive.assert_not_called()
        with patch.object(source.sys, 'argv', [*args, '--_storage-worker']), patch.object(source, 'install_signal_handlers'), patch.object(source, 'guarded_run') as guard, patch.object(source, 'receive', return_value={'status': 'applied'}) as receive, patch('builtins.print'):
            source.main()
            receive.assert_called_once()
            guard.assert_not_called()

    def test_upload_dry_run_before_payload_and_no_payload_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / ('market-' + 'a' * 64)
            bundle.mkdir()
            (bundle / 'runtime-manifest.jsonl').write_text('{}\n')
            with patch.object(source, 'ssh'), patch.object(source, 'transfer') as transfer, patch.object(source.subprocess, 'check_output', side_effect=['{}', 'invalid stats']):
                with self.assertRaises(RuntimeError):
                    source.send_cloud(bundle, 'A', 'test')
            self.assertEqual(transfer.call_count, 1)
            self.assertIn('runtime-manifest.jsonl', ' '.join(transfer.call_args.args))


if __name__ == '__main__':
    unittest.main()
