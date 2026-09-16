import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from backend.shared import tushare_pipeline as pipeline


class ArchiveAuthority(unittest.TestCase):
    def test_native_archive_requires_verified_owner_and_preserves_cloud_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(pipeline, 'ROOT', root), patch.dict(os.environ, {'QM_NODE_ROLE': 'archive'}):
                with self.assertRaises(FileNotFoundError):
                    pipeline.authority()
                marker = root / 'ARCHIVE_AUTHORITY.json'
                marker.write_text(json.dumps({'owner_hostname': socket.gethostname(), 'migration_verified': False}))
                with self.assertRaises(ValueError):
                    pipeline.authority()
                marker.write_text(json.dumps({'owner_hostname': socket.gethostname(), 'migration_verified': True}))
                pipeline.authority()
                marker.write_text(json.dumps({'owner_hostname': 'another-node', 'migration_verified': True}))
                with self.assertRaises(ValueError):
                    pipeline.authority()
            (root / 'ARCHIVE_RELOCATED.json').write_text('{}')
            with patch.object(pipeline, 'ROOT', root), patch.dict(os.environ, {'QM_NODE_ROLE': 'authority'}):
                with self.assertRaisesRegex(ValueError, 'relocated'):
                    pipeline.authority()
            with patch.object(pipeline, 'ROOT', root), patch.dict(os.environ, {'QM_NODE_ROLE': 'sandbox'}):
                with self.assertRaises(ValueError):
                    pipeline.authority()


if __name__ == '__main__':
    unittest.main()
