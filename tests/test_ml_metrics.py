import pytest

from src.ml_metrics import classification_metrics


def test_metrics_match_a_hand_computed_confusion_matrix():
    result = classification_metrics(['ham', 'ham', 'spam', 'spam'], ['ham', 'spam', 'spam', 'spam'])
    assert result['confusion_matrix'] == [[1, 1], [0, 2]]
    assert result['accuracy'] == pytest.approx(0.75)
    assert result['f1_spam'] == pytest.approx(0.8)
    assert result['per_class']['spam']['precision'] == pytest.approx(2 / 3)
    assert result['per_class']['spam']['recall'] == pytest.approx(1.0)


def test_majority_prediction_cannot_hide_zero_spam_recall():
    result = classification_metrics(['ham'] * 9 + ['spam'], ['ham'] * 10)
    assert result['accuracy'] == pytest.approx(0.9)
    assert result['f1_spam'] == 0
    assert result['per_class']['spam']['recall'] == 0


@pytest.mark.parametrize(('truth', 'predicted'), [([], []), (['ham'], []), (['bad'], ['ham']), (['ham'], [None])])
def test_invalid_metric_input_is_rejected(truth, predicted):
    with pytest.raises(ValueError):
        classification_metrics(truth, predicted)
