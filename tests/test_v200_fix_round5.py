#!/usr/bin/env python3
"""v2.0.0（5回目の修正、lint）: 箇条書きの比率の試験。

文はすべてこのファイルで作った合成の文。実在の会社や商品の名前は使わない。

直したこと:

- lint の <details>: 箇条書きの比率（list_ratio と excess_list）を「<details> の外の箇条書きの行 ÷（全体の非空行 − <details> の
  中の箇条書きの行）」にした。中に箇条書きを多く畳んでも、外の箇条書きの比率は薄まらない。この比率は、<details> の中も数えて
  いた前の比率（中と外の箇条書きの行 ÷ 全体の非空行）より大きくならないので、excess_list が新しく出ることはない。
  metrics の total_lines は今までどおり全体の非空行。候補の注記は「リスト行: 外の数 / 全非空行: 分母（<details> の中の箇条書き
  N行は数えていません）」の形にした。

試験のファイルに作者の名前（敬称つき）を書かない（開発の記録の書き方は「作者」にする）ことも、ここで見張る。
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_details_lists import BODY, PR_DOC, as_div, call_lint, lint, rules  # noqa: E402

TESTS = Path(__file__).resolve().parent


# ---- lint の <details>: 比率の分母から中の箇条書きの行を引く ----
OUTSIDE = (
    "\n## 変更点\n\n"
    "- 設定の読み込みを1か所にまとめ、同じ項目を同じ既定値で読むようにした\n"
    "- 起動時に値を検証し、失敗したら足りない項目の名前を出して止まる\n"
    "- 新しい項目は省略でき、省略したときは今までと同じ既定値を使う\n"
    "- 古い形式の設定ファイルも、書き換えずにそのまま読める\n"
    "- 検証の結果は標準エラーに出し、標準出力には何も足さない\n"
    "- 読み込みの順番は今までと同じで、あとに読んだ値が勝つ\n"
)
INSIDE = "".join("- 根拠の項目{}: test_case_{:02d}\n".format(number, number) for number in range(1, 41))
# 外の箇条書きだけで目安を超える文書と、同じ文書のあとに、中に箇条書きを40行畳んだ <details> を足した文書
HEAVY = BODY + OUTSIDE
HEAVY_WITH_DETAILS = HEAVY + "\n<details>\n<summary>根拠（試験の対応）</summary>\n\n" + INSIDE + "\n</details>\n"
# 外に1項目、中に12項目（PR の説明文の形。前の直しで excess_list が消えた形）
ONE_OUTSIDE = (BODY + "\n- 書き換えは要らない\n\n<details>\n<summary>根拠</summary>\n\n"
               + "".join("- 主張{}: claim-{:02d}\n".format(number, number) for number in range(1, 13)) + "\n</details>\n")
# 3つの <details> に4項目ずつ
THREE_SECTIONS = BODY + "".join(
    "\n<details>\n<summary>根拠{}</summary>\n\n".format(section)
    + "".join("- 項目{}-{}: case-{}{}\n".format(section, number, section, number) for number in range(1, 5))
    + "\n</details>\n" for section in range(1, 4))


def old_ratio(metrics):
    """<details> の中も数えていた前の比率（中と外の箇条書きの行 ÷ 全体の非空行）。"""
    total = metrics["total_lines"]
    return (metrics["list_lines"] + metrics.get("details_list_lines", 0)) / total if total else 0


class DetailsRatioTest(unittest.TestCase):
    def test_lists_folded_inside_do_not_hide_outside_lists(self):
        """中に箇条書きを多く畳んでも、外の箇条書きだけで目安を超える文書の excess_list は消えない。"""
        plain, folded = lint(HEAVY), lint(HEAVY_WITH_DETAILS)
        self.assertIn("excess_list", rules(plain))
        self.assertIn("excess_list", rules(folded))
        metrics = folded["metrics"]
        self.assertEqual((metrics["list_lines"], metrics["details_list_lines"], metrics["total_lines"]), (6, 40, 50))
        self.assertEqual(metrics["list_ratio"], round(6 / 10, 3))

    def test_ratio_formula(self):
        for doc in (HEAVY_WITH_DETAILS, ONE_OUTSIDE, THREE_SECTIONS, PR_DOC, HEAVY):
            with self.subTest(doc=doc[-30:]):
                metrics = lint(doc)["metrics"]
                base = metrics["total_lines"] - metrics.get("details_list_lines", 0)
                self.assertEqual(metrics["list_ratio"], round(metrics["list_lines"] / base, 3) if base else 0)

    def test_ratio_is_never_above_the_old_ratio(self):
        """前の比率より大きくならないので、excess_list が新しく出る文書はない（出るなら <div> にした文書でも出る）。"""
        for doc in (HEAVY_WITH_DETAILS, ONE_OUTSIDE, THREE_SECTIONS, PR_DOC, HEAVY):
            with self.subTest(doc=doc[-30:]):
                result = lint(doc)
                self.assertLessEqual(result["metrics"]["list_ratio"], round(old_ratio(result["metrics"]), 3))
                if "excess_list" in rules(result):
                    self.assertIn("excess_list", rules(lint(as_div(doc))))

    def test_pr_shaped_documents_stay_quiet(self):
        """前の直しで excess_list が消えた PR の説明文の形は、消えたまま。"""
        for doc in (PR_DOC, ONE_OUTSIDE, THREE_SECTIONS):
            with self.subTest(doc=doc[-30:]):
                self.assertNotIn("excess_list", rules(lint(doc)))
                self.assertIn("excess_list", rules(lint(as_div(doc))))

    def test_snippet_shows_the_denominator(self):
        finding = [item for item in lint(HEAVY_WITH_DETAILS)["findings"] if item["rule"] == "excess_list"][0]
        self.assertEqual(finding["snippet"], "リスト行: 6 / 全非空行: 10（<details> の中の箇条書き40行は数えていません）")
        self.assertIn("箇条書きの比率（60.0%）", finding["message"])

    def test_total_lines_is_still_every_non_empty_line(self):
        self.assertEqual(lint(HEAVY_WITH_DETAILS)["metrics"]["total_lines"],
                         lint(as_div(HEAVY_WITH_DETAILS))["metrics"]["total_lines"])

    def test_strict_exit_code(self):
        code, out, err = call_lint(["--strict"], stdin=HEAVY_WITH_DETAILS.encode("utf-8"))
        self.assertEqual((code, err), (1, ""))
        self.assertIn("excess_list", out)
        code, _, err = call_lint(["--strict"], stdin=ONE_OUTSIDE.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))


# ---- 試験のファイルに作者の名前を書かない ----
# 作者の名前に敬称を付けた形（名前そのものは書かないよう、文字の番号で作る。test_v200_fix_round3 の見張りと同じ）
OWNER_NOTE = "\u5927\u8cc0" + "\u3055\u3093"


class TestFilesHaveNoOwnerNotesTest(unittest.TestCase):
    def test_no_owner_notes_in_test_files(self):
        found = []
        for path in sorted(TESTS.glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if OWNER_NOTE in line:
                    found.append("{}:{}".format(path.name, number))
        self.assertEqual(found, [])

    def test_the_pattern(self):
        self.assertIsNotNone(re.search(OWNER_NOTE, "x" + OWNER_NOTE + "の判断"))
        self.assertIsNone(re.search(OWNER_NOTE, "作者の判断"))


if __name__ == "__main__":
    unittest.main()
