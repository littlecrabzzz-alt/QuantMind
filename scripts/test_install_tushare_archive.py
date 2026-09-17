from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import install_tushare_archive as install


class ArchiveInstall(unittest.TestCase):
    def test_launch_agent_preserves_short_rate_gate_timers(self):
        document = install.launch_agent_document(
            Path('/archive'),
            Path('/runtime'),
            Path('/runtime/python'),
            Path('/runtime/config/archive.env'),
            Path('/logs'),
        )
        self.assertEqual(document['ProcessType'], 'Interactive')
        self.assertEqual(document['ThrottleInterval'], 60)
        self.assertEqual(document['KeepAlive'], True)
        self.assertEqual(document['ProgramArguments'][-2:], ['--root', '/archive'])

    def test_failed_authority_cannot_install_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(install.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'authority')) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    install.activate(root, root, Path('/python'))
                self.assertEqual(run.call_count, 1)
                self.assertNotIn('launchctl', run.call_args.args[0])

    def test_public_secret_cannot_install_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            secret = root / 'config/archive.env'
            secret.touch(mode=0o644)
            with patch.object(install.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, '0600'):
                    install.activate(root, root, Path('/python'))
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
