#!/usr/bin/env python3
"""v2.0.0: 指示書2.2の3組（主語と目的語の入れ替え、数値、否定）の文を、lint の API と CLI で確かめる試験。

lint は文の意味を判定せず、意味を保ったとも合格とも言わない。期待値は設計の 6.1 の表、2.6〜2.8、1.1、1.3 に従う。
"""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
LINT = SCRIPTS_DIR / "yomiyasu_lint.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402


# 指示書2.2の3組（3つ目の値は、変わった点の種類）
PAIRS = (
    ("田中が佐藤を承認した。", "佐藤が田中を承認した。", "swap"),
    ("保存期間は3日です。", "保存期間は30日です。", "number"),
    ("データを保存します。", "データを保存しません。", "negation"),
)
LINT_HEADER_ZERO = [
    "表現・書式の検査を実行しました。",
    "見直し候補: 0件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
]
LINT_NOT_JUDGED = ["meaning_preservation", "reader_comprehension"]
# 6.1「passed、meaning_preserved のようなキー」。3.9 が使わないとする ok、passed、clean と、1.2 で消す is_clean も見る。
FORBIDDEN_KEYS = ("passed", "pass", "meaning_preserved", "is_clean", "clean", "ok")
FORBIDDEN_PHRASES = ("意味を保った", "合格", "問題ありません")


def run_cli(script, args, stdin=None):
    """CLI を子プロセスで動かす。stdin がなければ空の入力を渡す。"""
    kwargs = {}
    if stdin is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin
    return subprocess.run(
        [sys.executable, "-B", str(script)] + [str(a) for a in args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        **kwargs
    )


def all_keys(value):
    """入れ子の dict のキーをすべて集める。"""
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys |= all_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= all_keys(child)
    return keys


class PairCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v200-pairs-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        # 3.0.0: lint は作業フォルダの外のファイルを読まないので、ファイルを置く一時フォルダで動かす（子のプロセスも）
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def cli_text(self, script, args, stdin=None):
        """CLI を動かし、終了コード0で標準エラーが空であることを確かめてから標準出力を返す。"""
        process = run_cli(script, args, stdin=stdin)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        return process.stdout

    def cli_json(self, script, args, stdin=None):
        """--json の出力を、終了コードと標準エラーを確かめてから読む。"""
        return json.loads(self.cli_text(script, list(args) + ["--json"], stdin=stdin))


class TestLintOfPairSentences(PairCase):
    """6つの文（3組の前後）の lint の表示。"""

    def sentences(self):
        for before, after, _ in PAIRS:
            yield before
            yield after

    def test_first_three_lines_follow_instruction_3_1(self):
        """通常の出力の1〜3行目が指示書3.1と同じ（0件）。「スコア」「/100」「[PASS]」を含まない。"""
        for sentence in self.sentences():
            with self.subTest(sentence=sentence):
                process = run_cli(LINT, [], stdin=sentence + "\n")
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stdout.split("\n")[:3], LINT_HEADER_ZERO)
                for marker in ("スコア", "/100", "[PASS]"):
                    self.assertNotIn(marker, process.stdout)

    def test_json_has_rule_penalty_score_and_no_score(self):
        """JSON に score がなく、rule_penalty_score == 100。"""
        for sentence in self.sentences():
            with self.subTest(sentence=sentence):
                process = run_cli(LINT, ["--json"], stdin=sentence + "\n")
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertNotIn("score", result)
                self.assertEqual(result.get("rule_penalty_score"), 100)


class TestNoMeaningJudgement(PairCase):
    """意味の判定をしないこと。"""

    def test_json_has_not_judged(self):
        """lint の JSON に not_judged がある。"""
        for before, after, _ in PAIRS:
            with self.subTest(before=before):
                for sentence in (before, after):
                    lint_json = self.cli_json(LINT, [], stdin=sentence + "\n")
                    self.assertEqual(lint_json.get("not_judged"), LINT_NOT_JUDGED)
                self.assertEqual(yomiyasu_lint.lint_text(after + "\n").get("not_judged"), LINT_NOT_JUDGED)

    def test_json_has_no_pass_keys(self):
        """lint の JSON に passed、meaning_preserved のようなキーがない（入れ子も見る）。"""
        for before, after, _ in PAIRS:
            with self.subTest(before=before):
                lint_json = self.cli_json(LINT, [], stdin=after + "\n")
                # 形式2の JSON であることを先に確かめる（キーがないまま通らないように）。
                self.assertEqual(lint_json.get("format_version"), 2)
                for key in FORBIDDEN_KEYS:
                    self.assertNotIn(key, all_keys(lint_json))

    def test_outputs_do_not_claim_meaning_or_pass(self):
        """どの出力（lint の通常の出力と JSON）にも「意味を保った」「合格」「問題ありません」がない。"""
        for before, after, _ in PAIRS:
            with self.subTest(before=before):
                outputs = []
                for sentence in (before, after):
                    text = self.cli_text(LINT, [], stdin=sentence + "\n")
                    # 新しい出力であることを先に確かめる（空の出力や古い出力で通らないように）。
                    self.assertEqual(text.split("\n")[:3], LINT_HEADER_ZERO)
                    outputs.append(text)
                    outputs.append(json.dumps(self.cli_json(LINT, [], stdin=sentence + "\n"), ensure_ascii=False))
                for text in outputs:
                    for phrase in FORBIDDEN_PHRASES:
                        self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
