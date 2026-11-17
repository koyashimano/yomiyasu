"""v2.4.0: lint をスクリプトとして動かしても、スキルのフォルダに __pycache__ を作らない。

lint は、スクリプトとして動かしたときは markdown_visibility を読み込む前に sys.dont_write_bytecode を真にする。確かめるため、
この試験では -B を付けずに、一時フォルダにコピーしたスキルのフォルダで動かす（リポジトリの scripts には書かない）。
.pyc の置き場所（PYTHONPYCACHEPREFIX）を決めないときと、一時フォルダの中に向けたときの両方で見る。
文はすべて合成の文。
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import run_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "yomiyasu"
TOOL_STEMS = ("yomiyasu_lint.", "markdown_visibility.")
AFTER = "設定の保存期間は30日です✅\n手順は、次のとおりです。\n"


class NoPycacheTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-pycache-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.skill = self.root / "skill"
        shutil.copytree(str(SKILL), str(self.skill), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.scripts = self.skill / "scripts"
        self.after = self.root / "after.md"
        self.after.write_bytes(AFTER.encode("utf-8"))

    def env(self, prefix=None):
        env = dict(os.environ)
        for name in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
            env.pop(name, None)
        if prefix is not None:
            env["PYTHONPYCACHEPREFIX"] = str(prefix)
        return env

    def run_tools(self, env):
        lint = str(self.scripts / "yomiyasu_lint.py")
        runs = (
            ([lint, str(self.after)], None, 0),
            ([lint, str(self.after), "--json"], None, 0),
            ([lint, "-"], AFTER, 0),
            ([lint, "--version"], None, 0),
        )
        for args, stdin, code in runs:
            # -B を付けない（付けると .pyc を書かないことを確かめられない）
            process = run_text([sys.executable] + args, input=stdin, cwd=str(self.root), env=env,
                               capture_output=True, stdin=None if stdin is not None else subprocess.DEVNULL,
                               timeout=120)
            self.assertEqual(process.returncode, code, " ".join(args) + "\n" + process.stdout + process.stderr)

    def pycache_folders(self):
        return sorted(path.relative_to(self.skill).as_posix() for path in self.skill.rglob("__pycache__"))

    def test_no_pycache_beside_the_scripts(self):
        """.pyc の置き場所を決めないとき（Python の既定）は、スクリプトの隣の __pycache__ に書く。"""
        self.run_tools(self.env())
        self.assertEqual(self.pycache_folders(), [])
        self.assertEqual(sorted(path.name for path in self.skill.rglob("*.pyc")), [])

    def test_no_pyc_under_the_cache_prefix(self):
        """PYTHONPYCACHEPREFIX を決めたときは、その下にスクリプトの .pyc を書かない。"""
        prefix = self.root / "pyc"
        self.run_tools(self.env(prefix))
        self.assertEqual(self.pycache_folders(), [])
        written = sorted(path.name for path in prefix.rglob("*.pyc") if path.name.startswith(TOOL_STEMS))
        self.assertEqual(written, [], "スキルのスクリプトの .pyc ができた")

    def test_importing_keeps_the_callers_setting(self):
        """モジュールとして読み込んだときは、読み込む側の sys.dont_write_bytecode を変えない（一時フォルダの写しで読む）。"""
        probe = ("import sys\n"
                 "sys.path.insert(0, sys.argv[1])\n"
                 "import yomiyasu_lint\n"
                 "print('lint', sys.dont_write_bytecode)\n")
        process = subprocess.run([sys.executable, "-c", probe, str(self.scripts)], cwd=str(self.root),
                                 env=self.env(), capture_output=True, encoding="utf-8", timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.splitlines(), ["lint False"])


if __name__ == "__main__":
    unittest.main()
