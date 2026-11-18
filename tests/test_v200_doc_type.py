#!/usr/bin/env python3
"""v2.0.0（G7）: lint の文書の種類（--doc-type）と読者（--reader）。

期待値は種類と読者の設計の9章（道具のオプション）と 10.1 の表（A〜E）、末尾の追記（2026-10-13 19時。種類に
formal を足して9つにする。lint で外す規則はなし）と、あとで足した promo（10個目。lint で emoji_prohibited を外す。
2026-10-14 朝の作者の判断で fragment_run も外す）から取った。文はすべてこのファイルで作った合成の文。コーパスは読むだけ。

- 指定しないときの出力（9章の不変の条件、10.1 の A）は、tests/fixtures/g7_unchanged_outputs.json と照らす。
  lint の人が読む出力、終了コード、標準エラー（と、context を除いた JSON）を、コーパスの全ファイルで比べる。
  - lint の行は G7 を入れる前の作業ツリー（45a5885 に check の固めを入れたもの）の出力で、作り直していない。
    指定しないときの lint の出力が G7 の前と1字も違わないことを見る。ただし 2.2.0 で、新しい info の規則の候補が出る
    1本の行は作り直した（fixture の updates）。
  lint の出力をわざと変えたときは、unchanged_lint() の値で行を作り直し、作り直した理由と、終了コードが変わったファイルを
  updates と報告に書く（条件をゆるめて通さない）。
  fixture の説明の欄（description、generated_by、source_commit、updates）には、手元の記録と道具の名前を書かない
  （test_v200_fix_round3.PrivatePathTest が見張る）。
- SkillFilesTest（10.1 の C3、C4 と C5 の SKILL.md の部分）は、SKILL.md と references を入れる段までは失敗する。
"""

from pathlib import Path
from unittest import mock
import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CORPUS = ROOT / "tests" / "corpus"
FIXTURES = ROOT / "tests" / "fixtures"
UNCHANGED = FIXTURES / "g7_unchanged_outputs.json"
PACKAGE = ROOT / "skills" / "yomiyasu"
sys.path.insert(0, str(SCRIPTS))

import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
from portable import paced_limit, timing_clock  # noqa: E402


# ---- 9.1 と追記: 値、名前、外す規則 ----

# 既存10種類の互換性と references の試験はこの集合を維持する。mail/paper は test_v200_mail_paper.py。
# diff の詰め（目標の D-5、勢いの文書2章）: promo（紹介記事・宣伝文）を足して10にした
DOC_TYPE_VALUES = ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal", "promo")
DOC_TYPE_NAMES = {"pr": "PR説明", "article": "技術記事", "incident": "障害報告", "proposal": "提案書", "minutes": "議事録",
                  "manual": "マニュアル", "slides": "スライド", "essay": "エッセイ・小説",
                  "formal": "公用文、規程、契約書、仕様書", "promo": "紹介記事・宣伝文"}
DOC_TYPE_DOMAINS = {"pr": ("business.md",), "article": ("tech.md",), "incident": ("business.md",),
                    "proposal": ("business.md",), "minutes": ("business.md",), "manual": ("tech.md", "business.md"),
                    "slides": ("tech.md", "business.md"), "essay": ("essay.md",), "formal": ("business.md", "tech.md"),
                    "promo": ("essay.md", "business.md")}
READER_VALUES = ("expert", "informed", "general")
READER_NAMES = {"expert": "同じ分野の専門家", "informed": "分野は違うが技術に詳しい人", "general": "専門知識のない人"}
SKIP_RULES = {
    "pr": ("excess_list",),
    "article": (),
    "incident": ("excess_list",),
    "proposal": (),
    "minutes": ("bold_label_list", "excess_list", "sentence_end_repetition"),
    "manual": ("excess_list",),
    # スライドの箇条で強調として選ぶ「〜のは、A、B、C。」（cleft_list_ending）も外す。
    # 2.2.0: 主語も目的語もない動詞を並べる型（bare_verb_chain）も外す
    "slides": ("bare_verb_chain", "bold_label_list", "cleft_list_ending", "count_declaration", "excess_list",
               "short_summary_heading"),
    # 2.2.0: 見出しの短い比喩（metaphor_label）と動詞を並べる型（bare_verb_chain）を外す
    "essay": ("bare_verb_chain", "metaphor_label"),
    "formal": (),
    # D-5: promo では書き手の絵文字を残す（勢いの検査は絵文字が減ると候補にするので、lint の絵文字の候補と食い違わせない）。
    # diff の詰めで測って決めた。fragment_run（「安い。うまい。早い。」の型）も
    # 外す（作者の判断、2026-10-14 朝。紹介記事・宣伝文では評価の語を短く重ねる型も勢いとして残す）
    # 2.2.0: essay と同じく metaphor_label と bare_verb_chain も外す
    "promo": ("bare_verb_chain", "emoji_prohibited", "fragment_run", "metaphor_label"),
}
# 5.3「外さない規則と理由」。どの種類でも外さない。ただし fragment_run は promo だけ外す（作者の判断、2026-10-14 朝。
# 5.3 の理由はスライドの話で、紹介記事・宣伝文では評価の語を短く重ねる型を勢いとして残すと決めた）
# 2.2.0: 台詞・脚本（script）でも、台詞で普通に出る短い文の重ねとして fragment_run を外す
NEVER_SKIPPED_EXCEPT = {"fragment_run": ("promo", "script")}
NEVER_SKIPPED = ("bold_not_rendered", "fragment_run", "meta_intro", "metaphor_verb", "trailing_colon", "excess_bold",
                 "dash_list_ending", "dash_insertion", "dash_decoration")

