#!/usr/bin/env python3
"""v2.0.0（3回目の修正）: 公開の前の掃除の試験。

- リポジトリで公開するファイルに、手元の開発のフォルダの名前を書かない。fixture の説明の欄（description、
  generated_by、source_commit、updates）には、手元の記録と道具の名前も書かない。
- 配布物（scripts、skills、references）に、手元の記録の番号、設計の文書の名前と節の番号、作者の名前を書かない。
"""

from pathlib import Path
import json
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


# ---- 公開の前の掃除: 手元の開発のフォルダの名前 ----
# 試験のファイルそのものに当たらないよう、文字列はつないで作る
PRIVATE_NAMES = tuple(head + tail for head, tail in (("v200", "-development"), ("v200", "-handoff"),
                                                     ("step-", "c-"), ("human", "-evals"), ("codex", "-home")))
# 作り直しを待っている fixture（出どころの欄に手元の道具のパスが残っているもの）。g7_unchanged_outputs.json は作り直して
# 出どころの欄と updates から手元の名前を消したので、今は除くものはない
PENDING_FIXTURES = ()
# fixture の説明の欄（description、generated_by、source_commit、updates）には、手元の記録と道具の名前も書かない。
# 出どころは「lint は G7 の前の出力」のように書き、記録のファイル名や道具のパスで指さない
FIXTURE_NOTE_FILES = ("tests/fixtures/g7_unchanged_outputs.json",)
FIXTURE_NOTE_KEYS = ("description", "generated_by", "source_commit", "updates")
PRIVATE_NOTE_WORDS = PRIVATE_NAMES + tuple(head + tail for head, tail in (
    ("v200", "-"), ("step", "2"), ("step-", "c"), ("-work", "/"), ("/Us", "ers/"), ("DESIGN", "-"), ("GOA", "LS"),
    ("review1", "-"), ("review2", "-"), ("review-", "spec"), ("review-", "fp"), ("review-", "regress"),
    ("questions", ".md"), ("fixture-", "compare"), ("fix-", "round"), ("finalize", ".md"), ("measure", ".md"),
    ("explain-", "changes"), ("before-", "fix"), ("make_unchanged", "_fixture"), ("remake", "_fixture")))
# git がないときに見るもの
PUBLISHED = ("scripts", "skills", "tests", "references", "README.md", "CHANGELOG.md")


def published_files():
    """リポジトリで追跡しているファイルと、追跡の対象になる新しいファイル（.gitignore と info/exclude で外したものを除く）。
    git がなければ PUBLISHED の下を見る。"""
    try:
        process = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError):
        process = None
    if process is not None and process.returncode == 0 and process.stdout:
        names = sorted(set(name for name in process.stdout.decode("utf-8").split("\0") if name))
        return [name for name in names if (ROOT / name).is_file()]
    out = []
    for top in PUBLISHED:
        path = ROOT / top
        if path.is_file():
            out.append(top)
        elif path.is_dir():
            out.extend(str(found.relative_to(ROOT)).replace("\\", "/") for found in sorted(path.rglob("*"))
                       if found.is_file() and "__pycache__" not in found.parts)
    return out


class PrivatePathTest(unittest.TestCase):
    def test_published_files_have_no_private_folder_names(self):
        found = []
        for name in published_files():
            if name in PENDING_FIXTURES:
                continue
            data = (ROOT / name).read_bytes()
            for private in PRIVATE_NAMES:
                if private.encode("utf-8") in data:
                    found.append("{}: {}".format(name, private))
        self.assertEqual(found, [])

    def test_fixture_notes_have_no_private_record_names(self):
        """作り直した fixture の説明の欄に、手元の記録（反証や測りの記録のファイル名）と道具のパスを書かない。"""
        found = []
        for name in FIXTURE_NOTE_FILES:
            data = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for key in FIXTURE_NOTE_KEYS:
                self.assertIn(key, data, name)
                text = json.dumps(data[key], ensure_ascii=False)
                for word in PRIVATE_NOTE_WORDS:
                    if word in text:
                        found.append("{} {}: {}".format(name, key, word))
        self.assertEqual(found, [])

    def test_the_check_covers_the_published_folders(self):
        names = published_files()
        for top in ("scripts/", "skills/yomiyasu/scripts/", "tests/", "references/"):
            with self.subTest(top=top):
                self.assertTrue(any(name.startswith(top) for name in names))
        self.assertIn("README.md", names)
        self.assertIn("CHANGELOG.md", names)


# ---- 配布物（scripts、skills、references）に、手元の記録の番号、設計の文書の名前と節の番号、作者の名前を書かない ----
# 試験の説明（tests の下）は配布物でないので見ない（反証の指摘の番号が残ってもよい）。
DISTRIBUTED_TOPS = ("scripts/", "skills/", "references/")
# 反証の指摘や記録の番号の形（英大文字1〜2字と数。「-」でつないだ形も。例: R9-9、Z9、F99、C-99、W-XY-ok99）
RECORD_ID = re.compile(r"(?<![A-Za-z0-9_+\\])(?:[A-Z]{1,2}-?\d{1,3}(?:-[A-Z]{0,3}\d+)*[a-z]?|[A-Z]-[A-Z]{2}-[a-z]{2}\d+)"
                       r"(?![A-Za-z0-9_])")
