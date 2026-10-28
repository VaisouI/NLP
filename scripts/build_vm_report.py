#!/usr/bin/env python3
"""Создаёт отчёт только из существующих журналов целевой виртуальной машины."""
from __future__ import annotations

import datetime as dt
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VM = ROOT / 'evidence/vm'
CLIENT = ROOT / 'evidence/client' if (ROOT / 'evidence/client').is_dir() else ROOT / 'evidence/windows'
SYSTEM = VM / 'system'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8-sig', errors='replace').strip() if path.is_file() else ''


def main() -> int:
    if not SYSTEM.is_dir():
        raise SystemExit('Отсутствуют результаты collect_security.sh; отчёт VM не создан.')
    ufw = read(SYSTEM / 'ufw-status.txt')
    ssh_config = read(SYSTEM / 'sshd-effective-root.txt')
    user_proof = read(CLIENT / 'ssh-login-after.txt')
    root_proof = read(CLIENT / 'root-login-denied.txt')
    audit_path = VM / 'pip-audit.json'
    audit = json.loads(read(audit_path)) if audit_path.is_file() else {}
    dependencies = audit.get('dependencies', [])
    vulnerable = [d for d in dependencies if d.get('vulns')]
    skipped = [d for d in dependencies if d.get('skip_reason')]
    integrity_log = read(VM / 'integrity.log')
    checks = {
        'Основная работа от mluser': 'mluser' in user_proof and 'uid=0(' not in user_proof,
        'Новая SSH-сессия по ключу после UFW': bool(user_proof),
        'Запрет root: эффективный конфиг и отклонённый вход': 'permitrootlogin no' in ssh_config and 'Permission denied' in root_proof and read(CLIENT / 'root-login.exitcode') == '255',
        'Парольная SSH-аутентификация отключена': 'passwordauthentication no' in ssh_config and 'kbdinteractiveauthentication no' in ssh_config,
        'UFW активен, входящие запрещены, SSH ограничен': 'Status: active' in ufw and 'deny (incoming)' in ufw and 'LIMIT' in ufw and 'Logging: on (high)' in ufw,
        'pip-audit завершён без известных уязвимостей и пропусков': bool(dependencies) and not vulnerable and not skipped and read(VM / 'pip-audit.exitcode') == '0',
        'Защищённый эталон и SHA256 проверены': '/var/lib/ml-lab/integrity/dataset-manifest.json' in integrity_log and 'FAIL' not in integrity_log and integrity_log.count('OK ') == 3,
        'Изменение одного байта обнаружено': 'PASS:' in read(VM / 'tamper-demo.log'),
        'Обновления не требуют дополнительной перезагрузки': (SYSTEM / 'collected-at.txt').is_file() and not (SYSTEM / 'REBOOT_REQUIRED.txt').exists(),
        'Версия VS Code зафиксирована на клиенте': bool(read(CLIENT / 'vscode-version.txt')),
    }
    if CLIENT.name == 'client':
        checks['Независимая serial-консоль VM проверена'] = 'ML_CONSOLE_USER=labadmin' in read(CLIENT / 'console-proof.txt')
        checks['Jupyter отвечает на loopback внутри VM'] = 'JUPYTER_LOOPBACK_OK' in read(VM / 'jupyter-health.txt')
    port_analysis_path = SYSTEM / 'ports-analysis.json'
    if port_analysis_path.is_file():
        checks['Назначение каждого слушающего порта разобрано'] = bool(json.loads(read(port_analysis_path)).get('all_classified'))
    manifest = json.loads(read(ROOT / 'security/dataset-manifest.json'))
    profile = json.loads(read(ROOT / 'evidence/dataset-profile.json'))
    notebook = json.loads(read(ROOT / 'notebooks/01_dataset_analysis.ipynb'))
    code_cells = [cell for cell in notebook.get('cells', []) if cell.get('cell_type') == 'code']
    first_output = ''.join(''.join(output.get('text', [])) for output in (code_cells[0].get('outputs', []) if code_cells else []))
    checks['Notebook выполнен Jupyter от mluser'] = (
        notebook.get('metadata', {}).get('validation', {}).get('jupyter_kernel_start_verified') is True
        and bool(code_cells) and all(cell.get('execution_count') is not None for cell in code_cells)
        and all(output.get('output_type') != 'error' for cell in code_cells for output in cell.get('outputs', []))
        and 'mluser' in first_output
    )
    checks['Git-репозиторий создан обычным пользователем VM'] = 'mluser' in read(VM / 'git-checks.log') and '.gitignore' in read(VM / 'git-checks.log')
    lines = [
        '# Результаты проверки целевой виртуальной машины', '',
        f'Отчёт сформирован: {dt.datetime.now(dt.timezone.utc).isoformat()} (UTC).', '',
        f'Этот документ сформирован из файлов evidence/vm/ и evidence/{CLIENT.name}/. '
        'Выполнение скриптов само по себе не заменяет просмотр фактических выводов и анализ ненужных сервисов.', '',
        '| Проверка | Результат |', '|---|---|',
    ]
    lines[4:4] = [
        '## Проект и данные', '',
        'Направление — NLP. Задача будущей модели — классификация англоязычных SMS '
        'на ham и spam. Вход — текст сообщения, выход — метка класса; пользователь — '
        'разработчик фильтра сообщений. Обучение модели относится к следующим работам.', '',
        f"Источник: [{manifest['source']['name']}]({manifest['source']['page_url']}); "
        f"DOI {manifest['source']['doi']}; лицензия по UCI — CC BY 4.0. "
        'Один текстовый признак, одна целевая метка, два класса.', '',
        '| Класс | Количество | Доля, % |', '|---|---:|---:|',
        *[f"| {label} | {profile['classes'][label]} | {profile['class_percent'][label]:.4f} |" for label in ['ham', 'spam']], '',
        f"Всего {profile['records']} сообщений. Отношение численности классов "
        f"{profile['majority_to_minority_ratio']:.4f}:1. "
        f"Избыточных точных повторных строк: {profile['duplicate_rows_excess']}; "
        f"пропущенных значений: {profile['missing_cells']}. "
        'Исходный файл не балансировался и не очищался. '
        'При дальнейшем разбиении одинаковые нормализованные тексты должны попадать в одну группу. '
        'Accuracy константного прогноза ham составляет 86,60%; для обучения нужны метрики по классам.', '',
        '![Распределение классов](../figures/class_distribution.png)', '',
        'Анализ выполнен в notebooks/01_dataset_analysis.ipynb. '
        'Основной файл занимает 477 907 байт, исходный ZIP — 203 415 байт. '
        'Возраст корпуса ограничивает перенос результатов на современный спам.', '',
        '## Окружение и разделение привилегий', '',
        ('Лабораторная Ubuntu 24.04 работает в отдельной QEMU/KVM VM внутри Codespaces. '
         'IDE — VS Code в браузере на стороне Codespaces; ключ SSH создаётся на этом клиенте. '
         if CLIENT.name == 'client' else
         'Лабораторная Ubuntu 24.04 работает в отдельной VM. IDE и SSH-клиент находятся на Windows. ')
        +
        'Административная учётная запись выполняет системные действия, mluser выполняет '
        'Python-проверки без sudo и членства в группе Docker. '
        'Пакеты, SSH и UFW настраиваются внутри VM.', '',
    ]
    lines.extend(f'| {name} | {"Подтверждено журналами" if passed else "Требуется проверка / исправление"} |' for name, passed in checks.items())
    lines.extend(['', '## Мини-модель угроз: статус на целевой VM', '',
        '| Актив | Угроза | Последствие | Контрмера и фактический статус |', '|---|---|---|---|'])
    threat_rows = [
        ('SSH', 'Удалённый вход root или подбор пароля', 'Компрометация VM', 'Ключи, запрет root и паролей, UFW limit', checks['Запрет root: эффективный конфиг и отклонённый вход'] and checks['Парольная SSH-аутентификация отключена'] and checks['UFW активен, входящие запрещены, SSH ограничен']),
        ('Датасет', 'Подмена файлов относительно выбранного снимка', 'Обучение на изменённых данных', 'Проверка SHA256 до загрузки, отдельный эталон root, негативная проверка', checks['Защищённый эталон и SHA256 проверены'] and checks['Изменение одного байта обнаружено']),
        ('Зависимости', 'Использование пакетов с известными уязвимостями', 'Нарушение доступности или выполнение кода', 'Зафиксированные версии, pip check и pip-audit; отсутствие известных находок не гарантирует безопасность', checks['pip-audit завершён без известных уязвимостей и пропусков']),
    ]
    for asset, threat, consequence, measure, implemented in threat_rows:
        lines.append(f'| {asset} | {threat} | {consequence} | {measure}. Статус: {"подтверждено журналами" if implemented else "требуется проверка"}. |')
    lines.extend([
        '| Git | Утечка секретов | Компрометация сервисов | .gitignore подготовлен; история проверяется отдельно. Хранилище секретов и автоматический secret scanning предложены. |',
        '| Данные и оценка модели | Попадание дубликатов в обучение и тест | Завышенная оценка качества | Дубликаты выявлены. Разделение по группам и проверка отсутствия пересечения предложены для следующей лабораторной. |',
        '| Jupyter / Docker | Необоснованное открытие сетевых портов | Доступ к данным или вычислениям | Скрипт Jupyter использует 127.0.0.1 и стандартную аутентификацию; Docker-контейнеры и API в работе № 1 не публикуются. Запуск Jupyter и внешний повторный тест проверяются отдельно. |',
        '', '## Интерпретация слушающих портов', '',
        'Сравните фактические строки ниже с назначением каждого процесса. SSH на 0.0.0.0/[::] '
        'предназначен для удалённого доступа и ограничен UFW. DNS stub на 127.0.0.53/127.0.0.54 '
        'обслуживает локальное разрешение имён. DHCP на UDP/68 может быть нужен сети VM. '
        'Jupyter допускается на 127.0.0.1:8888 и через SSH-туннель. Unix-сокет Docker не является TCP-портом. '
        'Любой другой слушатель требует отдельного объяснения или отключения. Публикация Docker-портов '
        'может обходить обычные правила UFW, поэтому проверяйте также docker ps.', '',
    ])
    for title, path in [
        ('Версии компонентов', SYSTEM / 'versions.txt'),
        ('Правила UFW', SYSTEM / 'ufw-status.txt'),
        ('Слушающие сокеты и процессы', SYSTEM / 'listening-ports.txt'),
        ('Контейнеры и опубликованные порты', SYSTEM / 'docker-ports.txt'),
        ('SSH: вход по ключу', CLIENT / 'ssh-login-after.txt'),
        ('SSH: отказ root', CLIENT / 'root-login-denied.txt'),
        ('SSH: проверка синтаксиса', SYSTEM / 'sshd-syntax.txt'),
        ('Пользователь и права публичного ключа', SYSTEM / 'user-and-key-permissions.txt'),
        ('Сохранённая SSH-сессия', CLIENT / 'ssh-existing-session.txt'),
        ('pip-audit', VM / 'pip-audit-summary.txt'),
        ('SHA256 и защищённый эталон', SYSTEM / 'sha256.txt'),
        ('Негативная проверка целостности', VM / 'tamper-demo.log'),
        ('Доступные обновления после установки', SYSTEM / 'apt-upgradable-final.txt'),
        ('Обновляемые пакеты до установки', SYSTEM / 'apt-upgradable-before.txt'),
        ('Обновляемые пакеты после установки', SYSTEM / 'apt-upgradable-after.txt'),
        ('VS Code на клиенте', CLIENT / 'vscode-version.txt'),
    ]:
        lines.extend([f'## {title}', '', '```text', read(path) or '(файл отсутствует или вывод пустой)', '```', ''])
    if (SYSTEM / 'ports-analysis.md').is_file():
        lines.extend(['## Анализ фактической сетевой поверхности', '', read(SYSTEM / 'ports-analysis.md'), ''])
    if (CLIENT / 'console-proof.txt').is_file():
        lines.extend(['## Независимая serial-консоль', '', '```text', read(CLIENT / 'console-proof.txt'), '```', ''])
    lines.extend(['## Известные ограничения', '',
        'Хэш фиксирует снимок, а не достоверность источника или качество меток. '
        'Компрометация root позволяет изменить эталон. UFW limit ограничивает частоту новых подключений '
        'и не защищает от всех распределённых атак. Полный кодовый аудит зависимостей не выполнялся. '
        'Ненулевое число обновляемых пакетов необходимо объяснить по журналам apt.', '',
        'Удалённый Git-репозиторий и фактическая ссылка на него фиксируются после публикации. '
        'Отчёт не подтверждает наличие удалённого репозитория.', '',
    ])
    report = ROOT / 'docs/VM_REPORT.md'
    report.write_text('\n'.join(lines), encoding='utf-8')
    archive_path = ROOT / 'evidence/vm-results.tar.gz'
    print('Created:', report)
    print('Created:', archive_path)
    for name, passed in checks.items():
        print(('PASS ' if passed else 'REVIEW ') + name)
    status = {'checks': checks, 'all_checks_passed': all(checks.values())}
    (VM / 'summary.json').write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # В архиве должен быть и итоговый статус, который создан после формирования отчёта.
    with tarfile.open(archive_path, 'w:gz') as archive:
        for relative in ['docs/VM_REPORT.md', 'evidence/vm', 'notebooks/01_dataset_analysis.ipynb', 'requirements.txt', 'figures', 'evidence/dataset-profile.json']:
            archive.add(ROOT / relative, arcname=relative)
        if CLIENT.is_dir():
            archive.add(CLIENT, arcname=f'evidence/{CLIENT.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