# 2.2.0: 台詞・脚本（script）を末尾に足した
NEW_DOC_TYPES = (("mail", "メール・チャット", ("business.md",)), ("paper", "論文・研究レポート", ("tech.md",)),
                 ("script", "台詞・脚本", ("essay.md",)))
NEW_SKIP_RULES = {"mail": ("emoji_prohibited",), "paper": (),
                  "script": ("bare_verb_chain", "fragment_run", "metaphor_label", "sentence_end_repetition")}
DOC_TYPE_CHOICES = "、".join("{}（{}）".format(value, DOC_TYPE_NAMES[value]) for value in DOC_TYPE_VALUES) + "、" + "、".join("{}（{}）".format(row[0], row[1]) for row in NEW_DOC_TYPES)
READER_CHOICES = "、".join("{}（{}）".format(value, READER_NAMES[value]) for value in READER_VALUES)
# 9.1 の文どおり、値の一覧の閉じ括弧と「です」の間に空白を入れない（反証レビュー spec 6）
DOC_TYPE_ERROR = "--doc-type に使えない値です: {}。使えるのは " + DOC_TYPE_CHOICES + "です。"
READER_ERROR = "--reader に使えない値です: {}。使えるのは " + READER_CHOICES + "です。"
# 9.6 ヘルプの文（formal と promo を足した値の並び）
LINT_DOC_TYPE_HELP = ("文書の種類。指定すると、その種類で普通な書き方を候補にする規則（下の一覧）の候補を外し、外した件数を出します。"
                      "外した候補の中身は、指定せずに実行すると見られます。省くと、すべての規則を当てます（今までどおり）。"
                      "値: " + DOC_TYPE_CHOICES + "。")
LINT_READER_HELP = "想定する読者の知識。表示と JSON に残すだけで、候補は変えません。値: " + READER_CHOICES + "。"
LINT_HELP_LIST = "\n".join([
    "文書の種類ごとに外す規則（--doc-type）:",
    "  pr        excess_list",
    "  article   なし",
    "  incident  excess_list",
    "  proposal  なし",
    "  minutes   bold_label_list、excess_list、sentence_end_repetition",
    "  manual    excess_list",
    "  slides    bare_verb_chain、bold_label_list、cleft_list_ending、count_declaration、excess_list、short_summary_heading",
    "  essay     bare_verb_chain、metaphor_label",
    "  formal    なし",
    "  promo     bare_verb_chain、emoji_prohibited、fragment_run、metaphor_label",
    "  mail      emoji_prohibited",
    "  paper     なし",
    "  script    bare_verb_chain、fragment_run、metaphor_label、sentence_end_repetition",
    "mail は meta_filler の返信・結びの5型だけも外します（ご質問ありがとうございます、必要なら次に〜します、いかがでしたでしょうか、ぜひ〜してみてください、参考になれば幸いです等）。宛名・挨拶・署名を削る専用規則はありません。paper は慎重表現を削る規則がないため除外なし。",
    "種類を指定したときだけ当てる規則: pause_comma（promo、script を除く11種類。種類を指定しないときは出しません）",
    "種類を指定したときだけ当てる規則: dialogue_period（script だけ。種類を指定しないときは出しません）",
    "種類を指定したときだけ当てる規則: narrative_density（essay だけ。種類を指定しないときは出しません）",
    "種類を指定したときだけ当てる規則: slide_comma（slides だけ。種類を指定しないときは出しません）",
    "外した候補は、見直し候補の件数と --strict、--fail-on の判定に入れません。",
])
# 9.3 と 9.4 の1行
LINT_NO_SKIP = "この種類で外す規則はありません。"
LINT_READER_NOTE = "読者では候補を変えていません。"
LINT_HEADER = [
    "表現・書式の検査を実行しました。",
    "見直し候補: {}件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
]

# ---- 合成の文: 外す規則ごとに、その規則だけに当たる文書（10.1 の B2、B4、B5）----

EXCESS_LIST_ONLY = ("今週の作業の記録を残します。担当者は各自の作業を確認してから、来週の予定を決めてください。\n\n"
                    + "".join("- 第{}工程の部品を棚から出して、検品の台に並べた上で数を数える。\n".format(number)
                              for number in range(1, 10)))
SENTENCE_END_ONLY = "今日は雨です。明日は晴れです。週末は曇りです。\n"
BOLD_LABEL_ONLY = "- **日時**: 10月1日\n- **場所**: 本社3階\n- **担当**: 田中\n"
COUNT_DECLARATION_ONLY = "ポイントは3つです。順に説明します。\n"
SUMMARY_HEADING_ONLY = "# 報告\n\n作業は終わりました。\n\n## まとめ\n\n作業は予定どおり終わりました。\n"
BOLD_ERROR_ONLY = "これは**「重要」**です。\n"
EMOJI_ONLY = "新作のケーキが並びました\U0001F370\n"
FRAGMENT_RUN_ONLY = "安い。うまい。早い。\n"
CLEFT_LIST_ONLY = "書き換えの中で変動したのは、画面、帳票、通知。\n"
RULE_SAMPLES = {
    "emoji_prohibited": EMOJI_ONLY,
    "fragment_run": FRAGMENT_RUN_ONLY,
    "cleft_list_ending": CLEFT_LIST_ONLY,
    "excess_list": EXCESS_LIST_ONLY,
    "sentence_end_repetition": SENTENCE_END_ONLY,
    "bold_label_list": BOLD_LABEL_ONLY,
    "count_declaration": COUNT_DECLARATION_ONLY,
    "short_summary_heading": SUMMARY_HEADING_ONLY,
}
# 2.2.0 の規則で、表で外すもの（B2 で候補を外から入れて確かめる）
INJECTED_V220_RULES = ("bare_verb_chain", "metaphor_label")
# スライドの例: bold_label_list と short_summary_heading（外す）と、emoji_prohibited（外さない warn）に当たる
SLIDES_SAMPLE = ("# 新しい検索の仕組み\n\n- **対象**: 社内の文書\n- **期間**: 10月から\n- **担当**: 検索チーム\n\n"
                 "## まとめ\n\n検索が速くなります\U0001F600\n")
