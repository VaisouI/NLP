import pytest

from src.detection import detect


@pytest.mark.parametrize('count,triggered', [(2, False), (3, True), (4, True)])
def test_known_detection_threshold(count, triggered):
    records = [{'timestamp': '2026-11-01T10:00:01+00:00', 'route': '/predict', 'http_status': 401, 'request_id': str(i)} for i in range(count)]
    records.extend([{'timestamp': '2026-11-01T09:59:59+00:00', 'route': '/predict', 'http_status': 401},
                    {'timestamp': '2026-11-01T10:00:01+00:00', 'route': '/metrics', 'http_status': 401}])
    rule = {'rule_id': 'test', 'route': '/predict', 'http_status': 401, 'window_seconds': 60, 'threshold': 3}
    result = detect(records, rule, '2026-11-01T10:00:00+00:00', '2026-11-01T10:00:02+00:00')
    assert result['observed'] == count and result['triggered'] is triggered


def test_detection_rejects_an_interval_larger_than_policy():
    with pytest.raises(ValueError, match='interval'):
        detect([], {'window_seconds': 60}, '2026-11-01T10:00:00+00:00', '2026-11-01T10:02:00+00:00')