# 番号の形でも配布物で使ってよい語: Unicode の異体字セレクタ、ライセンスの名前、例の文の語（社内の略語の例）、noqa の番号
RECORD_ID_ALLOWED = re.compile(r"\bVS1[56]\b|(?i:license v3)|P1対応|noqa: [A-Z]\d+")
# 手元の設計の文書と記録の名前（文字列はつないで作る）
PRIVATE_DOC_NAMES = tuple(head + tail for head, tail in (
    ("DESIGN", "-"), ("GOA", "LS"), ("USER-", "DECISIONS"), ("START-", "HERE"), ("CHECK", "POINT"), ("STATUS", ".md")))
# 手元の文書の節や章の番号（「設計」「追加文書」「勢いの文書」「beta 文書」のあとの番号）と、種類と読者の設計の呼び方
PRIVATE_SECTION = re.compile(r"(?:設計|追加文書|勢いの文書|beta 文書) ?\d+(?:\.\d+)*|種類と読者の設計")
# 作者の名前に敬称を付けた形（開発の記録の書き方。名前そのものは書かないよう、文字の番号で作る）
OWNER_NOTE = "\u5927\u8cc0" + "\u3055\u3093"


def distributed_texts():
    """配布物のテキストのファイル（相対パス, 中身）。UTF-8 として読めないもの（画像など）は除く。"""
    out = []
    for name in published_files():
        if not name.startswith(DISTRIBUTED_TOPS):
            continue
        try:
            out.append((name, (ROOT / name).read_bytes().decode("utf-8")))
        except UnicodeDecodeError:
            continue
    return out


def record_ids(text):
    masked = RECORD_ID_ALLOWED.sub(lambda match: " " * len(match.group(0)), text)
    return [match.group(0) for match in RECORD_ID.finditer(masked)]


def found_in_lines(text, finder):
    """(行番号, 当たった語) の並び。"""
    out = []
    for number, line in enumerate(text.split("\n"), 1):
        out.extend((number, word) for word in finder(line))
    return out


class DistributedNotesTest(unittest.TestCase):
    """配布物に、反証の指摘の番号の形、手元の設計の文書の名前と節の番号、作者の名前に敬称を付けた形がない。"""

    def check(self, finder):
        found = []
        for name, text in distributed_texts():
            found.extend("{}:{}: {}".format(name, number, word) for number, word in found_in_lines(text, finder))
        self.assertEqual(found, [])

    def test_no_record_ids(self):
        self.check(record_ids)

    def test_no_private_document_names(self):
        self.check(lambda line: [word for word in PRIVATE_DOC_NAMES if word in line])

    def test_no_private_section_numbers(self):
        self.check(lambda line: [match.group(0) for match in PRIVATE_SECTION.finditer(line)])

    def test_no_owner_notes(self):
        self.check(lambda line: [OWNER_NOTE] if OWNER_NOTE in line else [])

    def test_the_patterns(self):
        """見張る形と、見張らない形（ここで作った例）。"""
        for text, expected in (
                ("（R9-9、Z9、F99）", ["R9-9", "Z9", "F99"]), ("（10.9 C-99）", ["C-99"]), ("目標の D-9", ["D-9"]),
                ("G9 で足した", ["G9"]), ("W-XY-ok99 の組", ["W-XY-ok99"]), ("R9-FP9-9", ["R9-FP9-9"]),
                ("U+FF01〜U+FF5E", []), ("VS15 と VS16", []), ("Unicode License V3", []), ("COM1、LPT1", []),
                ("# noqa: E402", []), ("UTF-8、SHA-256、ISO8601、NFKC", []), ("P1対応", []), ("\\U0001f000", [])):
            with self.subTest(text=text):
                self.assertEqual(record_ids(text), expected)
        self.assertEqual([m.group(0) for m in PRIVATE_SECTION.finditer("（設計 9.9.9、追加文書 9.9、勢いの文書9章）")],
                         ["設計 9.9.9", "追加文書 9.9", "勢いの文書9"])
        self.assertEqual(list(PRIVATE_SECTION.finditer("設計の文どおり。仕様や設計が壊れる")), [])

    def test_the_check_covers_the_distributed_folders(self):
        names = [name for name, _ in distributed_texts()]
        for name in ("scripts/yomiyasu_lint.py", "skills/yomiyasu/scripts/yomiyasu_lint.py", "skills/yomiyasu/SKILL.md",
                     "references/review-points.md", "references/lists/katakana-terms.txt"):
            with self.subTest(name=name):
                self.assertIn(name, names)
        self.assertFalse(any(name.startswith("tests/") for name in names))


if __name__ == "__main__":
    unittest.main()
