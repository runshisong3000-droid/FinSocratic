import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from finsocratic import source_archive


class ArchiveTests(unittest.TestCase):
    def test_original_round_trip_and_path_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(source_archive,'ROOT',Path(folder)):
                doc={'id':'DOC-ABC123','name':'report.txt'}
                metadata=source_archive.archive(doc,b'original evidence')
                path,saved=source_archive.original(doc['id'])
                self.assertEqual(path.read_bytes(),b'original evidence')
                self.assertEqual(metadata['sha256'],saved['sha256'])
                self.assertIsNone(source_archive.original('../outside'))
