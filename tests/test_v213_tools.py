#!/usr/bin/env python3
"""v2.1.3: Windows で、標準出力と標準エラーの改行と、閉じた出力先を確かめる。

1. lint は、標準出力と標準エラーに OS によらず "\\n" で書く（Windows の既定は "\\r\\n"）。
   POSIX では、Windows と同じく "\\n" を "\\r\\n" に変える流れを sitecustomize で作り、子プロセスでも試す。
2. Windows では、読む側が閉じたパイプに書くと、BrokenPipeError ではなく errno が EINVAL の OSError になる。
   os.name を "nt" にして、BrokenPipeError と同じ案内と終了コード3になること、POSIX では内部エラーのままであることを試す。

文はすべて合成。
"""

import errno
import importlib.util
import io
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import ContextManager
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
LINT = SCRIPTS / "yomiyasu_lint.py"
CLOSED = "出力先が閉じられたため、結果を最後まで書けませんでした。"

FINAL_TEXT = "この記事では、設計を説明します。\n\nテストを書いてください。\n保存期間は30日です。\n"

# Windows の標準出力と標準エラーと同じく、書いた "\n" を "\r\n" に変える流れに差し替える
CRLF_SITECUSTOMIZE = '''
import io
import sys


def _crlf(name):
    stream = getattr(sys, name, None)
    if stream is None or not hasattr(stream, "buffer"):
        return
    encoding, errors = stream.encoding, stream.errors
    line_buffering = stream.line_buffering
    write_through = getattr(stream, "write_through", False)
    stream.flush()
    wrapped = io.TextIOWrapper(stream.detach(), encoding=encoding, errors=errors, newline="\\r\\n",
                               line_buffering=line_buffering, write_through=write_through)
    setattr(sys, name, wrapped)
    setattr(sys, "__{}__".format(name), wrapped)


_crlf("stdout")
_crlf("stderr")
'''


def load(path, name):
    saved = sys.dont_write_bytecode
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


lint = load(LINT, "_v213_tools_lint")


def platform_os(module: ModuleType, name: str) -> ContextManager[object]:
    """Change only the tested module's OS branch, keeping pathlib native."""
    return mock.patch.object(module, "os", SimpleNamespace(**{**vars(os), "name": name}))


class _RecordingStream(object):
    def __init__(self):
        self.calls = []

    def reconfigure(self, **options):
        self.calls.append(options)