SLIDES_LINE = ("文書の種類: スライド（slides）、読者: 指定なし。種類に合わせて外した候補 2件（bare_verb_chain 0件、"
               "bold_label_list 1件、cleft_list_ending 0件、count_declaration 0件、excess_list 0件、"
               "short_summary_heading 1件）。")

# 指示書2.2の3組（合成の文）
PAIRS_22 = (("田中が佐藤を承認した。\n", "佐藤が田中を承認した。\n"),
            ("保存期間は3日です。\n", "保存期間は30日です。\n"),
            ("データを保存します。\n", "データを保存しません。\n"))


# ---- 補助 ----

def call(main, argv, stdin=None):
    """main(argv) をプロセスの中で動かし、(終了コード, 標準出力, 標準エラー) を返す。stdin はバイト列。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "stdout", out))
        stack.enter_context(mock.patch.object(sys, "stderr", err))
        if stdin is not None:
            stack.enter_context(mock.patch.object(
                sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")))
        try:
            code = main([str(item) for item in argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def corpus_files():
    """tests/corpus の .md（コーパスのフォルダからの相対パス、/ 区切り）。"""
    return sorted(path.relative_to(CORPUS).as_posix() for path in CORPUS.rglob("*.md"))


def _fixture_tool_version():
    """fixture を作ったときの版（目標の D-3 で版の文字列を 2.0.0-beta に変えたので、比べるときに読み替える）。"""
    path = FIXTURES / "g7_unchanged_outputs.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("tool_version")
    except (OSError, ValueError):
        return None


def _digest(*parts):
    """出力をつないだものの SHA-256 の先頭16字。今の版の文字列は、fixture を作ったときの版に読み替えてから数える
    （版の文字列を変えただけで、G7 の不変の条件の試験が落ちないように。出力のほかの字はそのまま比べる）。"""
    data = "\x00".join(str(part) for part in parts)
    current, recorded = yomiyasu_lint.__version__, _fixture_tool_version()
    if recorded and current != recorded:
        data = data.replace(current, recorded)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _without_context(text, indent):
    """JSON の文字列から context のキーを除き、同じ形で書き直す（G7 の前の JSON と比べるため）。"""
    value = json.loads(text)
    value.pop("context", None)
    return json.dumps(value, ensure_ascii=True, indent=indent)


def unchanged_lint():
    """lint の出力の要約。キーはコーパスの相対パス。"""
    rows = {}
    for relative in corpus_files():
        path = str(CORPUS / relative)
        data = (CORPUS / relative).read_bytes()
        row = {}
        for name, argv in (("plain", [path]), ("strict", ["--strict", path]), ("fail_error", ["--fail-on", "error", path])):
            row[name] = _digest(*call(yomiyasu_lint.main, argv))
        code, out, err = call(yomiyasu_lint.main, ["--json", path])
        row["json"] = _digest(code, _without_context(out, 2), err)
        row["stdin"] = _digest(*call(yomiyasu_lint.main, [], stdin=data))
        rows[relative] = row
    return rows


class DocTypeCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-doc-type-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        # 3.0.0: lint は作業フォルダの外のファイルを読まないので、ファイルを置く一時フォルダで動かす
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(str(self.root))

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def lint(self, *argv, stdin=None):
        return call(yomiyasu_lint.main, argv, stdin)


# ---- A. 指定しないときは変わらない ----

class UnchangedOutputTest(unittest.TestCase):
    """9章の不変の条件: 指定しないときの lint の人が読む出力、終了コード、標準エラーが fixture と1字も違わない。
    lint は G7 の前の出力と照らす（このファイルの冒頭の説明と、fixture の description、updates）。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(UNCHANGED.read_text(encoding="utf-8"))

    def compare(self, name, current, expected=None):
        """current を fixture の name の行と照らす。expected を渡すと、fixture のその行だけと照らす。"""
        expected = self.fixture[name] if expected is None else expected
        self.assertEqual(sorted(current), sorted(expected), "{} の対象が fixture と違う".format(name))
        changed = ["{} {}".format(key, variant) for key in sorted(expected) for variant in sorted(expected[key])
                   if current[key].get(variant) != expected[key][variant]]
        self.assertEqual(changed, [], "{} の出力が fixture と違う（行の出どころは fixture の source_commit）".format(name))

    def test_fixture_covers_the_whole_corpus(self):
        self.assertEqual(len(corpus_files()), 181)
        self.assertEqual(sorted(self.fixture["lint"]), corpus_files())

    def test_lint_outputs_match_before_g7(self):
        """lint の行は G7 の前（45a5885 の作業ツリー）の出力のまま。"""
        self.compare("lint", unchanged_lint())


