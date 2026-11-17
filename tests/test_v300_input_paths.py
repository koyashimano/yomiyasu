"""3.0.0: lint は、コマンドラインで名前を渡されたファイルのうち、作業フォルダの外のファイルと、作業フォルダからの
道筋に点で始まる部分（.env、.git/config、sub/.secret/x.md など）を含むパスを読まない。

断るのは入力の誤り（終了コード2）で、何も書かない。標準入力（-）はいつでも読める。作業フォルダの中のファイルの出力は前と
同じ（ライブラリの関数の値と比べる）。道具が自分で探すフォルダ（用語リスト、references/lists/）と --words のフォルダは、
この決まりに当たらない。
文はすべて合成の文。ファイルは一時フォルダの中にだけ作る。
"""
from pathlib import Path
from unittest import mock
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402

LINT = SCRIPTS / "yomiyasu_lint.py"

OUTSIDE = markdown_visibility.INPUT_PATH_OUTSIDE
HIDDEN = markdown_visibility.INPUT_PATH_HIDDEN
LINT_HINT = "このファイルを検査するときは、標準入力から渡してください（ファイルの名前の代わりに - を渡すか、省きます）"
FINAL = "新しい手順を来週から試します。\n担当は3人です。\n"
# 読ませたくないファイルの中身。断ったときに、標準出力にも標準エラーにも出ないことを確かめる
SECRET = "秘密の合言葉は青い鳥です。\n"
SECRET_WORD = "青い鳥"


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8"))
    return path


def message(path, reason, hint):
    return "Error opening file {}: {}。{}".format(path, reason, hint)


