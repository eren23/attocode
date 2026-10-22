"""Reject image growth and invalid comparisons using independent measured inputs."""
import pytest

from eval.quality.image_budget import check_growth, check_comparison


def baseline():
    return {'schema_version': 1, 'image_size_bytes': 1000, 'allowed_growth_percent': 5,
            'source_commit': 'a' * 40, 'review': 'Measured passing same-runner runtime image comparison.'}


def test_image_growth_ceiling_accepts_boundary_and_rejects_one_byte_more():
    check_growth(1050, baseline())
    with pytest.raises(ValueError, match='image_growth'):
        check_growth(1051, baseline())


@pytest.mark.parametrize('size', [0, -1, True, 1000.5])
def test_invalid_measured_size_cannot_pass_growth_guard(size):
    with pytest.raises(ValueError):
        check_growth(size, baseline())


@pytest.mark.parametrize('missing', ['review', 'source_commit', 'image_size_bytes'])
def test_size_baseline_requires_reviewed_source_provenance(missing):
    record = baseline()
    record.pop(missing)
    with pytest.raises(ValueError):
        check_growth(1000, record)


def measured(size=1000):
    return {'size_bytes': size, 'identity': {'dependencies': [['example', '1.0']],
            'runtime_layers': ['sha256:base'], 'static_sha256': 'fixed'},
            'runtime_checks': {'health': True, 'dashboard': True, 'mcp_auth': True,
                               'navigation': True, 'cli': True, 'writable_state': True}}


def test_only_strictly_smaller_equivalent_passing_image_can_be_adopted():
    check_comparison(measured(), measured(999))
    with pytest.raises(ValueError, match='not_smaller'):
        check_comparison(measured(), measured())
    changed = measured(999)
    changed['identity']['dependencies'] = [['example', '2.0']]
    with pytest.raises(ValueError, match='identity'):
        check_comparison(measured(), changed)


def test_missing_or_failed_runtime_check_prevents_image_adoption():
    for missing in (True, False):
        changed = measured(999)
        if missing:
            changed['runtime_checks'].pop('cli')
        else:
            changed['runtime_checks']['cli'] = False
        with pytest.raises(ValueError, match='runtime'):
            check_comparison(measured(), changed)
