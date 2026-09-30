from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.archive.file_copy import copy_complete


class ArchiveFileCopyTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.bin"
        self.dest = self.root / "out" / "game.bin"
        self.source.write_bytes(b"complete source")

    def assert_no_pending(self):
        self.assertEqual(list(self.root.rglob("*.rms-part")), [])

    def test_new_copy(self):
        self.assertTrue(copy_complete(self.source, self.dest))
        self.assertEqual(self.dest.read_bytes(), self.source.read_bytes())
        self.assert_no_pending()

    def test_existing_rom_is_not_overwritten(self):
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            copy_complete(self.source, self.dest)
        self.assertEqual(self.dest.read_bytes(), b"old")

    def test_media_replacement(self):
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"old")
        copy_complete(self.source, self.dest, replace=True)
        self.assertEqual(self.dest.read_bytes(), self.source.read_bytes())
        self.assert_no_pending()

    def test_partial_copy_failure_preserves_old_media(self):
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"old")
        def fail(source, destination):
            Path(destination).write_bytes(b"partial")
            raise OSError("disk full")
        with patch("app.archive.file_copy.shutil.copy2", side_effect=fail):
            with self.assertRaises(OSError):
                copy_complete(self.source, self.dest, replace=True)
        self.assertEqual(self.dest.read_bytes(), b"old")
        self.assert_no_pending()

    def test_short_copy_is_rejected(self):
        with patch("app.archive.file_copy.shutil.copy2",
                   side_effect=lambda source, destination: Path(destination).write_bytes(b"x")):
            with self.assertRaises(OSError):
                copy_complete(self.source, self.dest)
        self.assertFalse(self.dest.exists())
        self.assert_no_pending()

    def test_changed_source_is_rejected(self):
        import shutil
        original = shutil.copy2
        def change(source, destination):
            original(source, destination)
            Path(source).write_bytes(b"changed after copying")
        with patch("app.archive.file_copy.shutil.copy2", side_effect=change):
            with self.assertRaises(OSError):
                copy_complete(self.source, self.dest)
        self.assertFalse(self.dest.exists())
        self.assert_no_pending()

    def test_external_destination_change_is_preserved(self):
        import shutil
        original = shutil.copy2
        def change(source, destination):
            original(source, destination)
            self.dest.write_bytes(b"other writer")
        with patch("app.archive.file_copy.shutil.copy2", side_effect=change):
            with self.assertRaises(OSError):
                copy_complete(self.source, self.dest, replace=True)
        self.assertEqual(self.dest.read_bytes(), b"other writer")
        self.assert_no_pending()

    def test_publish_failure_preserves_old_media(self):
        self.dest.parent.mkdir()
        self.dest.write_bytes(b"old")
        with patch("app.archive.file_copy.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                copy_complete(self.source, self.dest, replace=True)
        self.assertEqual(self.dest.read_bytes(), b"old")
        self.assert_no_pending()

    def test_same_file_is_a_noop(self):
        self.assertFalse(copy_complete(self.source, self.source))
        self.assert_no_pending()
