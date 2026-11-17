"""Drive-relative and home-relative word-list paths must resolve to the folder the user meant."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import ntpath
import os
from pathlib import Path
import pathlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import markdown_visibility as visibility


@contextmanager
def legacy_windows() -> Iterator[None]:
    """Use Python 3.9's actual WindowsPath; fake only the native OS boundary."""
    def native_absolute(path: str) -> str:
        if ntpath.isabs(path):
            return ntpath.normpath(path)
        drive, tail = ntpath.splitdrive(path)
        base = r"D:\drive-work" if drive.upper() == "D:" else r"C:\project"
        return ntpath.normpath(ntpath.join(base, tail if drive else path))

    windows_path = SimpleNamespace(**{**vars(ntpath), "abspath": native_absolute})
    windows_os = SimpleNamespace(**{**vars(os), "path": windows_path, "sep": "\\", "name": "nt"})
    with mock.patch.object(pathlib._windows_flavour, "is_supported", True), \
            mock.patch.object(pathlib.os, "getcwd", return_value=r"C:\project"), \
            mock.patch.object(pathlib.WindowsPath, "is_dir", return_value=True), \
            mock.patch.object(visibility, "Path", pathlib.WindowsPath), \
            mock.patch.object(visibility, "os", windows_os):
        yield


@unittest.skipUnless(sys.version_info[:2] == (3, 9) and os.name != "nt", "Python 3.9 WindowsPath on a non-Windows test host")
class LegacyWindowsPathTest(unittest.TestCase):
    def test_empty_home_keeps_the_literal_tilde_folder(self) -> None:
        for environment in ({"USERPROFILE": ""}, {"HOMEDRIVE": "", "HOMEPATH": ""}):
            with legacy_windows(), mock.patch.dict(os.environ, environment, clear=True):
                with self.subTest(environment=environment, operation="_words_home"):
                    self.assertEqual(visibility._words_home("~/lists"), "~/lists")
                with self.subTest(environment=environment, operation="find_words_folder"):
                    self.assertEqual(visibility.find_words_folder(r"C:\project", "~/lists"),
                                     r"C:\project\~\lists")

    def test_words_folder_keeps_the_other_drives_directory(self) -> None:
        with legacy_windows():
            self.assertEqual(visibility.find_words_folder(r"C:\project", "D:lists"), r"D:\drive-work\lists")


@unittest.skipUnless(os.name == "nt", "requires real Windows drive-relative resolution")
class NativeWindowsDriveTest(unittest.TestCase):
    def test_empty_home_chooses_the_literal_tilde_word_list(self) -> None:
        with tempfile.TemporaryDirectory(prefix="yomiyasu-home-") as folder:
            root = Path(folder)
            for words in (root / "lists", root / "~" / "lists"):
                words.mkdir(parents=True)
                (words / "allow.txt").write_bytes("入口\n".encode("utf-8"))
            for environment in ({"USERPROFILE": ""}, {"HOMEDRIVE": "", "HOMEPATH": ""}):
                with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True):
                    words = visibility.resolve_words(str(root), "~/lists")
                    self.assertEqual(words["path"], str(root / "~" / "lists"))


if __name__ == "__main__":
    unittest.main()
