import json
import tempfile
import unittest
from pathlib import Path

from src.integrity import IntegrityError, read_manifest, sha256_file, verify_dataset, verify_file


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / 'data.txt'
        self.data.write_bytes(b'ham\thello\n')
        self.record = {'sha256': sha256_file(self.data), 'bytes': self.data.stat().st_size}
        self.manifest = self.root / 'baseline.json'
        self.manifest.write_text(json.dumps({'algorithm': 'SHA256', 'files': {'data.txt': self.record}}))

    def tearDown(self):
        self.temporary.cleanup()

    def test_original_is_accepted(self):
        self.assertEqual(verify_file(self.data, self.record), self.record['sha256'])

    def test_same_size_byte_change_is_rejected(self):
        original_manifest = self.manifest.read_bytes()
        self.data.write_bytes(b'ham\tHello\n')
        with self.assertRaises(IntegrityError):
            verify_dataset(self.root, self.manifest)
        self.assertEqual(self.manifest.read_bytes(), original_manifest)

    def test_missing_data_is_rejected(self):
        self.data.unlink()
        with self.assertRaises(IntegrityError):
            verify_file(self.data, self.record)

    def test_parent_traversal_in_manifest_is_rejected(self):
        self.manifest.write_text(json.dumps({'algorithm': 'SHA256', 'files': {'../outside': self.record}}))
        with self.assertRaises(IntegrityError):
            read_manifest(self.manifest)

    def test_symlink_outside_project_is_rejected(self):
        outside = self.root.parent / (self.root.name + '-outside')
        try:
            outside.write_bytes(self.data.read_bytes())
            self.data.unlink()
            self.data.symlink_to(outside)
            with self.assertRaises(IntegrityError):
                verify_dataset(self.root, self.manifest)
        finally:
            outside.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()

