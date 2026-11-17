"""Observable work reductions with the real bold algorithm."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import yomiyasu_lint


class OptimizationWorkTests(unittest.TestCase):
    def test_independent_bold_repairs_reuse_the_original_analysis(self):
        # Concatenating these fragments creates valid cross-fragment strong
        # matches. Separate paragraphs are forty actual independent failures.
        text = '\n\n'.join(['文**「語句」**続き'] * 40)
        original = yomiyasu_lint.analyze_markdown
        analyzed = []

        def counted(value, *args, **kwargs):
            analyzed.append(value)
            return original(value, *args, **kwargs)

        with patch.object(yomiyasu_lint, 'analyze_markdown', counted):
            findings = yomiyasu_lint.bold_problems(text)
        self.assertEqual(len(findings), 40)
        self.assertEqual(analyzed.count(text), 1)
        self.assertLessEqual(len(analyzed), 41)
        self.assertEqual(findings[0]['how'], 'かっこの内側だけを太字にする')

    def test_concatenated_fragments_are_not_forty_broken_pairs(self):
        # Actual GFM renders 39 intervening strong regions for this source.
        # Keep this adjudicated correctness delta separate from a speed claim.
        findings = yomiyasu_lint.bold_problems('文**「語句」**続き ' * 40)
        self.assertEqual(len(findings), 1)


if __name__ == '__main__':
    unittest.main()
