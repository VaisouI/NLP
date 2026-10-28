from unittest.mock import Mock

import pytest

from src.prediction import SmsPredictor
from src.preprocessing import InputPolicy, InputValidationError, normalize_text


@pytest.mark.parametrize(('payload', 'code'), [
    ('plain string', 'invalid_structure'),
    ([], 'invalid_structure'),
    ({}, 'invalid_fields'),
    ({'text': 'hello', 'extra': True}, 'invalid_fields'),
    ({'text': 1}, 'invalid_type'),
    ({'text': False}, 'invalid_type'),
    ({'text': None}, 'invalid_type'),
    ({'text': float('nan')}, 'invalid_type'),
    ({'text': float('inf')}, 'invalid_type'),
    ({'text': ''}, 'empty_text'),
    ({'text': ' \n\t '}, 'empty_text'),
    ({'text': 'x' * 65}, 'text_too_long'),
    ({'text': 'я' * 49}, 'text_too_large'),
    ({'text': '\ufb03' * 22}, 'normalized_too_large'),
    ({'text': '\ud800'}, 'invalid_unicode'),
    ({'text': 'a\x00b'}, 'control_character'),
    ({'text': 'a\u0092b'}, 'control_character'),
])
def test_invalid_inputs_never_call_model(payload, code):
    model = Mock()
    predictor = SmsPredictor(model, policy=InputPolicy(64, 96))
    with pytest.raises(InputValidationError) as error:
        predictor.predict(payload)
    assert error.value.code == code
    model.predict.assert_not_called()


def test_valid_input_is_normalized_once_and_returns_documented_shape():
    model = Mock()
    model.predict.return_value = ['spam']
    response = SmsPredictor(model).predict({'text': '  ＦＲＥＥ\t PRIZE \n'})
    assert response == {'prediction': 'spam', 'model_version': 'lab2-v1'}
    model.predict.assert_called_once_with(['free prize'])


def test_preprocessing_is_idempotent_and_folds_equivalent_inputs():
    value = ' \n ＨＥＬＬＯ\tStraße  '
    normalized = normalize_text(value)
    assert normalized == 'hello strasse'
    assert normalize_text(normalized) == normalized


def test_size_boundary_is_inclusive():
    model = Mock()
    model.predict.return_value = ['ham']
    assert SmsPredictor(model, policy=InputPolicy(8, 8)).predict({'text': 'abcdefgh'})['prediction'] == 'ham'


@pytest.mark.parametrize('value', [0, -1, True, 1.5])
def test_invalid_limit_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        InputPolicy(value, 100)
