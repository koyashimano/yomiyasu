"""v2.2.0: プロジェクトの用語リスト（.yomiyasu-words/ の allow.txt と flag.txt）を、lint で確かめる。

文はすべて合成の文。一覧のフォルダは一時フォルダの中にだけ作る（リポジトリの中には置かない。試験の多くはリポジトリの
中で動き、一覧があると context の固定が崩れる）。
"""
from pathlib import Path
from unittest import mock
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402

LINT = SCRIPTS / "yomiyasu_lint.py"

WORD_KEYS = ["path", "allow_lines", "flag_lines", "allow_sha256", "flag_sha256"]
ALLOW_RULES = ["ai_phrase", "calque", "katakana_term", "metaphor_label", "metaphor_verb", "project_term", "renyo_noun",
               "slop_vocabulary", "translated_term"]
# 既存の3つの規則に当たる合成の文（v2.1.3 の lint が warn を出す）
SLOP_LINE = "この方針は思考のOSとして働きます。"
METAPHOR_LINE = "このままでは、夜間の処理が静かに壊れる。"
TRANSLATED_LINE = "毎月、版を上げて配布します。"
PLAIN_LINE = "担当者は手順書を読み、作業の記録を残しました。"


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def run(command, cwd, env=None, stdin=None):
    return subprocess.run([sys.executable, "-B"] + [str(part) for part in command], cwd=str(cwd), env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          stdin=subprocess.DEVNULL if stdin is None else stdin)


