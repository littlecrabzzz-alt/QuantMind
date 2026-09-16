from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import install_tushare_archive as install


class ArchiveInstall(unittest.TestCase):
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