class DefaultsTest(DocTypeCase):
    def test_a1_lint_text_without_options_is_the_same(self):
        """A1: lint_text(t) と lint_text(t, doc_type=None, reader=None) が同じ。人が読む出力に「文書の種類:」の行がない。"""
        texts = [(CORPUS / relative).read_text(encoding="utf-8") for relative in corpus_files()]
        texts += [case["text"] for case in json.loads((FIXTURES / "bold_regressions.json").read_text(encoding="utf-8"))]
        for text in texts:
            plain = yomiyasu_lint.lint_text(text)
            given = yomiyasu_lint.lint_text(text, doc_type=None, reader=None)
            self.assertEqual(plain, given)
            self.assertNotIn("文書の種類:", yomiyasu_lint.render_report(plain))

    def test_a2_lint_context_is_null_without_options(self):
        """A2: JSON の context は値なしで、not_judged の次、metrics の前。"""
        result = yomiyasu_lint.lint_text(SLIDES_SAMPLE)
        self.assertEqual(result["context"], {"doc_type": None, "reader": None, "skipped_by_doc_type": {}})
        keys = list(result)
        self.assertEqual(keys[keys.index("not_judged") + 1], "context")
        self.assertEqual(keys[keys.index("context") + 1], "metrics")
        code, out, err = self.lint("--json", stdin=SLIDES_SAMPLE.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["context"], {"doc_type": None, "reader": None, "skipped_by_doc_type": {}})

# ---- B. lint の種類ごとの外し方 ----