class FolderCase(unittest.TestCase):
    """git の外の一時フォルダ（上に .git がない）で動かす。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(os.path.realpath(self.tmp.name))
        self.env = dict(os.environ, HOME=str(self.root))
        # 一時フォルダの上に .git がないこと（git の外の場合の前提）
        current = self.root
        while current != current.parent:
            self.assertFalse((current / ".git").exists(), current)
            current = current.parent

    def words(self, folder=None, allow=None, flag=None):
        folder = Path(folder) if folder is not None else self.root / ".yomiyasu-words"
        folder.mkdir(parents=True, exist_ok=True)
        if allow is not None:
            write(folder / "allow.txt", allow)
        if flag is not None:
            write(folder / "flag.txt", flag)
        return folder

    def lint(self, *args, cwd=None):
        return run([LINT] + list(args), cwd or self.root, self.env)

    def lint_json(self, *args, cwd=None):
        process = self.lint("--json", *args, cwd=cwd)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)


class ReaderTest(FolderCase):
    """共有の読み手（markdown_visibility）の読み方。"""

    def test_crlf_bom_cr_comments_blank_lines_and_spaces(self):
        allow = b"\xef\xbb\xbf# \xe3\x82\xb3\xe3\x83\xa1\xe3\x83\xb3\xe3\x83\x88\r\n" + "依存先\r\n\r\n  入口  \r\n\t# 字下げのコメント\r\n".encode("utf-8")
        flag = "スプリント\r締め日\r\r　全角の空白　\r".encode("utf-8")
        folder = self.words(allow=allow, flag=flag)
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual(words["allow"], ("依存先", "入口"))
        self.assertEqual(words["flag"], ("スプリント", "締め日", "全角の空白"))
        self.assertEqual((words["allow_lines"], words["flag_lines"]), (2, 3))
        self.assertEqual(words["allow_sha256"], hashlib.sha256(allow).hexdigest())
        self.assertEqual(words["flag_sha256"], hashlib.sha256(flag).hexdigest())
        self.assertEqual(markdown_visibility.words_context(words),
                         {"path": str(folder), "allow_lines": 2, "flag_lines": 3,
                          "allow_sha256": hashlib.sha256(allow).hexdigest(),
                          "flag_sha256": hashlib.sha256(flag).hexdigest()})
        self.assertEqual(list(markdown_visibility.words_context(words)), WORD_KEYS)

    def test_duplicates_are_counted_as_lines(self):
        folder = self.words(allow="入口\n入口\n")
        self.assertEqual(markdown_visibility.load_words(str(folder))["allow_lines"], 2)

    def test_one_file_only(self):
        folder = self.words(flag="締め日\n")
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual((words["allow"], words["allow_lines"], words["allow_sha256"]), ((), 0, None))
        self.assertEqual(words["flag"], ("締め日",))

    def test_empty_files_are_used(self):
        """ファイルがあれば（中身が空やコメントだけでも）一覧を使ったものとする。"""
        folder = self.words(allow=b"", flag="# 見直す語\n")
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual((words["allow_lines"], words["flag_lines"]), (0, 0))
        self.assertEqual(words["allow_sha256"], hashlib.sha256(b"").hexdigest())

    def test_folder_without_files_is_no_list(self):
        folder = self.words()
        self.assertIsNone(markdown_visibility.load_words(str(folder)))
        self.assertIsNone(markdown_visibility.resolve_words(str(self.root)))

    def test_not_utf8_names_the_file_and_line(self):
        for data, line in ((b"\xff\n", 1), ("入口\n締め日\n".encode("utf-8") + b"\x82\xa0\n", 3),
                           ("入口\r\n締め日\r\n".encode("utf-8") + b"\xe3\x81\n", 3), (b"a\rb\r\xff", 3)):
            with self.subTest(data=data):
                folder = self.words(allow=data)
                with self.assertRaises(markdown_visibility.WordsError) as raised:
                    markdown_visibility.load_words(str(folder))
                self.assertEqual(str(raised.exception), "Error opening file {}: UTF-8 として読めません（{}行目）".format(
                    os.path.join(str(folder), "allow.txt"), line))

    def test_line_limit(self):
        folder = self.words(flag="語\n" * 10000)
        self.assertEqual(markdown_visibility.load_words(str(folder))["flag_lines"], 10000)
        # 数えるのはファイルの行（コメントと空の行も数える）
        write(folder / "flag.txt", "#\n" * 10000 + "語\n")
        with self.assertRaises(markdown_visibility.WordsError) as raised:
            markdown_visibility.load_words(str(folder))
        self.assertEqual(str(raised.exception), "Error opening file {}: 行が多すぎます（10001行目。10,000行までです）".format(
            os.path.join(str(folder), "flag.txt")))

    def test_unreadable_file_is_an_error(self):
        folder = self.words()
        (folder / "allow.txt").mkdir()
        with self.assertRaises(markdown_visibility.WordsError) as raised:
            markdown_visibility.load_words(str(folder))
        self.assertTrue(str(raised.exception).startswith("Error opening file {}: ファイルを開けません（".format(
            os.path.join(str(folder), "allow.txt"))), raised.exception)

    def test_search_outside_git_uses_the_working_directory_only(self):
        self.words(allow="入口\n")
        sub = self.root / "sub"
        sub.mkdir()
        self.assertEqual(markdown_visibility.find_words_folder(str(self.root)), str(self.root / ".yomiyasu-words"))
        # git の外では、上のフォルダの一覧は探さない
        self.assertIsNone(markdown_visibility.find_words_folder(str(sub)))

    def test_explicit_folder_normalizes_dotdot_without_following_symlinks(self) -> None:
        folder = self.words(self.root / "lists", allow="入口\n")
        target = self.root / "elsewhere" / "child"
        target.mkdir(parents=True)
        link = self.root / "alias"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")
        selected = markdown_visibility.find_words_folder(str(self.root), "alias/../lists")
        self.assertEqual(selected, str(folder))

    @unittest.skipIf(os.name == "nt", "POSIX の権限で実際に読み取りを拒否する")
    def test_explicit_folder_below_unreadable_directory_is_a_words_error(self) -> None:
        denied = self.root / "denied"
        denied.mkdir()
        denied.chmod(0)
        try:
            try:
                (denied / "probe").write_bytes(b"permission check")
            except PermissionError:
                pass
            else:
                self.skipTest("この利用者には chmod(0) の拒否を適用できません")
            with self.assertRaises(markdown_visibility.WordsError):
                markdown_visibility.find_words_folder(str(self.root), str(denied / "words"))
            self.assertIsNone(markdown_visibility.find_words_folder(str(denied)))
        finally:
            denied.chmod(0o700)

    def test_search_inside_git_goes_to_the_first_git_folder(self):
        for kind in ("folder", "file"):
            with self.subTest(kind=kind):
                project = self.root / kind
                if kind == "folder":
                    (project / ".git").mkdir(parents=True)
                else:
                    write(project / ".git", "gitdir: /elsewhere/.git/worktrees/x\n")
                self.words(project / ".yomiyasu-words", allow="入口\n")
                deep = project / "docs" / "guide"
                deep.mkdir(parents=True)
                self.assertEqual(markdown_visibility.find_words_folder(str(deep)), str(project / ".yomiyasu-words"))
                # 作業ディレクトリの一覧は、git の中では使わない（git の最上位だけ）
                self.words(deep / ".yomiyasu-words", allow="締め日\n")
                self.assertEqual(markdown_visibility.find_words_folder(str(deep)), str(project / ".yomiyasu-words"))
                # git の最上位に一覧がなければ、一覧なし
                inner = project / "docs" / "inner"
                (inner / ".git").mkdir(parents=True)
                self.assertIsNone(markdown_visibility.find_words_folder(str(inner)))

    def test_state_folder_is_not_searched(self):
        self.words(self.root / ".yomiyasu" / ".yomiyasu-words", allow="入口\n")
        self.assertIsNone(markdown_visibility.find_words_folder(str(self.root)))

    def test_option_folder(self):
        other = self.words(self.root / "lists", allow="入口\n")
        self.assertEqual(markdown_visibility.find_words_folder(str(self.root), "lists"), str(other))
        self.assertEqual(markdown_visibility.find_words_folder(None, str(other)), str(other))
        for value, reason in (("missing", "フォルダがありません"), ("lists/allow.txt", "フォルダではありません")):
            with self.assertRaises(markdown_visibility.WordsError) as raised:
                markdown_visibility.find_words_folder(str(self.root), value)
            self.assertEqual(str(raised.exception), "Error opening folder {}: --words の{}".format(value, reason))
        with self.assertRaises(markdown_visibility.WordsError):
            markdown_visibility.find_words_folder(str(self.root), " ")
        with self.assertRaises(markdown_visibility.WordsError):
            markdown_visibility.find_words_folder(None, "lists")

    def test_option_home(self):
        self.words(self.root / "lists", allow="入口\n")
        # Windows の ~ は USERPROFILE を読むので、HOME と一緒に差し替える
        with mock.patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}):
            self.assertEqual(markdown_visibility.find_words_folder("/", "~/lists"), str(self.root / "lists"))

    def test_disabled(self):
        self.words(allow="入口\n")
        self.assertIsNone(markdown_visibility.resolve_words(str(self.root), disabled=True))
        self.assertIsNotNone(markdown_visibility.resolve_words(str(self.root)))


class LintAllowTest(FolderCase):
    """allow.txt で既存の3つの規則と新しい規則の候補を外す。"""

    def words_value(self, allow="", flag=None):
        return markdown_visibility.load_words(str(self.words(allow=allow, flag=flag)))

    def test_existing_three_rules(self):
        text = "\n\n".join((SLOP_LINE, METAPHOR_LINE, TRANSLATED_LINE, PLAIN_LINE)) + "\n"
        plain = yomiyasu_lint.lint_text(text)
        self.assertEqual([f["rule"] for f in plain["findings"]], ["slop_vocabulary", "metaphor_verb", "translated_term"])
        cases = (("思考のOS", "slop_vocabulary"), ("〜のOS", "slop_vocabulary"), ("静かに壊れる", "metaphor_verb"),
                 ("静かに壊れ", "metaphor_verb"), ("版", "translated_term"), ("版を上げ", "translated_term"))
        for word, rule in cases:
            with self.subTest(word=word):
                result = yomiyasu_lint.lint_text(text, words=self.words_value(allow=word + "\n"))
                self.assertEqual([f["rule"] for f in result["findings"]],
                                 [f["rule"] for f in plain["findings"] if f["rule"] != rule])
                removed = result["context"]["words"]["allow_removed"]
                self.assertEqual(list(removed), ALLOW_RULES)
                self.assertEqual(removed, dict((name, int(name == rule)) for name in ALLOW_RULES))
                # 件数と点数は外したあとに数える
                self.assertEqual(result["candidate_count"], 2)
                self.assertEqual(result["counts"], {"error": 0, "warn": 2, "info": 0})
                self.assertGreater(result["rule_penalty_score"], plain["rule_penalty_score"])

    def test_every_slop_word_can_be_allowed(self):
        """組み込みの語のどれを allow に書いても、その語の候補（message にその語がある候補）が外れる。"""
        for word in yomiyasu_lint.SLOP_WORDS:
            with self.subTest(word=word):
                text = "この文では{}を使います。\n".format(word)
                named = "「{}」".format(word)
                plain = [f for f in yomiyasu_lint.lint_text(text)["findings"] if named in f["message"]]
                self.assertEqual(len(plain), 1)
                words = {"path": "/x", "allow": (word,), "flag": (), "allow_lines": 1, "flag_lines": 0,
                         "allow_sha256": "0" * 64, "flag_sha256": None}
                result = yomiyasu_lint.lint_text(text, words=words)
                self.assertEqual([f for f in result["findings"] if named in f["message"]], [])
                self.assertEqual(result["context"]["words"]["allow_removed"]["slop_vocabulary"], 1)

    def test_partial_or_other_words_do_not_remove(self):
        text = SLOP_LINE + "\n"
        for word in ("OS", "思考", "壊れる", "思考のOSとして"):
            with self.subTest(word=word):
                result = yomiyasu_lint.lint_text(text, words=self.words_value(allow=word + "\n"))
                self.assertEqual([f["rule"] for f in result["findings"]], ["slop_vocabulary"])
                self.assertEqual(sum(result["context"]["words"]["allow_removed"].values()), 0)

    def test_new_rules_with_words_field(self):
        """新しい規則（担当 A1 が _words を入れる）は、_words の語で外す。7つの規則の外の規則は外さない。"""
        def findings(analysis):
            return [{"rule": rule, "line": 1, "severity": "info", "message": "合成の候補です。", "snippet": PLAIN_LINE,
                     "_words": ("手順書",)}
                    for rule in ("calque", "metaphor_label", "katakana_term", "say_hedge", "thin_evaluation")]
        with mock.patch.object(yomiyasu_lint, "_v220_word_findings", findings):
            plain = yomiyasu_lint.lint_text(PLAIN_LINE + "\n")
            result = yomiyasu_lint.lint_text(PLAIN_LINE + "\n", words=self.words_value(allow="手順書\n"))
            other = yomiyasu_lint.lint_text(PLAIN_LINE + "\n", words=self.words_value(allow="記録\n"))
        self.assertEqual(plain["candidate_count"], 5)
        self.assertEqual([f["rule"] for f in result["findings"]], ["say_hedge", "thin_evaluation"])
        self.assertEqual(result["context"]["words"]["allow_removed"],
                         {"ai_phrase": 0, "calque": 1, "katakana_term": 1, "metaphor_label": 1, "metaphor_verb": 0,
                          "project_term": 0, "renyo_noun": 0, "slop_vocabulary": 0, "translated_term": 0})
        self.assertEqual(result["counts"]["info"], 2)
        self.assertEqual(other["candidate_count"], 5)
        self.assertNotIn("_words", json.dumps(result))

    def test_allow_is_applied_after_doc_type(self):
        """種類で外した候補は allow の件数に数えない（種類で外す処理が先）。"""
        def findings(analysis):
            return [{"rule": "metaphor_label", "line": 1, "severity": "info", "message": "合成の候補です。",
                     "snippet": PLAIN_LINE, "_words": ("手順書",)}]
        with mock.patch.object(yomiyasu_lint, "_v220_word_findings", findings), \
                mock.patch.dict(yomiyasu_lint.DOC_TYPE_SKIP_RULES, {"essay": ("metaphor_label",)}):
            result = yomiyasu_lint.lint_text(PLAIN_LINE + "\n", doc_type="essay", words=self.words_value(allow="手順書\n"))
        self.assertEqual(result["context"]["skipped_by_doc_type"], {"metaphor_label": 1})
        self.assertEqual(result["context"]["words"]["allow_removed"]["metaphor_label"], 0)

    def test_no_list_keeps_the_output(self):
        text = "\n\n".join((SLOP_LINE, METAPHOR_LINE, TRANSLATED_LINE)) + "\n"
        result = yomiyasu_lint.lint_text(text)
        self.assertEqual(list(result["context"]), ["doc_type", "reader", "skipped_by_doc_type"])
        self.assertEqual(result, yomiyasu_lint.lint_text(text, words=None))
        self.assertNotIn("用語リスト", yomiyasu_lint.render_report(result))


class ProjectTermTest(FolderCase):
    def lint_with(self, text, flag, allow=None):
        words = markdown_visibility.load_words(str(self.words(allow=allow, flag=flag)))
        return yomiyasu_lint.lint_text(text, words=words)

    def test_one_finding_per_line_with_the_words(self):
        text = ("# スプリントの決め方\n\n"
                # 3.3.0: pause_comma を種類なしでも当てるので、この行の「次のスプリントでは、」の読点を外した
                "次のスプリントでは締め日の名前とスプリントの日付を決めます。\n\n"
                "| 項目 | 期日 |\n|---|---|\n| スプリント | 月末 |\n\n"
                "- 締め日を一つにまとめる\n")
        result = self.lint_with(text, "スプリント\n締め日\n")
        found = [(f["line"], f["severity"]) for f in result["findings"] if f["rule"] == "project_term"]
        self.assertEqual(found, [(1, "info"), (3, "info"), (7, "info"), (9, "info")])
        finding = [f for f in result["findings"] if f["line"] == 3][0]
        self.assertEqual(finding["message"],
                         "用語リスト（flag.txt）の言葉（スプリント、締め日）の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。")
        self.assertEqual(finding["snippet"], "次のスプリントでは締め日の名前とスプリントの日付を決めます。")
        self.assertEqual(sorted(finding), ["line", "message", "rule", "severity", "snippet"])
        # 点数に入れない
        self.assertEqual(result["rule_penalty_score"], 100)

    def test_words_field_holds_the_line_words(self):
        analysis = markdown_visibility.analyze_markdown("締め日とスプリントと締め日。\n")
        words = {"flag": ("スプリント", "締め日", "日付"), "allow": ()}
        found = yomiyasu_lint._project_term_findings(analysis, words)
        self.assertEqual([f["_words"] for f in found], [("締め日", "スプリント")])

    def test_hidden_places_are_not_counted(self):
        text = ("```\nスプリント = 1\n```\n\n"
                "`スプリント` を設定します。\n\n"
                "> スプリントを決めました。\n\n"
                "彼は「スプリント」と言いました。\n\n"
                "詳しくは https://example.com/スプリント を見ます。\n\n"
                "<div>スプリント</div>\n\n"
                "変数 milestone_id と obj.milestone と path/milestone を使います。\n")
        result = self.lint_with(text, "スプリント\nmilestone\n")
        self.assertEqual([f["line"] for f in result["findings"] if f["rule"] == "project_term"], [])
        result = self.lint_with("次の milestone を決めます。Milestone ではありません。\n", "milestone\n")
        self.assertEqual([f["line"] for f in result["findings"] if f["rule"] == "project_term"], [1])

    def test_frontmatter_is_not_counted(self):
        result = self.lint_with("---\ntitle: スプリント\n---\n\n本文です。\n", "スプリント\n")
        self.assertEqual([f for f in result["findings"] if f["rule"] == "project_term"], [])

    def test_allow_wins_over_flag(self):
        result = self.lint_with("次のスプリントを決めます。\n", "スプリント\n", allow="スプリント\n")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["context"]["words"]["allow_removed"]["project_term"], 1)

    def test_doc_type_does_not_skip(self):
        words = markdown_visibility.load_words(str(self.words(flag="スプリント\n")))
        for doc_type in [row[0] for row in yomiyasu_lint.DOC_TYPES]:
            with self.subTest(doc_type=doc_type):
                result = yomiyasu_lint.lint_text("次のスプリントを決めます。\n", doc_type=doc_type, words=words)
                self.assertEqual([f["rule"] for f in result["findings"]], ["project_term"])


class LintCliTest(FolderCase):
    def test_json_context_words_and_human_line(self):
        folder = self.words(allow="静かに壊れる\n", flag="手順書\n")
        draft = write(self.root / "a.md", METAPHOR_LINE + "\n\n" + PLAIN_LINE + "\n")
        result = self.lint_json(str(draft))
        words = result["context"]["words"]
        self.assertEqual(list(result["context"]), ["doc_type", "reader", "skipped_by_doc_type", "words"])
        self.assertEqual(list(words), WORD_KEYS + ["allow_removed"])
        self.assertEqual(words["path"], str(folder))
        self.assertEqual((words["allow_lines"], words["flag_lines"]), (1, 1))
        self.assertEqual(words["allow_removed"]["metaphor_verb"], 1)
        self.assertEqual([f["rule"] for f in result["findings"]], ["project_term"])
        process = self.lint(str(draft))
        lines = process.stdout.splitlines()
        self.assertEqual(lines[3], "用語リスト: {}（allow 1語、flag 1語）。allow で外した候補 1件。".format(folder))
        process = self.lint("--doc-type", "article", str(draft))
        lines = process.stdout.splitlines()
        self.assertTrue(lines[3].startswith("文書の種類: 技術記事（article）"), lines[3])
        self.assertTrue(lines[4].startswith("用語リスト: "), lines[4])

    def test_no_words_and_explicit_folder(self):
        self.words(allow="静かに壊れる\n")
        other = self.words(self.root / "lists", flag="手順書\n")
        draft = write(self.root / "a.md", METAPHOR_LINE + "\n\n" + PLAIN_LINE + "\n")
        plain = self.lint_json("--no-words", str(draft))
        self.assertNotIn("words", plain["context"])
        self.assertEqual([f["rule"] for f in plain["findings"]], ["metaphor_verb"])
        self.assertNotIn("用語リスト", self.lint("--no-words", str(draft)).stdout)
        chosen = self.lint_json("--words", "lists", str(draft))
        self.assertEqual(chosen["context"]["words"]["path"], str(other))
        self.assertEqual([f["rule"] for f in chosen["findings"]], ["metaphor_verb", "project_term"])

    def test_stdin_uses_the_list(self):
        self.words(flag="手順書\n")
        process = subprocess.run([sys.executable, "-B", str(LINT), "--json"], cwd=str(self.root), env=self.env,
                                 input=(PLAIN_LINE + "\n").encode("utf-8"), capture_output=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("words", json.loads(process.stdout.decode("utf-8"))["context"])

    def test_errors_exit_2_before_reading_input(self):
        draft = write(self.root / "a.md", PLAIN_LINE + "\n")
        folder = self.words(allow=b"\xe5\x85\xa5\xe5\x8f\xa3\n\xff\n")
        cases = (
            (["--words", "missing", str(draft)], "Error opening folder missing: --words のフォルダがありません\n"),
            ([str(draft)], "Error opening file {}: UTF-8 として読めません（2行目）\n".format(folder / "allow.txt")),
            # 入力のファイルがなくても、一覧の誤りを先に出す
            (["missing.md"], "Error opening file {}: UTF-8 として読めません（2行目）\n".format(folder / "allow.txt")),
        )
        for args, error in cases:
            with self.subTest(args=args):
                process = self.lint(*args)
                self.assertEqual((process.returncode, process.stdout, process.stderr), (2, "", error))
        process = self.lint("--words", str(folder), "--no-words", str(draft))
        self.assertEqual((process.returncode, process.stdout), (2, ""))
        self.assertIn("yomiyasu_lint.py: error: --words と --no-words は一緒に使えません\n", process.stderr)
        self.assertIn("引数の誤りです。", process.stderr)
        write(folder / "allow.txt", "語\n" * 10001)
        process = self.lint(str(draft))
        self.assertEqual((process.returncode, process.stderr), (
            2, "Error opening file {}: 行が多すぎます（10001行目。10,000行までです）\n".format(folder / "allow.txt")))
        # --no-words なら読めない一覧も読まない
        self.assertEqual(self.lint("--no-words", str(draft)).returncode, 0)

    def test_help_and_exit_codes(self):
        help_text = "".join(yomiyasu_lint._build_parser().format_help().split())
        for text in ("--wordsフォルダ", "--no-words", ".yomiyasu-words/", "project_term（info）"):
            self.assertIn(text, help_text)
        self.assertIn("用語リストを読めない", yomiyasu_lint._EXIT_CODES)
        usage = yomiyasu_lint._build_parser().format_usage()
        self.assertIn("[--words フォルダ]", usage)
        self.assertIn("[--no-words]", usage)


if __name__ == "__main__":
    unittest.main()
