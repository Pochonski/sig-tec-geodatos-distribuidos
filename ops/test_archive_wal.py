"""Pruebas del publicador WAL con archivos ficticios fuera de los volúmenes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'archive-wal.sh'
NAME = '000000010000000000000001'


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'wal-test-data'
        scratch.mkdir(exist_ok=True, mode=0o700)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'archive'
        self.archive.mkdir()
        self.source = self.root / NAME
        self.source.write_bytes(b'WAL ficticio para prueba\n')

    def run_archive(self, name=NAME):
        return subprocess.run(['sh', str(SCRIPT), str(self.source), name, str(self.archive)],
                              capture_output=True).returncode

    def test_publish_and_identical_retry(self):
        self.assertEqual(self.run_archive(), 0)
        target = self.archive / NAME
        before = target.stat()
        self.assertEqual(self.run_archive(), 0)
        self.assertEqual(target.stat().st_ino, before.st_ino)
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.archive.iterdir()), [target])

    def test_different_content_never_overwrites(self):
        target = self.archive / NAME
        target.write_bytes(b'Contenido anterior')
        self.assertNotEqual(self.run_archive(), 0)
        self.assertEqual(target.read_bytes(), b'Contenido anterior')

    def test_reject_symlink_and_directory(self):
        target = self.archive / NAME
        target.symlink_to(self.source)
        self.assertNotEqual(self.run_archive(), 0)
        target.unlink()
        target.mkdir()
        self.assertNotEqual(self.run_archive(), 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_invalid_name_and_missing_source(self):
        self.assertEqual(self.run_archive('../escape'), 64)
        self.source.unlink()
        self.assertNotEqual(self.run_archive(), 0)
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_concurrent_identical_publish(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: self.run_archive(), range(2)))
        self.assertEqual(result, [0, 0])
        self.assertEqual((self.archive / NAME).read_bytes(), self.source.read_bytes())
        self.assertEqual(len(list(self.archive.iterdir())), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