class LintSkipTest(DocTypeCase):
    def test_b1_findings_with_a_type_are_the_plain_findings_minus_the_table(self):
        """B1: コーパスの全ファイルと10の種類で、種類つきの候補から種類を限って当てる規則（pause_comma、2.2.0 の
        dialogue_period と narrative_density）を除けば、種類なしの候補から表の規則を除いたもの（順も同じ）。"""
        for relative in corpus_files():
            text = (CORPUS / relative).read_text(encoding="utf-8")
            plain = yomiyasu_lint.lint_text(text)["findings"]
            for value in DOC_TYPE_VALUES:
                result = yomiyasu_lint.lint_text(text, doc_type=value)
                kept = [finding for finding in plain if finding["rule"] not in SKIP_RULES[value]]
                self.assertEqual([f for f in result["findings"] if f["rule"] not in yomiyasu_lint.DOC_TYPE_ONLY_RULES], kept,
                                 (relative, value))
                skipped = result["context"]["skipped_by_doc_type"]
                self.assertEqual(list(skipped), list(SKIP_RULES[value]), (relative, value))
                self.assertEqual(sum(skipped.values()), len(plain) - len(kept), (relative, value))
                for rule, count in skipped.items():
                    self.assertEqual(count, sum(1 for finding in plain if finding["rule"] == rule), (relative, rule))

    def test_b2_each_skipped_rule_is_real_and_skipped_only_for_its_types(self):
        """B2: 外す規則ごとに、その規則だけに当たる文書で、種類なしでは出て、外す種類では出ず、外さない種類では出る。"""
        rules = sorted(set(rule for value in DOC_TYPE_VALUES for rule in SKIP_RULES[value]))
        # 2.2.0 の規則（metaphor_label、bare_verb_chain）は、検出の関数の外から候補を1件入れて、表で外れることを見る
        # （検出そのものは tests/test_v220_*.py）
        self.assertEqual(sorted(set(RULE_SAMPLES) | set(INJECTED_V220_RULES)), rules)
        for rule in INJECTED_V220_RULES:
            injected = {"rule": rule, "line": 1, "severity": "info", "message": "合成の候補です。", "snippet": "記録を確認した。"}
            with mock.patch.object(yomiyasu_lint, "_v220_document_findings", lambda analysis, doc_type, f=injected: [dict(f)]):
                plain = yomiyasu_lint.lint_text("記録を確認した。\n")["findings"]
                self.assertEqual([finding["rule"] for finding in plain], [rule], rule)
                for value in DOC_TYPE_VALUES + tuple(row[0] for row in NEW_DOC_TYPES):
                    found = [finding["rule"] for finding in
                             yomiyasu_lint.lint_text("記録を確認した。\n", doc_type=value)["findings"]]
                    self.assertEqual(found, [] if rule in yomiyasu_lint.DOC_TYPE_SKIP_RULES[value] else [rule], (rule, value))
        for rule, text in RULE_SAMPLES.items():
            plain = yomiyasu_lint.lint_text(text)["findings"]
            self.assertEqual([finding["rule"] for finding in plain], [rule], rule)
            for value in DOC_TYPE_VALUES:
                found = [finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type=value)["findings"]]
                self.assertEqual(found, [] if rule in SKIP_RULES[value] else [rule], (rule, value))

    def test_b3_counts_and_scores_come_from_the_kept_findings(self):
        """B3: 外したあとの counts、candidate_count、no_rule_findings、rule_penalty_score は、残った候補から計算した値。
        metrics は変えない。"""
        for text in list(RULE_SAMPLES.values()) + [SLIDES_SAMPLE, EXCESS_LIST_ONLY + BOLD_ERROR_ONLY]:
            plain = yomiyasu_lint.lint_text(text)
            for value in DOC_TYPE_VALUES:
                result = yomiyasu_lint.lint_text(text, doc_type=value)
                findings = result["findings"]
                counts = {"error": 0, "warn": 0, "info": 0}
                for finding in findings:
                    counts[finding["severity"]] += 1
                self.assertEqual(result["counts"], counts, value)
                self.assertEqual(result["candidate_count"], len(findings), value)
                self.assertEqual(result["no_rule_findings"], not findings, value)
                # 全例が地の文1,000字未満。行の重み3/2/1、文書の重み2/2/1を独立に計算。
                self.assertLessEqual(plain["metrics"]["char_count"], 1000)
                documents = {"excess_bold": 2, "excess_list": 2, "bold_label_list": 1}
                weights = {"error": 3, "warn": 2, "info": 1}
                # 2.2.0 から 2.4.0 で足した規則の候補は点数を計算する前に除く
                excluded = yomiyasu_lint._V220_RULES + yomiyasu_lint._V230_RULES + yomiyasu_lint._V240_RULES
                scored = [f for f in findings if f["rule"] not in excluded]
                line_weight = sum(weights[f["severity"]] for f in scored
                                  if f["rule"] not in documents and f["rule"] != "negative_parallelism_density")
                document_weight = sum(documents.get(f["rule"], 0) for f in scored)
                num = 4000 * 1000
                den = (40 + document_weight + line_weight) * 1000
                expected = max(1, min(99, (2 * num + den) // (2 * den))) if scored else 100
                self.assertEqual(result["rule_penalty_score"], expected, value)
                self.assertEqual(result["metrics"], plain["metrics"], value)

    def test_b4_strict_uses_the_kept_findings(self):
        """B4: excess_list だけに当たる文書の --strict は、種類なしと外さない種類で1、外す種類で0。"""
        path = self.write("list.md", EXCESS_LIST_ONLY)
        code, _, _ = self.lint("--strict", path)
        self.assertEqual(code, 1)
        for value in DOC_TYPE_VALUES:
            code, out, err = self.lint("--strict", "--doc-type", value, path)
            self.assertEqual(code, 0 if "excess_list" in SKIP_RULES[value] else 1, value)
            self.assertEqual(err, "")
            self.assertEqual("終了コード1:" in out, code == 1, value)

    def test_b5_bold_not_rendered_is_never_skipped(self):
        """B5: bold_not_rendered だけに当たる文書の --fail-on=error は、10の種類すべてで1。"""
        path = self.write("bold.md", BOLD_ERROR_ONLY)
        for value in DOC_TYPE_VALUES:
            code, out, _ = self.lint("--fail-on=error", "--doc-type", value, path)
            self.assertEqual(code, 1, value)
            self.assertTrue(out.endswith("終了コード1: --fail-on=error の条件（error の候補が1件以上）に当たりました"
                                         "（error 1件、warn 0件）。\n"), out)

    def test_b6_reader_does_not_change_findings(self):
        """B6: 3つの読者のどれでも、候補は読者なしと同じ。"""
        for text in list(RULE_SAMPLES.values()) + [SLIDES_SAMPLE]:
            plain = yomiyasu_lint.lint_text(text)
            for reader in READER_VALUES:
                result = yomiyasu_lint.lint_text(text, reader=reader)
                self.assertEqual(result["findings"], plain["findings"], reader)
                self.assertEqual(result["counts"], plain["counts"], reader)
                self.assertEqual(result["context"], {"doc_type": None, "reader": reader, "skipped_by_doc_type": {}})

    def test_b7_fourth_line(self):
        """B7: 4行目は付けたときだけ。外す規則あり、外す規則なし、読者だけ、種類と読者の形。"""
        path = self.write("slides.md", SLIDES_SAMPLE)
        code, out, err = self.lint("--doc-type", "slides", path)
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        self.assertEqual(lines[:3], [LINT_HEADER[0], LINT_HEADER[1].format(1), LINT_HEADER[2]])
        self.assertEqual(lines[3], SLIDES_LINE)
        self.assertEqual(lines[4:6], ["", "内訳: error 0件、warn 1件、info 0件"])
        cases = (
            (("--doc-type", "article", "--reader", "expert"),
             "文書の種類: 技術記事（article）、読者: 同じ分野の専門家（expert）。" + LINT_NO_SKIP + LINT_READER_NOTE),
            (("--reader", "general"), "文書の種類: 指定なし、読者: 専門知識のない人（general）。" + LINT_READER_NOTE),
            (("--doc-type", "formal"), "文書の種類: 公用文、規程、契約書、仕様書（formal）、読者: 指定なし。" + LINT_NO_SKIP),
            (("--doc-type", "pr", "--reader", "informed"),
             "文書の種類: PR説明（pr）、読者: 分野は違うが技術に詳しい人（informed）。種類に合わせて外した候補 0件"
             "（excess_list 0件）。" + LINT_READER_NOTE),
        )
        for argv, expected in cases:
            code, out, err = self.lint(*(argv + (path,)))
            self.assertEqual(out.split("\n")[3], expected, argv)
        # 候補が0件でも、4行目は出る（そのあとに内訳はない）
        empty = self.write("empty.md", "会議は3時に始まります。\n")
        code, out, err = self.lint("--doc-type", "minutes", empty)
        self.assertEqual(out, "\n".join([LINT_HEADER[0], LINT_HEADER[1].format(0), LINT_HEADER[2],
                                         "文書の種類: 議事録（minutes）、読者: 指定なし。種類に合わせて外した候補 0件"
                                         "（bold_label_list 0件、excess_list 0件、sentence_end_repetition 0件）。"]) + "\n")
        # render_findings は変えない
        result = yomiyasu_lint.lint_text(SLIDES_SAMPLE, doc_type="slides")
        self.assertNotIn("文書の種類", yomiyasu_lint.render_findings(result))

    def test_b7_strict_tail_counts_the_kept_findings(self):
        """9.3: 2行目の件数、内訳、終了コード1の最後の行の件数は、外したあとの候補で数える。"""
        path = self.write("both.md", EXCESS_LIST_ONLY + "\n" + BOLD_ERROR_ONLY)
        code, out, _ = self.lint("--strict", "--doc-type", "manual", path)
        lines = out.split("\n")
        self.assertEqual(code, 1)
        self.assertEqual(lines[1], "見直し候補: 1件")
        self.assertEqual(lines[3], "文書の種類: マニュアル（manual）、読者: 指定なし。種類に合わせて外した候補 1件（excess_list 1件）。")
        self.assertEqual(lines[-2], "終了コード1: --strict の条件（warn か error の候補が1件以上）に当たりました（error 1件、warn 0件）。")

    def test_b8_type_only_rules(self):
        """B8: DOC_TYPE_ONLY_RULES の規則は、種類なしとほかの種類では除かれ、指定した種類でだけ残る。"""
        self.assertEqual(yomiyasu_lint.DOC_TYPE_ONLY_RULES, {
            "pause_comma": ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal", "mail", "paper"),
            "dialogue_period": ("script",),
            "narrative_density": ("essay",),
            "slide_comma": ("slides",),
        })
        text = COUNT_DECLARATION_ONLY
        with mock.patch.object(yomiyasu_lint, "DOC_TYPE_ONLY_RULES", {"count_declaration": ("article",)}):
            self.assertEqual(yomiyasu_lint.lint_text(text)["findings"], [])
            self.assertEqual([finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type="article")["findings"]],
                             ["count_declaration"])
            for value in DOC_TYPE_VALUES:
                if value != "article":
                    self.assertEqual(yomiyasu_lint.lint_text(text, doc_type=value)["findings"], [], value)

    def test_lint_text_takes_keyword_only_options(self):
        """9.2: lint_text(text, *, doc_type=None, reader=None)。値は中で正規化し、使えない値は ValueError。"""
        parameters = inspect.signature(yomiyasu_lint.lint_text).parameters
        for name in ("doc_type", "reader"):
            self.assertEqual(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIsNone(parameters[name].default)
        self.assertEqual(yomiyasu_lint.lint_text(SLIDES_SAMPLE, doc_type=" ＳＬＩＤＥＳ ", reader="General")["context"],
                         {"doc_type": "slides", "reader": "general",
                          "skipped_by_doc_type": {"bare_verb_chain": 0, "bold_label_list": 1, "cleft_list_ending": 0,
                                                  "count_declaration": 0,
                                                  "excess_list": 0,
                                                  "short_summary_heading": 1}})
        with self.assertRaises(ValueError):
            yomiyasu_lint.lint_text(SLIDES_SAMPLE, doc_type="tech")
        with self.assertRaises(ValueError):
            yomiyasu_lint.lint_text(SLIDES_SAMPLE, reader="")

    def test_json_keeps_finding_keys_and_format(self):
        """9.3: findings の各要素は5キーのまま。外した候補の中身は JSON に入れない。形式2のまま。"""
        code, out, _ = self.lint("--json", "--doc-type", "slides", self.write("s.md", SLIDES_SAMPLE))
        result = json.loads(out)
        self.assertEqual(result["format_version"], 2)
        self.assertEqual([finding["rule"] for finding in result["findings"]], ["emoji_prohibited"])
        for finding in result["findings"]:
            self.assertEqual(set(finding), {"rule", "line", "severity", "message", "snippet"})
        self.assertNotIn("bold_label_list", json.dumps(result["findings"]))


# ---- C. 表と文書の食い違いを防ぐ（道具の部分）----

class TableTest(unittest.TestCase):
    def test_c1_tables(self):
        """C1: DOC_TYPE_SKIP_RULES のキーは DOC_TYPES の13と同じで順も同じ。READER_LEVELS は3つ。"""
        self.assertEqual(tuple(row[0] for row in markdown_visibility.DOC_TYPES), DOC_TYPE_VALUES + ("mail", "paper", "script"))
        self.assertEqual(dict((row[0], row[1]) for row in markdown_visibility.DOC_TYPES), dict(DOC_TYPE_NAMES, **{r[0]: r[1] for r in NEW_DOC_TYPES}))
        self.assertEqual(dict((row[0], tuple(row[2])) for row in markdown_visibility.DOC_TYPES), dict(DOC_TYPE_DOMAINS, **{r[0]: r[2] for r in NEW_DOC_TYPES}))
        self.assertEqual(tuple(markdown_visibility.READER_LEVELS),
                         tuple((value, READER_NAMES[value]) for value in READER_VALUES))
        self.assertEqual(list(yomiyasu_lint.DOC_TYPE_SKIP_RULES), list(DOC_TYPE_VALUES) + ["mail", "paper", "script"])
        self.assertEqual(dict((key, tuple(value)) for key, value in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items()), dict(SKIP_RULES, **NEW_SKIP_RULES))
        for value, rules in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items():
            self.assertEqual(list(rules), sorted(set(rules)), value)

    def test_c2_rules_that_are_never_skipped(self):
        """C2: bold_not_rendered（error）と、5.3 で外さないとした規則は、どの種類の表にもない（fragment_run の promo を除く）。"""
        for value, rules in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items():
            for rule in NEVER_SKIPPED:
                if value in NEVER_SKIPPED_EXCEPT.get(rule, ()):
                    continue
                self.assertNotIn(rule, rules, value)

    def test_c6_lint_help_lists_the_table(self):
        """C6: lint の --help の一覧が、DOC_TYPE_SKIP_RULES と DOC_TYPE_ONLY_RULES から作った文と同じ（終了コードの表の前）。"""
        built = ["文書の種類ごとに外す規則（--doc-type）:"]
        for value, rules in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items():
            built.append("  {:<10}{}".format(value, "、".join(rules) if rules else "なし"))
        built.append(next(line for line in LINT_HELP_LIST.split("\n") if line.startswith("mail は meta_filler")))
        for rule, allowed in yomiyasu_lint.DOC_TYPE_ONLY_RULES.items():
            excluded = [row[0] for row in yomiyasu_lint.DOC_TYPES if row[0] not in allowed]
            if len(allowed) < len(excluded):
                scope = "{} だけ".format("、".join(allowed))
            else:
                scope = "{} を除く{}種類".format("、".join(excluded), len(allowed)) if excluded else "全{}種類".format(len(allowed))
            built.append("種類を指定したときだけ当てる規則: {}（{}。種類を指定しないときは出しません）".format(rule, scope))
        built.append("外した候補は、見直し候補の件数と --strict、--fail-on の判定に入れません。")
        self.assertEqual("\n".join(built), LINT_HELP_LIST)
        code, out, _ = call(yomiyasu_lint.main, ["--help"])
        self.assertEqual(code, 0)
        # 種類の表と終了コードの表の間に、点数の式の説明を置く。
        self.assertIn(LINT_HELP_LIST + "\n\nrule_penalty_score（--json の目安）:", out)
        self.assertLess(out.index("rule_penalty_score（--json の目安）:"), out.index("終了コード:"))

    def test_help_texts(self):
        """9.6 のヘルプの文。"""
        def helps(parser):
            return dict((option, action.help) for action in parser._actions for option in action.option_strings)
        lint_help = helps(yomiyasu_lint._build_parser())
        self.assertEqual((lint_help["--doc-type"], lint_help["--reader"]), (LINT_DOC_TYPE_HELP, LINT_READER_HELP))
        code, out, _ = call(yomiyasu_lint.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--doc-type", out)
        self.assertIn("--reader", out)


class VisibilityApiTest(unittest.TestCase):
    """9.2: markdown_visibility の正規化と、lint の1行の頭。"""

    def test_normalize(self):
        for raw, expected in (("SLIDES", "slides"), (" slides ", "slides"), ("ｓｌｉｄｅｓ", "slides"),
                              ("　Formal　", "formal"), ("pr", "pr"), (None, None)):
            self.assertEqual(markdown_visibility.normalize_doc_type(raw), expected, raw)
        for raw, expected in (("EXPERT", "expert"), ("ｇｅｎｅｒａｌ", "general"), (None, None)):
            self.assertEqual(markdown_visibility.normalize_reader(raw), expected, raw)
        for raw, shown in (("tech", "tech"), ("", "（空）"), ("  ", "（空）"), ("スライド", "スライド"), ("none", "none")):
            with self.assertRaises(ValueError) as caught:
                markdown_visibility.normalize_doc_type(raw)
            self.assertEqual(str(caught.exception), DOC_TYPE_ERROR.format(shown))
        with self.assertRaises(ValueError) as caught:
            markdown_visibility.normalize_reader("beginner")
        self.assertEqual(str(caught.exception), READER_ERROR.format("beginner"))

    def test_context_label(self):
        self.assertEqual(markdown_visibility.context_label("slides", None), "文書の種類: スライド（slides）、読者: 指定なし。")
        self.assertEqual(markdown_visibility.context_label(None, "general"),
                         "文書の種類: 指定なし、読者: 専門知識のない人（general）。")
        self.assertEqual(markdown_visibility.context_label("essay", "expert"),
                         "文書の種類: エッセイ・小説（essay）、読者: 同じ分野の専門家（expert）。")


# ---- D. オプション ----

class OptionTest(DocTypeCase):
    def test_d1_normalized_in_every_tool(self):
        """D1: 大文字、前後の空白、全角を正規化する。--doc-type=値 と --doc-type 値 の両方。"""
        b = self.write("b.md", SLIDES_SAMPLE)
        for form in (["--doc-type=SLIDES", "--reader= General "], ["--doc-type", "ｓｌｉｄｅｓ", "--reader", "GENERAL"]):
            code, out, _ = self.lint(*(form + ["--json", b]))
            self.assertEqual(json.loads(out)["context"]["doc_type"], "slides", form)
            self.assertEqual(json.loads(out)["context"]["reader"], "general", form)

    def test_d1_last_value_wins(self):
        """9.1: 同じオプションを2回付けたら最後の値を使う。"""
        b = self.write("b.md", SLIDES_SAMPLE)
        _, out, _ = self.lint("--doc-type", "pr", "--doc-type", "slides", "--json", b)
        self.assertEqual(json.loads(out)["context"]["doc_type"], "slides")

    def test_d2_bad_values_are_usage_errors(self):
        """D2: 使えない値と空の文字列で終了コード2。標準エラーに 9.1 の文、標準出力は空。"""
        b = self.write("b.md", PAIRS_22[1][1])
        cases = ((["--doc-type", "tech"], DOC_TYPE_ERROR.format("tech")),
                 (["--doc-type="], DOC_TYPE_ERROR.format("（空）")),
                 (["--doc-type", "スライド"], DOC_TYPE_ERROR.format("スライド")),
                 (["--reader", "beginner"], READER_ERROR.format("beginner")),
                 (["--reader", " "], READER_ERROR.format("（空）")))
        for option, message in cases:
            code, out, err = call(yomiyasu_lint.main, option + [b])
            self.assertEqual((code, out, err), (2, "", message + "\n"), option)

    def test_d8_versions_do_not_change(self):
        """D8: --version と形式の版は変えない（9.7）。"""
        self.assertEqual(call(yomiyasu_lint.main, ["--version"])[1], "yomiyasu_lint.py 3.2.0 (JSON format 2)\n")


# ---- E. 速さ ----

class SpeedTest(unittest.TestCase):
    def test_e1_long_document(self):
        """E1: 6万字の文書で、--doc-type slides の lint が指定なしの時間＋0.2秒以内。"""
        block = SLIDES_SAMPLE + EXCESS_LIST_ONLY + SENTENCE_END_ONLY + COUNT_DECLARATION_ONLY + "\n"
        text = block * (60000 // len(block) + 1)
        self.assertGreaterEqual(len(text), 60000)

        # 0.2秒の差は、Windows の遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）。時間は CPU 時間で測る
        clock = timing_clock()

        def best(**options):
            times = []
            for _ in range(3):
                started = clock()
                yomiyasu_lint.lint_text(text, **options)
                times.append(clock() - started)
            return min(times)

        plain = best()
        typed = best(doc_type="slides")
        slack, detail = paced_limit(0.2, typed - plain)
        self.assertLessEqual(typed, plain + slack, (plain, typed, detail))


# ---- C3、C4、C5: SKILL.md と references（SKILL.md と references を入れる段までは失敗する）----

class SkillFilesTest(unittest.TestCase):
    def test_c3_doc_type_files(self):
        """C3: 13の references/doc-types/<値>.md がルートと skills/yomiyasu にあり、4行目が表と同じ。3行目の domains がある。
        mail、paper、script は、4行目の規則 ID が DOC_TYPE_SKIP_RULES と DOC_TYPE_SKIP_PATTERNS（一部の型だけ外す規則）の和と同じ。"""
        for base in (ROOT / "references", PACKAGE / "references"):
            for value in DOC_TYPE_VALUES + tuple(row[0] for row in NEW_DOC_TYPES):
                path = base / "doc-types" / (value + ".md")
                self.assertTrue(path.is_file(), str(path))
                lines = path.read_text(encoding="utf-8").split("\n")
                rules = yomiyasu_lint.DOC_TYPE_SKIP_RULES[value]
                if value in DOC_TYPE_VALUES:
                    self.assertEqual(lines[3], "lint で外す規則: " + ("、".join(rules) if rules else "なし"), str(path))
                else:
                    self.assertTrue(lines[3].startswith("lint で外す規則: "), str(path))
                    partial = tuple(yomiyasu_lint.DOC_TYPE_SKIP_PATTERNS.get(value, {}))
                    self.assertEqual(set(re.findall(r"[a-z][a-z_]+", lines[3][len("lint で外す規則: "):])), set(rules + partial), str(path))
                    if not rules and not partial:
                        self.assertEqual(lines[3], "lint で外す規則: なし", str(path))
                self.assertTrue(lines[2].startswith("あわせて読む: "), str(path))
                named = re.findall(r"domains/([a-z]+\.md)", lines[2])
                self.assertTrue(named, str(path))
                for name in named:
                    self.assertTrue((base / "domains" / name).is_file(), (str(path), name))

    def test_c4_audience_table(self):
        """C4: audience.md の種類と外す規則の表の規則ID が DOC_TYPE_SKIP_RULES と同じ。"""
        for base in (ROOT / "references", PACKAGE / "references"):
            path = base / "audience.md"
            self.assertTrue(path.is_file(), str(path))
            rows = {}
            column = None
            for line in path.read_text(encoding="utf-8").split("\n"):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")] if line.startswith("|") else None
                if cells is None:
                    column = None
                    continue
                if "lint で外す規則" in cells:
                    column = cells.index("lint で外す規則")
                    continue
                if column is not None and (cells[0] in DOC_TYPE_VALUES or cells[0] in NEW_SKIP_RULES):
                    # mail の meta_filler は一部の型だけを外す（「meta_filler（返信と結びの5つの型だけ）」）。括弧の中は読まない
                    rows[cells[0]] = tuple(re.sub(r"（[^）]*）", "", rule) for rule in re.split(r"[、,]\s*", cells[column])
                                           if rule and rule != "なし")
            expected = dict(SKIP_RULES)
            for value, rules in NEW_SKIP_RULES.items():
                expected[value] = rules + tuple(yomiyasu_lint.DOC_TYPE_SKIP_PATTERNS.get(value, {}))
            self.assertEqual(rows, expected, str(path))

    def test_c5_skill_md(self):
        """C5: SKILL.md の種類の一覧（Step 1 の「種類は 〜 の13種類で」の文）に13の値がちょうど1回ずつあり、3つの読者の値、
        「ここに説明が必要です」、--doc-type、--reader がある（--doc-type と --reader が check run の --help にあることは
        TableTest.test_help_texts）。
        3.0.0 で種類の表を文の一覧にした（種類ごとの当てない規則は references/doc-types/<値>.md の「普通な書き方」にある）。"""
        text = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")
        lists = re.findall(r"種類は (.+?)の13種類で", text)
        self.assertEqual(len(lists), 1, lists)
        found = re.findall(r"[a-z]+", lists[0])
        self.assertEqual(sorted(found), sorted(DOC_TYPE_VALUES + tuple(row[0] for row in NEW_DOC_TYPES)))
        for word in READER_VALUES + ("ここに説明が必要です", "--doc-type", "--reader"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
