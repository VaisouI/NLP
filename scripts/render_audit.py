#!/usr/bin/env python3
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit('Результат аудита отсутствует; проверьте stderr и доступность сервиса.')
result = json.loads(path.read_text(encoding='utf-8'))
dependencies = result.get('dependencies', []) if isinstance(result, dict) else result
vulnerable = [dependency for dependency in dependencies if dependency.get('vulns')]
skipped = [dependency for dependency in dependencies if dependency.get('skip_reason')]
print(f'Записей в аудите: {len(dependencies)}; уязвимых пакетов: {len(vulnerable)}; пропущено: {len(skipped)}.')
if vulnerable:
    print('| Библиотека | Версия | Уязвимость | Исправленные версии |')
    print('|---|---|---|---|')
    for dependency in vulnerable:
        for vulnerability in dependency['vulns']:
            fixes = ', '.join(vulnerability.get('fix_versions', [])) or 'не указаны; требуется отдельное решение'
            print(f"| {dependency['name']} | {dependency['version']} | {vulnerability['id']} | {fixes} |")
for dependency in skipped:
    print(f"НЕ ПРОВЕРЕНО: {dependency['name']}: {dependency['skip_reason']}")
print('Результат относится к известным уязвимостям на момент запроса, а не доказывает отсутствие уязвимостей.')

