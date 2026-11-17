#!/usr/bin/env python3
"""v2.0.0: lint の種類 promo。

作者の判断（2026-10-14 朝。紹介記事・宣伝文では評価の語を短く重ねる型「安い。うまい。早い。」も残す）の直し。
文はすべて合成の文。実在の会社や商品の名前は使わない。

- lint: --doc-type promo のとき fragment_run（評価の語だけの短い文の並び）を外す。種類なしとほかの種類は今までどおり。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402

DOC_TYPES = tuple(row[0] for row in markdown_visibility.DOC_TYPES)


# ---- 作者の判断 2: lint の promo で fragment_run を外す ----
FRAGMENTS = "港町の駅前にある食堂の日替わり定食。安い。うまい。早い。\n"


class LintPromoFragmentTest(unittest.TestCase):
    def rules(self, text, doc_type=None):
        return [finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type=doc_type)["findings"]]

    def test_promo_skips_fragment_run(self):
        result = yomiyasu_lint.lint_text(FRAGMENTS, doc_type="promo")
        self.assertNotIn("fragment_run", [finding["rule"] for finding in result["findings"]])
        # 2.2.0 で metaphor_label と bare_verb_chain も外す
        self.assertEqual(result["context"]["skipped_by_doc_type"],
                         {"bare_verb_chain": 0, "emoji_prohibited": 0, "fragment_run": 1, "metaphor_label": 0})
        report = yomiyasu_lint.render_report(result)
        self.assertIn("種類に合わせて外した候補 1件（bare_verb_chain 0件、emoji_prohibited 0件、fragment_run 1件、"
                      "metaphor_label 0件）。", report)

    def test_no_type_and_other_types_keep_fragment_run(self):
        self.assertIn("fragment_run", self.rules(FRAGMENTS))
        for doc_type in DOC_TYPES:
            # 2.2.0: script（台詞・脚本）も、台詞で普通に出る短い文の重ねとして外す
            if doc_type in ("promo", "script"):
                continue
            with self.subTest(doc_type=doc_type):
                self.assertIn("fragment_run", self.rules(FRAGMENTS, doc_type))

    def test_table_row(self):
        self.assertEqual(tuple(yomiyasu_lint.DOC_TYPE_SKIP_RULES["promo"]),
                         ("bare_verb_chain", "emoji_prohibited", "fragment_run", "metaphor_label"))
        self.assertIn("fragment_run", yomiyasu_lint.DOC_TYPE_SKIP_RULES["script"])


if __name__ == "__main__":
    unittest.main()