class PathCase(unittest.TestCase):
    """作業フォルダ work（.git がある）と、その外の outside.md を一時フォルダに作る。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.work = self.root / "work"
        (self.work / ".git").mkdir(parents=True)
        (self.work / "a").mkdir()
        write(self.work / "final.md", FINAL)
        write(self.work / "docs" / "note.md", FINAL)
        self.outside = write(self.root / "outside.md", SECRET)
        for name in (".env", ".git/config", "sub/.secret/x.md", ".hidden.md"):
            write(self.work / name, SECRET)
        self.env = dict(os.environ, HOME=str(self.root), PYTHONIOENCODING="utf-8")

    def run_tool(self, script, *args, stdin=None, cwd=None):
        return subprocess.run([sys.executable, "-B", str(script)] + [str(arg) for arg in args],
                              cwd=str(cwd or self.work), env=self.env, capture_output=True, timeout=120,
                              input=(stdin.encode("utf-8") if stdin is not None else None),
                              stdin=(subprocess.DEVNULL if stdin is None else None))

    def assertRefused(self, process, expected):
        stdout = process.stdout.decode("utf-8")
        stderr = process.stderr.decode("utf-8")
        self.assertEqual(process.returncode, 2, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, expected + "\n")
        self.assertNotIn(SECRET_WORD, stdout + stderr)


REFUSED = (
    # (渡すパスの作り方, 理由)
    (lambda case: case.outside, OUTSIDE),
    (lambda case: "../outside.md", OUTSIDE),
    (lambda case: ".env", HIDDEN),
    (lambda case: ".git/config", HIDDEN),
    (lambda case: "sub/.secret/x.md", HIDDEN),
    (lambda case: "a/../.env", HIDDEN),
    (lambda case: case.work / ".env", HIDDEN),
    (lambda case: ".hidden.md", HIDDEN),
)


class HelperTest(PathCase):
    def call(self, path):
        current = os.getcwd()
        os.chdir(str(self.work))
        try:
            return markdown_visibility.input_path_problem(str(path))
        finally:
            os.chdir(current)

    def test_refused_paths(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                self.assertEqual(self.call(path), reason)

    def test_allowed_paths(self):
        for path in ("-", "final.md", "./final.md", self.work / "final.md", "docs/note.md", "docs/../final.md",
                     "missing.md", ""):
            with self.subTest(path=path):
                self.assertIsNone(self.call(path))

    def test_other_drive_is_outside(self):
        # Windows でドライブが違うと commonpath が ValueError を出す。同じフォルダもたどれないので、外のファイルとして断る
        with mock.patch.object(markdown_visibility.os.path, "commonpath", side_effect=ValueError("drives")):
            self.assertEqual(self.call(self.outside), OUTSIDE)
            self.assertEqual(self.call("../outside.md"), OUTSIDE)

    def test_unknown_place_is_outside(self):
        # NUL のほかの理由で realpath が場所を決められないときは、読まずに外とみなす
        real = os.path.realpath

        def realpath(path):
            if path == os.getcwd():
                return real(path)
            raise OSError("realpath")

        with mock.patch.object(markdown_visibility.os.path, "realpath", side_effect=realpath):
            self.assertEqual(self.call("final.md"), OUTSIDE)
        self.assertIsNone(self.call("final\0.md"))

    def test_same_folder_other_spelling(self):
        # macOS などで、大文字と小文字だけ、または日本語の名前の NFC と NFD だけが違うパスは、同じフォルダなら中とみなす。
        # 点で始まる部分と外のファイルは、同じように断る
        import unicodedata
        folder = self.work / unicodedata.normalize("NFD", "ガイド資料")
        write(folder / "a.md", FINAL)
        write(folder / ".env", SECRET)
        nfc = str(self.work / unicodedata.normalize("NFC", "ガイド資料"))
        if not os.path.exists(os.path.join(nfc, "a.md")):
            self.skipTest("このファイルシステムは NFC と NFD を別の名前として扱います")
        current = os.getcwd()
        os.chdir(str(folder))
        try:
            self.assertIsNone(markdown_visibility.input_path_problem(os.path.join(nfc, "a.md")))
            self.assertIsNone(markdown_visibility.input_path_problem(os.path.join(nfc, "missing.md")))
            self.assertEqual(markdown_visibility.input_path_problem(os.path.join(nfc, ".env")), HIDDEN)
            self.assertEqual(markdown_visibility.input_path_problem(str(self.outside)), OUTSIDE)
            upper = str(folder / "a.md").upper()
            if os.path.exists(upper):
                self.assertIsNone(markdown_visibility.input_path_problem(upper))
                self.assertEqual(markdown_visibility.input_path_problem(str(folder / ".ENV").upper()), HIDDEN)
            process = self.run_tool(LINT, "--no-words", os.path.join(nfc, "a.md"), cwd=folder)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        finally:
            os.chdir(current)

    def test_windows_paths(self):
        # Windows のパスの書き方（ntpath）で、作業フォルダ C:\Users\Me\Work から見た中と外。ファイルは開かない
        import ntpath
        import types
        work = "C:\\Users\\Me\\Work"

        def no_stat(path):
            raise OSError("no stat")

        # realpath は作業フォルダからつないで整えるだけにする（Windows で動かしても、本物の作業フォルダを見ない）
        path_module = types.SimpleNamespace(
            normcase=ntpath.normcase, commonpath=ntpath.commonpath, relpath=ntpath.relpath, split=ntpath.split,
            samestat=ntpath.samestat, realpath=lambda path: ntpath.normpath(ntpath.join(work, path)))
        fake = types.SimpleNamespace(path=path_module, sep="\\", curdir=".", getcwd=lambda: work, stat=no_stat)
        cases = (
            ("final.md", None), ("sub\\note.md", None), ("sub/note.md", None), (".\\final.md", None),
            (work + "\\final.md", None), ("c:\\users\\me\\work\\FINAL.md", None),
            (".env", HIDDEN), ("sub\\.secret\\x.md", HIDDEN), ("sub/.secret/x.md", HIDDEN),
            (work + "\\.git\\config", HIDDEN), ("C:\\Users\\Me\\.ssh\\id_rsa", OUTSIDE),
            ("..\\..\\.ssh\\id_rsa", OUTSIDE), ("D:\\Work\\final.md", OUTSIDE),
            ("\\\\server\\share\\x.md", OUTSIDE), ("C:\\Users\\Me\\Workshop\\a.md", OUTSIDE),
        )
        with mock.patch.object(markdown_visibility, "os", fake):
            for path, expected in cases:
                with self.subTest(path=path):
                    self.assertEqual(markdown_visibility.input_path_problem(path), expected)

    def test_symlink_inside_pointing_outside(self):
        link = self.work / "link.md"
        hidden_link = self.work / "hidden-link.md"
        try:
            os.symlink(str(self.outside), str(link))
            os.symlink(str(self.work / ".env"), str(hidden_link))
        except (OSError, NotImplementedError) as error:
            self.skipTest("シンボリックリンクを作れません（{}）".format(error))
        self.assertEqual(self.call("link.md"), OUTSIDE)
        self.assertEqual(self.call("hidden-link.md"), HIDDEN)


class LintTest(PathCase):
    def test_refused(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                self.assertRefused(self.run_tool(LINT, path), message(path, reason, LINT_HINT))
                self.assertRefused(self.run_tool(LINT, "--json", path), message(path, reason, LINT_HINT))

    def test_symlink_refused(self):
        link = self.work / "link.md"
        try:
            os.symlink(str(self.outside), str(link))
        except (OSError, NotImplementedError) as error:
            self.skipTest("シンボリックリンクを作れません（{}）".format(error))
        self.assertRefused(self.run_tool(LINT, "link.md"), message("link.md", OUTSIDE, LINT_HINT))

    def test_inside_output_unchanged(self):
        expected = json.dumps(yomiyasu_lint.lint_text(FINAL), ensure_ascii=True, indent=2) + "\n"
        for path in ("final.md", "./final.md", self.work / "final.md", "-", None):
            with self.subTest(path=path):
                args = ["--json", "--no-words"] + ([path] if path is not None else [])
                process = self.run_tool(LINT, *args, stdin=FINAL if path in ("-", None) else None)
                self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
                self.assertEqual(process.stdout.decode("utf-8"), expected)

    def test_hidden_content_through_stdin(self):
        # 点で始まるファイルの中身も、標準入力からなら検査できる
        process = self.run_tool(LINT, "--json", "--no-words", "-", stdin=SECRET)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout.decode("utf-8")), yomiyasu_lint.lint_text(SECRET))

    def test_words_folder_outside_still_read(self):
        # --words のフォルダは読むファイルの名前が決まっている（allow.txt、flag.txt、flag-patterns.txt）ので、この決まりに当てない
        words = self.root / "shared-words"
        write(words / "flag.txt", "三人\n")
        process = self.run_tool(LINT, "--json", "--words", "../shared-words", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["context"]["words"]["path"], str(words))

    def test_default_words_folder_from_subfolder(self):
        # 自分で探す .yomiyasu-words/ は、作業フォルダの上（git の最上位）にあって名前が点で始まっても、前と同じく読む
        write(self.work / ".yomiyasu-words" / "flag.txt", "三人\n")
        process = self.run_tool(LINT, "--json", "note.md", cwd=self.work / "docs")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["context"]["words"]["path"],
                         str(self.work / ".yomiyasu-words"))


if __name__ == "__main__":
    unittest.main()
