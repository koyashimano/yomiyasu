"""メール・論文の lint の契約。仕様6章の例と、文書の種類 mail と paper。"""
from pathlib import Path
import contextlib
import io
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import yomiyasu_lint as lint
import markdown_visibility as visibility
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import working_folder  # noqa: E402


def call(main, args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main([str(a) for a in args])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class SpecExamples(unittest.TestCase):
    def test_four_preserved_examples(self):
        for kind, text in (
            ('mail', 'お手数ですが、10月20日までにご確認いただけますでしょうか。'),
            ('mail', 'それ明日でもいいかも、確認しときます'),
            ('paper', 'この結果は、AとBの間に関係がある可能性を示唆する。'),
            ('paper', '平均は12.4（SD = 3.1, p < .05）であった [3]。'),
        ):
            with self.subTest(text=text):
                self.assertEqual(lint.lint_text(text, doc_type=kind)['findings'], [])

    def test_honorific_correction_belongs_to_agent(self):
        # lint は二重敬語や使役の妥当性を判定する規則を持たない。許可・恩恵の文脈判断はエージェント側。
        text = 'ご確認させていただきましたところ、問題ございませんでした。'
        self.assertEqual(lint.lint_text(text, doc_type='mail')['findings'], [])

class DocTypes(unittest.TestCase):
    def test_types_and_mirrors(self):
        # 2.2.0 で script（台詞・脚本）を足して13
        self.assertEqual(len(visibility.DOC_TYPES), 13)
        self.assertEqual(visibility.normalize_doc_type(' ＭＡＩＬ '), 'mail')
        for name in ('markdown_visibility.py', 'yomiyasu_lint.py'):
            self.assertEqual((ROOT/'scripts'/name).read_bytes(), (ROOT/'skills/yomiyasu/scripts'/name).read_bytes())

    def test_mail_filters_only_replies_and_closings(self):
        phrases = ['ご質問ありがとうございます。', '必要なら次に説明します。', 'いかがでしたでしょうか。',
                   'ぜひ試してみてください。', '参考になれば幸いです。']
        for phrase in phrases:
            self.assertTrue(any(f['rule'] == 'meta_filler' for f in lint.lint_text(phrase)['findings']), phrase)
            result = lint.lint_text(phrase, doc_type='mail')
            self.assertFalse(any(f['rule'] == 'meta_filler' for f in result['findings']), phrase)
            self.assertEqual(result['context']['skipped_by_doc_type']['meta_filler'], 1)
        self.assertTrue(any(f['rule'] == 'meta_filler' for f in lint.lint_text('正直に言うと、簡単です。', doc_type='mail')['findings']))
        self.assertEqual(lint.DOC_TYPE_SKIP_RULES['paper'], ())
        for phrase in ['田中様\nお世話になっております。\nよろしくお願いいたします。\n株式会社青空 山田',
                       '恐れ入りますが、ご確認ください。', 'お手数ですが、ご返信ください。']:
            self.assertEqual(lint.lint_text(phrase, doc_type='mail')['findings'], [])

    def test_paper_info_mail_review(self):
        self.assertFalse(lint.lint_text('ありがとう！😀', doc_type='mail')['findings'])

    def test_cli_types_and_japanese_help(self):
        with tempfile.TemporaryDirectory() as folder, working_folder(folder):
            new = Path(folder)/'new.md'
            new.write_bytes('確認します。'.encode('utf-8'))
            for kind in ('mail', 'paper'):
                code, output, error = call(lint.main, [new, '--doc-type', kind, '--json'])
                self.assertEqual((code, error), (0, ''), output)
                self.assertIn(kind, output)
            code, output, error = call(lint.main, ['-h'])
            self.assertEqual(code, 0)
            self.assertIn('mail（メール・チャット）', output.replace('\n', '').replace(' ', ''))
            self.assertIn('paper（論文・研究レポート）', output.replace('\n', '').replace(' ', ''))


if __name__ == '__main__':
    unittest.main()