class UseUtf8NewlineTests(unittest.TestCase):
    """_use_utf8 は、文字コードと一緒に改行を "\\n" に決める。"""

    def test_reconfigure_passes_newline(self):
        stream = _RecordingStream()
        lint._use_utf8(stream)
        lint._use_utf8(stream, errors="backslashreplace")
        self.assertEqual(stream.calls, [{"encoding": "utf-8", "newline": "\n"},
                                        {"encoding": "utf-8", "newline": "\n", "errors": "backslashreplace"}])

    def test_crlf_stream_writes_lf_after_use_utf8(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp932", newline="\r\n")
        lint._use_utf8(stream)
        stream.write("一行目\n二行目\n")
        stream.flush()
        self.assertEqual(raw.getvalue(), "一行目\n二行目\n".encode("utf-8"))

    def test_streams_without_reconfigure_are_left_alone(self):
        lint._use_utf8(None)
        lint._use_utf8(io.StringIO())


class CrlfConsoleCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tools-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        site = self.root / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_bytes(CRLF_SITECUSTOMIZE.encode("utf-8"))
        self.final = self.root / "final.md"
        self.final.write_bytes(FINAL_TEXT.encode("utf-8"))
        base = dict(os.environ)
        for name in ("PYTHONIOENCODING", "PYTHONUTF8"):
            base.pop(name, None)
        base["HOME"] = str(self.root)
        self.plain_env = dict(base)
        self.crlf_env = dict(base, PYTHONPATH=os.pathsep.join(
            [str(site)] + ([base["PYTHONPATH"]] if base.get("PYTHONPATH") else [])))

    def run_tool(self, args, crlf=True, stdin=None):
        return subprocess.run([sys.executable, "-B"] + [str(arg) for arg in args], cwd=str(self.root),
                              input=stdin, capture_output=True, timeout=60,
                              env=self.crlf_env if crlf else self.plain_env)

    def assert_lf_only(self, data, label):
        self.assertTrue(data, label + " が空です")
        self.assertNotIn(b"\r", data, label)


class CrlfConsoleTests(CrlfConsoleCase):
    """"\\n" を "\\r\\n" に変える標準出力と標準エラーでも、lint は "\\n" だけを書く。"""

    def test_simulated_console_turns_lf_into_crlf(self):
        # この試験の前提: sitecustomize が子プロセスの標準出力と標準エラーを差し替えている
        process = self.run_tool(["-c", "import sys; print('a'); print('b', file=sys.stderr)"])
        self.assertEqual((process.stdout, process.stderr), (b"a\r\n", b"b\r\n"))

    def test_lint_outputs(self):
        cases = {
            "lint": [LINT, self.final],
            "lint --json": [LINT, "--json", self.final],
            "lint --help": [LINT, "--help"],
        }
        for label, args in cases.items():
            with self.subTest(case=label):
                crlf = self.run_tool(args)
                self.assertEqual(crlf.returncode, 0, crlf.stderr)
                self.assert_lf_only(crlf.stdout, label)
                # 改行を変えない流れのときと同じバイト列
                self.assertEqual(crlf.stdout, self.run_tool(args, crlf=False).stdout)

    def test_stdin_input_is_read_as_before(self):
        crlf = self.run_tool([LINT, "--json"], stdin="一行目です。\r\n二行目です。\n".encode("utf-8"))
        plain = self.run_tool([LINT, "--json"], crlf=False, stdin="一行目です。\r\n二行目です。\n".encode("utf-8"))
        self.assertEqual(crlf.returncode, 0, crlf.stderr)
        self.assertEqual(crlf.stdout, plain.stdout)
        self.assertNotIn(b"\r", crlf.stdout)

    def test_error_messages_on_stderr(self):
        cases = {
            "lint usage": ([LINT, "--nope"], 2),
            "lint fail-on": ([LINT, "--fail-on", "nope", self.final], 2),
            "lint missing": ([LINT, self.root / "missing.md"], 2),
        }
        for label, (args, code) in cases.items():
            with self.subTest(case=label):
                crlf = self.run_tool(args)
                self.assertEqual(crlf.returncode, code, crlf.stderr)
                self.assert_lf_only(crlf.stderr, label)
                self.assertEqual(crlf.stderr, self.run_tool(args, crlf=False).stderr)


class _ClosedOnWindows(io.TextIOBase):
    """書けるが、書き出すと Windows の閉じたパイプと同じ OSError（errno EINVAL）を出す標準出力。"""

    def __init__(self, error=None):
        super().__init__()
        self.error = error or OSError(errno.EINVAL, "Invalid argument")

    def writable(self):
        return True

    def write(self, text):
        return len(text)

    def flush(self):
        raise self.error

    def close(self):
        # 後片付けでは書き出さない（試験の外で例外を出さない）
        pass


class ClosedOutputTests(unittest.TestCase):
    """Windows の閉じたパイプ（errno EINVAL の OSError）は、BrokenPipeError と同じ案内と終了コード3にする。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tools-")
        self.addCleanup(folder.cleanup)
        # 3.0.0: lint は作業フォルダの外のファイルを読まないので、ファイルを置く一時フォルダで動かす
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(folder.name)
        final = Path(folder.name) / "final.md"
        final.write_bytes(FINAL_TEXT.encode("utf-8"))
        # lint は結果を書いたあとに書き出す
        self.TOOLS = ((lint, "yomiyasu_lint.py", [str(final)]),)

    def run_main(self, module, args, os_name, error=None):
        stdout, stderr = _ClosedOnWindows(error), io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
                platform_os(module, os_name):
            code = module.main(args)
        return code, stderr.getvalue()

    def test_einval_on_windows_is_a_closed_output(self):
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                code, message = self.run_main(module, args, "nt")
                self.assertEqual(code, 3)
                self.assertEqual(message, "{}: {}\n".format(name, CLOSED))
                self.assertNotIn("Traceback", message)

    def test_einval_message_matches_broken_pipe(self):
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                broken = self.run_main(module, args, "posix", BrokenPipeError(errno.EPIPE, "Broken pipe"))
                self.assertEqual(self.run_main(module, args, "nt"), broken)

    def test_einval_on_posix_is_still_an_internal_error(self):
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                code, message = self.run_main(module, args, "posix")
                self.assertEqual(code, 3)
                self.assertIn("{}: 内部エラー: OSError: [Errno {}]".format(name, errno.EINVAL), message)
                self.assertIn("Traceback", message)
                self.assertNotIn(CLOSED, message)

    def test_other_errors_on_windows_are_still_internal_errors(self):
        others = (OSError(errno.EINVAL, "Invalid argument", "名前:に使えない字.md"),
                  OSError(errno.EIO, "Input/output error"),
                  ValueError("I/O operation on closed file."))
        for module, name, args in self.TOOLS:
            for error in others:
                with self.subTest(tool=name, error=repr(error)):
                    code, message = self.run_main(module, args, "nt", error)
                    self.assertEqual(code, 3)
                    self.assertIn("内部エラー", message)
                    self.assertNotIn(CLOSED, message)

    def test_closed_output_silences_stdout(self):
        """インタプリタの終わりでもう一度書き出しに失敗しないように、_silence_stdout を通してから案内を出す。"""
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                stdout, stderr = _ClosedOnWindows(), io.StringIO()
                with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
                        platform_os(module, "nt"), \
                        mock.patch.object(module, "_silence_stdout") as silence:
                    code = module.main(args)
                self.assertEqual(code, 3)
                silence.assert_called_once_with()
                self.assertEqual(stderr.getvalue(), "{}: {}\n".format(name, CLOSED))


if __name__ == "__main__":
    unittest.main()
