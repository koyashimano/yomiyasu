#!/usr/bin/env python3
"""v2.0.0（G12）: 文書の種類 promo（紹介記事・宣伝文）。

文はすべてこのファイルで作った合成の文。

- lint は、文書の種類が promo のとき emoji_prohibited を外す（書き手の絵文字を残す）。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_lint  # noqa: E402


class PromoDocTypeTest(unittest.TestCase):
    """D-5: 文書の種類 promo（紹介記事・宣伝文）。lint は promo のとき emoji_prohibited を外す。
    fragment_run も外す（作者の判断、2026-10-14 朝。試験は test_v200_tone_stiffness_refine.LintPromoFragmentTest）。"""

    def test_promo_is_a_doc_type(self):
        import markdown_visibility
        self.assertEqual(markdown_visibility.normalize_doc_type(" PROMO "), "promo")
        self.assertIn(("promo", "紹介記事・宣伝文"), [row[:2] for row in markdown_visibility.DOC_TYPES])

    def test_lint_skips_emoji_for_promo(self):
        text = "# 春のおすすめケーキ\n\n新作のケーキが並びました\U0001F370\n"
        plain = yomiyasu_lint.lint_text(text)
        self.assertIn("emoji_prohibited", [f["rule"] for f in plain["findings"]])
        promo = yomiyasu_lint.lint_text(text, doc_type="promo")
        self.assertNotIn("emoji_prohibited", [f["rule"] for f in promo["findings"]])
        # 作者の判断（2026-10-14 朝）で fragment_run も外す（評価の語を短く重ねる型を勢いとして残す）
        # 2.2.0 で metaphor_label と bare_verb_chain も外す
        self.assertEqual(promo["context"]["skipped_by_doc_type"],
                         {"bare_verb_chain": 0, "emoji_prohibited": 1, "fragment_run": 0, "metaphor_label": 0})
        self.assertEqual(yomiyasu_lint.DOC_TYPE_SKIP_RULES["promo"],
                         ("bare_verb_chain", "emoji_prohibited", "fragment_run", "metaphor_label"))

    def test_other_doc_types_keep_emoji(self):
        text = "新作のケーキが並びました\U0001F370\n"
        for value in ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal"):
            with self.subTest(doc_type=value):
                found = yomiyasu_lint.lint_text(text, doc_type=value)
                self.assertIn("emoji_prohibited", [f["rule"] for f in found["findings"]])


if __name__ == "__main__":
    unittest.main()
