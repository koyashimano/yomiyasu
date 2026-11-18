"""3.1.0 の後: 冗長さの削減の規則。

SKILL.md の「冗長さの削減」の節と、それを指す所（書き換えてよい範囲、情報を追加しない、Step 2）、
references/redundancy.md（2つの写し）、README の原則の一覧を確かめる。
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "yomiyasu" / "SKILL.md"
REF_COPIES = [ROOT / "references", ROOT / "skills" / "yomiyasu" / "references"]


def text(path):
    return path.read_text(encoding="utf-8")


def section(body, heading):
    start = body.index(heading)
    rest = body[start + len(heading):]
    match = re.search(r"\n#{2,3} ", rest)
    return heading + (rest[:match.start()] if match else rest)


class RedundancySkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = text(SKILL)
        cls.part = section(cls.skill, "### 冗長さの削減")

    def test_section_lists_the_types(self):
        for words in ("| 内容の繰り返し |", "| 打ち消すのみの但し書き |", "| 言い直しの括弧 |",
                      "| 近い意味の語の並び |", "| 中身のない副詞 |", "| 案内のみの文と節 |", "| 共通する条件の繰り返し |", "| 主題の繰り返し |"):
            with self.subTest(words=words):
                self.assertIn(words, self.part)

    def test_checks_before_removing(self):
        self.assertIn("その箇所にしかない数値・条件・例外・理由がないかを確かめ、あれば残すか、残す側の文に移す。", self.part)
        self.assertIn("その事実を肯定の文で残す。", self.part)

    def test_keeps(self):
        for words in ("本文のどこにもない条件・限界・数値を述べる但し書き",
                      "初めて出た所の原語と説明（`references/audience.md`）",
                      "「必ず」「確実に」のように保証を表す副詞",
                      "長い文書の冒頭の要約",
                      "manual の手順ごとの前提と警告"):
            with self.subTest(words=words):
                self.assertIn(words, self.part)

    def test_section_comes_after_the_logic_section(self):
        self.assertLess(self.skill.index("### 段落と文の論理構造（つながり）"), self.skill.index("### 冗長さの削減"))
        self.assertLess(self.skill.index("### 冗長さの削減"), self.skill.index("### セルフラベリングと否定対比の整理"))

    def test_other_sections_point_here(self):
        scope = section(self.skill, "### 書き換えてよい範囲")
        self.assertIn("（「冗長さの削減」）", scope)
        no_add = section(self.skill, "### 情報を追加しない")
        self.assertIn("要約の指定がなければ情報を省かない。同じ文書ですでに述べた内容の繰り返しと、", no_add)
        self.assertIn("ここで言う情報に入らない（「冗長さの削減」）。", no_add)
        meaning = section(self.skill, "### 意味の保持")
        self.assertIn("打ち消すのみの但し書きは、否定や条件を変えたことに入らない。", meaning)
        step2 = section(self.skill, "### Step 2:")
        self.assertIn("除いても何も失わない語句（1章「冗長さの削減」）", step2)

    def test_no_priority_slogans(self):
        self.assertNotIn("最優先", self.part)


class RedundancyReferenceTest(unittest.TestCase):
    def test_both_copies_are_the_same(self):
        first, second = (text(refs / "redundancy.md") for refs in REF_COPIES)
        self.assertEqual(first, second)

    def test_reference_has_examples_for_each_type(self):
        body = text(REF_COPIES[0] / "redundancy.md")
        for heading in ("## 2. 内容の繰り返し", "## 3. 打ち消すのみの但し書き", "## 4. 言い直しの括弧",
                        "## 5. 近い意味の語の並び", "## 6. 中身のない副詞", "## 7. 案内のみの文と節", "## 8. 共通する条件の繰り返し", "## 9. 主題の繰り返し"):
            with self.subTest(heading=heading):
                self.assertIn(heading, body)
        self.assertIn("上の数字は Node.js v24 で測った値で、ほかのエンジンでは変わりうる。", body)

    def test_skill_points_to_reference(self):
        self.assertIn("`references/redundancy.md`", text(SKILL))


class ReadmeTest(unittest.TestCase):
    def test_principles(self):
        readme = text(ROOT / "README.md")
        self.assertIn("### 9つの変換原則", readme)
        self.assertNotIn("8つの変換原則", readme)
        self.assertIn("9. 冗長さの削減", readme)


if __name__ == "__main__":
    unittest.main()
