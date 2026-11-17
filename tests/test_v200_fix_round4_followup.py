#!/usr/bin/env python3
"""v2.0.0（4回目の修正の続き）: 残す限界の試験。

限界として固定する形（直さない。今の出力のまま）:

- lint の lint_text() にライブラリとして先頭の BOM がついた文字列を渡すと、1行目の <details> を見ない（CLI は BOM を外して
  読むので同じ値になる）。
"""

from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_lint  # noqa: E402


# ---- 限界として固定する形（直さない）----
class KnownLimitsFollowupTest(unittest.TestCase):
    def test_lint_text_with_bom(self):
        """lint_text() に先頭の BOM がついた文字列を渡すと、1行目の <details> を見ない（CLI は BOM を外して読む）。"""
        text = ("<details>\n<summary>根拠</summary>\n\n"
                + "".join("- 確かめた点{}: 手順のとおりに動いた\n".format(index) for index in range(1, 7))
                + "\n</details>\n\n確かめたい点があれば、この説明に書き込んでください。計測に使ったデータは、前の週の記録から"
                  "個人の情報を外して作りました。同じ手順で、ほかの画面も速くできるかを次に調べます。\n")
        plain = yomiyasu_lint.lint_text(text)["metrics"]
        self.assertEqual((plain["list_lines"], plain["details_list_lines"]), (0, 6))
        with_bom = yomiyasu_lint.lint_text("﻿" + text)["metrics"]
        self.assertEqual(with_bom["list_lines"], 6)
        self.assertNotIn("details_list_lines", with_bom)


if __name__ == "__main__":
    unittest.main()
