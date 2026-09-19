import hashlib
import json
import math
import sys

import pytest

from laboratorio.evaluation import evaluate


def numeric_case(expected, tolerance=0):
    return dict(id='x', domain='math', prompt='Exactamente 1e20',
                expected=expected, method='numeric', tolerance=tolerance)


def test_reported_int_float_false_positive():
    answer = 100000000000000000001
    expected = 1e20
    assert answer != expected
    report = evaluate([numeric_case(expected)], [dict(id='x', answer=answer)])
    assert report['correct'] == 0


@pytest.mark.parametrize('answer,expected,tolerance,correct', [
    (2**53 + 1, 2**53, 0, False),
    (2**53 + 1, float(2**53), 0, False),
    (2**53 + 1, float(2**53), 1, True),
    (2**53 + 1, float(2**53), math.nextafter(1.0, 0.0), False),
    (10**20 + 1, 1e20, 0, False),
    (10**20 - 1, 1e20, 0, False),
    (10**20 + 1, 1e20, 1.0, True),
    (10**20 + 2, 1e20, 1, False),
    (10**20, 1e20, 0, True),
    (-(10**20 + 1), -1e20, 0, False),
    (10**400, 0.0, 10**400, True),
    (10**400, 0.0, 10**400 - 1, False),
    (10**400, 0.0, 0, False),
    (10**400 + 1, 10**400, 1, True),
    (10**400 + 1, 10**400, 0, False),
    (2**53 + 1, 0, float(2**53), False),
    (2**53, 0, float(2**53), True),
    (1.0, -2**-54, 1.0, False),
    (1.0, -2**-54, math.nextafter(1.0, math.inf), True),
    (0.1 + 0.2, 0.3, 0, False),
    (0.3, 0.1, math.nextafter(0.2, 0.0), True),
    (0.1, 0, 0.1, True),
    (0.1, 0, math.nextafter(0.1, 0.0), False),
    (5e-324, 0.0, 0, False),
    (5e-324, 0.0, 5e-324, True),
    (5e-324, -5e-324, 5e-324, False),
    (5e-324, -5e-324, 1e-323, True),
    (sys.float_info.max, -sys.float_info.max, 2 * int(sys.float_info.max), True),
    (sys.float_info.max, -sys.float_info.max, 2 * int(sys.float_info.max) - 1, False),
    (sys.float_info.max, -sys.float_info.max, sys.float_info.max, False),
    (42, 42.0, 0, True),
    (-0.0, 0, -0.0, True),
    (1.25, 1, 0.25, True),
    (1.5, 1, 0.25, False),
])
@pytest.mark.parametrize('reverse', [False, True])
def test_exact_numeric_distance(answer, expected, tolerance, correct, reverse):
    if reverse:
        answer, expected = expected, answer
    report = evaluate([numeric_case(expected, tolerance)],
                      [dict(id='x', answer=answer)])
    assert report['rows'][0]['correct'] is correct
    assert report['correct'] == int(correct)


@pytest.mark.parametrize('answer', [True, False, '1', None, [], {}])
def test_nonnumeric_answers_fail_closed(answer):
    assert evaluate([numeric_case(1)], [dict(id='x', answer=answer)])['correct'] == 0


@pytest.mark.parametrize('field,value', [
    ('expected', True), ('expected', False),
    ('tolerance', True), ('tolerance', False),
    ('tolerance', -1), ('tolerance', -5e-324),
])
def test_invalid_numeric_reference_rejected(field, value):
    case = numeric_case(1)
    case[field] = value
    with pytest.raises(ValueError):
        evaluate([case], [dict(id='x', answer=1)])


@pytest.mark.parametrize('value', [math.inf, -math.inf, math.nan])
@pytest.mark.parametrize('field', ['answer', 'expected', 'tolerance'])
def test_nonfinite_values_rejected(field, value):
    case, response = numeric_case(1), dict(id='x', answer=1)
    (response if field == 'answer' else case)[field] = value
    with pytest.raises(ValueError):
        evaluate([case], [response])


def test_report_shape_and_original_input_hashes_preserved():
    cases = [numeric_case(1e20)]
    responses = [dict(id='x', answer=10**20 + 1)]
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    cases_hash, responses_hash = digest(cases), digest(responses)
    assert evaluate(cases, responses) == {
        'schema_version': 1, 'status': 'COMPLETE', 'total': 1, 'correct': 0,
        'answered': 1, 'missing': 0, 'accuracy': 0.0, 'coverage': 1.0,
        'by_domain': {'math': {'total': 1, 'correct': 0, 'answered': 1}},
        'rows': [dict(id='x', domain='math', answered=True, correct=False)],
        'cases_sha256': cases_hash, 'responses_sha256': responses_hash,
        'authorizes_actions': False,
        'claim_scope': 'ONLY_THESE_CASES_NOT_GENERAL_INTELLIGENCE',
    }
    assert digest(cases) == cases_hash
    assert digest(responses) == responses_hash


def test_default_zero_tolerance_and_missing_answer():
    case = numeric_case(1e20)
    del case['tolerance']
    assert evaluate([case], [dict(id='x', answer=10**20 + 1)])['correct'] == 0
    report = evaluate([case], [])
    assert report['correct'] == 0 and report['missing'] == 1
    assert report['status'] == 'INCOMPLETE'
