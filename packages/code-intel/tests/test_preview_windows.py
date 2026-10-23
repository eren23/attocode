"""Runner-only RED/GREEN and controls for the fixed preview-window experiment."""
import pytest
from attocode_intel.focused_evidence import task_terms, terms
from attocode_intel.search_evidence import snippet_window as baseline_window

from eval.quality.preview_windows import window_preview

preview = window_preview


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_later_window_strictly_extends_baseline_positive_coverage(newline):
    tail = newline.join(['alpha();', 'beta();', 'gamma();']) + newline
    body = ('alpha beta();' + newline) + ('padding();' + newline) * 8 + tail
    result = preview(body, 'alpha beta gamma', len(tail), 1)
    assert all(word in result['snippet'] for word in ('alpha', 'beta', 'gamma'))
    assert result['snippet_start_line'] == 10
    assert result['snippet_end_line'] == 12


@pytest.mark.parametrize('body,query,cap,line', [
    ('alpha beta();\nnext();\n', 'alpha beta', 15, 1),
    ('first\nsecond\n', 'missing', 8, 1),
    ('class Upload', 'upload', 8, None),
    ('', 'upload', 8, 1),
    ('padding ' * 100 + 'alphaBeta();', 'alpha beta', 20, 1),
    ('cache cache\nalphaBeta();\n', 'alpha beta without cache', 20, 1),
])
def test_unchanged_fallbacks_and_equal_coverage(body, query, cap, line):
    assert preview(body, query, cap, line) == baseline_window(body, query, cap, line)


def test_exact_source_and_budget_across_long_lines_and_line_endings():
    for newline in ('\n', '\r\n', '\r'):
        body = newline.join(['alpha beta();', 'x' * 80, 'alpha();', 'beta();', 'gamma();'])
        for cap in (1, 12, 28, 60, 200):
            result = preview(body, 'alpha beta gamma', cap, 7)
            assert result['snippet'] in body and len(result['snippet']) <= cap
            assert result['snippet_start_line'] >= 7
            assert result['snippet_end_line'] <= 11
            positive, _ = task_terms('alpha beta gamma')
            assert positive & terms(baseline_window(body, 'alpha beta gamma', cap, 7)['snippet']) <= positive & terms(result['snippet'])
