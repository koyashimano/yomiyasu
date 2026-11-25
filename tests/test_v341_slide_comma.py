"""3.4.1: lint の slide_comma の当たった言い方を、数字の区切りの「，」のあとから切り出さない（本家の issue #76）。

本家の tests/test_v341_issue76.py のうち、lint の SlideCommaExcerptTest のみを取り込んだ（diff の試験は、diff を削除したので入れていない）。
文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402


def slide_hits(text):
    result = yomiyasu_lint.lint_text(text, doc_type="slides")
    return [(f["line"], f["message"].split("当たった言い方: ")[1].split("）")[0]) for f in result["findings"] if f["rule"] == "slide_comma"]


class SlideCommaExcerptTest(unittest.TestCase):
    def test_excerpt_does_not_start_after_a_digit_separator(self):
        for text, hits in (("## 売上は１２，０００円、利益は３，０００円\n", [(1, "「売上は１２，０００円、」")]),
                           ("## １２，０００件、達成\n", [(1, "「１２，０００件、」")]),
                           ("## 会員は１，２００，０００人、前年の倍\n", [(1, "「会員は１，２００，０００人、」")]),
                           ("## 費用は１２，５００円，期間は３日\n", [(1, "「費用は１２，５００円，」")]),
                           ("## 売上は12,000円、利益は3,000円\n", [(1, "「売上は12,000円、」")])):
            with self.subTest(text=text):
                self.assertEqual(slide_hits(text), hits)

    def test_commas_written_as_full_width_commas_are_still_boundaries(self):
        """1つの見出しの当たりは1つの候補に並べる。読点の「，」と、あとが3桁でない「，」は今までどおり境目にする。"""
        self.assertEqual(slide_hits("## 背景，課題，対策\n"), [(1, "「背景，」「課題，」")])
        self.assertEqual(slide_hits("## 背景，１２，０００件，対策\n"), [(1, "「背景，」「１２，０００件，」")])
        self.assertEqual(slide_hits("## １，２，３の順に、押す\n"), [(1, "「１，」「２，」「３の順に、」")])
        self.assertEqual(slide_hits("## 売上、１２，０００円、利益、３，０００円\n"), [(1, "「売上、」「１２，０００円、」「利益、」")])

    def test_known_limits_of_the_excerpt(self):
        """引用の中に数字の区切りの「，」があると「…」を付け、時刻の「:」のあとから切り出す（3.4.0 と同じ限り）。"""
        self.assertEqual(slide_hits("## 「１２，０００円」より、安い\n"), [(1, "「…より、」")])
        self.assertEqual(slide_hits("## 会議は12:30、場所は本社\n"), [(1, "「30、」")])
        self.assertEqual(slide_hits("## 会員数１２，０００人の内訳\n"), [])


if __name__ == "__main__":
    unittest.main()
