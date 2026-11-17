#!/usr/bin/env python3
"""v2.0.0: SKILL.md と道具の食い違いを防ぐ試験（設計 6.7、5章）。

SKILL.md の文と、古い手順と古い表示の文が残っていないことを確かめる。
v1.1.2 では、文字数を書き出す試験（後戻り防止の印を付けた）のほかはすべて失敗する。
"""

from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "skills" / "yomiyasu"
SKILL_MD = PACKAGE / "SKILL.md"

# 6.7 の1つ目: SKILL.md に含む文字列
REQUIRED = (
    "${CLAUDE_SKILL_DIR}/scripts/yomiyasu_lint.py",
    "--doc-type",
    "--reader",
    "### 確認の記録",
    "実行した検査",
    "見直し候補",
)
# 6.7 の1つ目の最後「本文だけの指定の扱いの文」。5.2 の文「…本文だけを返す指定があるときは付けない…」の要の語。
# SKILL.md は以前は敬体で書いていたので「付けません」も受ける（3.1.0 の後で常体にした）。「だけ」は「のみ」にした。
BODY_ONLY_RULE = re.compile(r"本文(?:だけ|のみ)[^。\n]*付け(?:ない|ません)")
# 6.7 の2つ目: SKILL.md に含まない文字列（SKILL.md を常体にしたので、常体の形も並べる）
FORBIDDEN_IN_SKILL = (
    "フルモード",
    "スクリプトの再実行を繰り返す往復は行いません",
    "スクリプトの再実行を繰り返す往復は行わない",
    "修正の試行は最大2回",
    "yomiyasu_lint.py <対象ファイル>",
    # run --stdin が verify を案内するので、ファイルを作らない対話で照合を省く古い文を残さない
    "この照合は行いません",
    "この照合は行わない",
    "最終稿の照合（ファイルを作らない対話のため）",
    # 3.1.0 の後で diff、check、hook を削除した
    "yomiyasu_check.py",
    "yomiyasu_diff.py",
    "yomiyasu_hook.py",
)
# 6.7 の4つ目: SKILL.md、references、README に含まない表示（CHANGELOG の移行の表は除く）
OLD_REPORT_MARKERS = ("AIっぽさ 検査レポート", "[PASS]", "（候補なし）")


def line_of(text, phrase):
    """失敗したときに文書全体を出さず、行番号だけを示す。"""
    position = text.find(phrase)
    return text.count("\n", 0, position) + 1 if position != -1 else None


def documents():
    """SKILL.md、ルートと skills の references、README.md。"""
    paths = [SKILL_MD, ROOT / "README.md"]
    for base in (ROOT / "references", PACKAGE / "references"):
        paths.extend(sorted(path for path in base.rglob("*.md") if path.is_file()))
    return paths


class SkillContractCase(unittest.TestCase):
    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")


class TestSkillText(SkillContractCase):
    """SKILL.md の文。"""

    def test_contains_the_lint_procedure(self):
        """SKILL.md に lint の呼び方と引数、確認の記録の欄の言葉がある。"""
        for phrase in REQUIRED:
            with self.subTest(phrase=phrase):
                self.assertTrue(phrase in self.text, "SKILL.md に「{}」がない".format(phrase))

    def test_states_the_body_only_rule(self):
        """本文だけの指定では確認の記録の欄を付けない、という扱いの文がある（5.2）。"""
        self.assertIsNotNone(BODY_ONLY_RULE.search(self.text), "SKILL.md に本文だけの指定の扱いの文がない")

    def test_drops_the_old_procedure(self):
        """フルモード、往復しない文、修正の試行は最大2回、lint を単に呼ぶ手順が残っていない。"""
        for phrase in FORBIDDEN_IN_SKILL:
            with self.subTest(phrase=phrase):
                self.assertFalse(phrase in self.text, "SKILL.md の{}行目に「{}」がある".format(line_of(self.text, phrase), phrase))

    def test_skill_md_length_is_reported(self):
        """SKILL.md の文字数を出力に書く。上限は設けず、合否には使わない（指示書1章）。（v1.1.2 でも通る後戻り防止）"""
        count = len(self.text)
        sys.stderr.write("\n[test_v200_skill_contract] SKILL.md: {:,}字（{}）\n".format(count, SKILL_MD.relative_to(ROOT)))
        self.assertGreater(count, 0)


class TestOldReportMarkers(SkillContractCase):
    """古い表示を文書に残さない。"""

    def test_documents_do_not_show_old_report_markers(self):
        """SKILL.md、references、README に「AIっぽさ 検査レポート」「[PASS]」「（候補なし）」がない。"""
        for path in documents():
            text = path.read_text(encoding="utf-8")
            for marker in OLD_REPORT_MARKERS:
                with self.subTest(document=str(path.relative_to(ROOT)), marker=marker):
                    self.assertFalse(marker in text, "{}行目に「{}」がある".format(line_of(text, marker), marker))


if __name__ == "__main__":
    unittest.main()
