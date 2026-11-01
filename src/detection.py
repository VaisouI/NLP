"""Проверка правила по ограниченному интервалу обезличенных журналов."""
from datetime import datetime


def detect(records: list[dict], rule: dict, start: str, end: str) -> dict:
    beginning, ending = datetime.fromisoformat(start), datetime.fromisoformat(end)
    if beginning.tzinfo is None or ending.tzinfo is None or not 0 <= (ending - beginning).total_seconds() <= rule['window_seconds']:
        raise ValueError('Detection interval must fit the configured window')
    matching = [row for row in records if row.get('route') == rule['route'] and row.get('http_status') == rule['http_status']
                and beginning <= datetime.fromisoformat(row['timestamp']) <= ending]
    return {'rule_id': rule['rule_id'], 'start_utc': start, 'end_utc': end,
            'window_seconds': rule['window_seconds'], 'threshold': rule['threshold'],
            'observed': len(matching), 'triggered': len(matching) >= rule['threshold'],
            'request_ids': [row['request_id'] for row in matching]}
