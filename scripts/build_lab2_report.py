#!/usr/bin/env python3
"""Отчёт только из сохранённых расчётов и фактических доказательств среды."""
from pathlib import Path
import argparse
import datetime
import getpass
import hashlib
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def read_json(path, fallback=None):
    return json.loads(path.read_text()) if path.is_file() else fallback


def text(path):
    return path.read_text(errors='replace') if path.is_file() else '(доказательство отсутствует)\n'


def clean(value):
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value).replace('\r', '')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-vm', action='store_true')
    args = parser.parse_args()
    evidence = ROOT / 'evidence/lab2' / ('vm' if args.target_vm else 'local')
    data = read_json(ROOT/'metrics/lab2-data.json')
    baseline = read_json(ROOT/'metrics/baseline.json')
    ci = read_json(ROOT/'metrics/baseline_ci.json')
    parameters = read_json(ROOT/'metrics/training.json')
    majority = read_json(ROOT/'metrics/majority-baseline.json')
    robustness = read_json(ROOT/'metrics/robustness.json')
    cases = read_json(ROOT/'metrics/validation-cases.json')
    model = read_json(ROOT/'security/model-manifest-lab2-v1.json')
    errors = read_json(ROOT/'metrics/error-analysis.json')
    runtime = read_json(evidence/'runtime-security.json', {})
    tunnel = read_json(ROOT/'evidence/lab2/client/jupyter-tunnel.json', {})
    environment = read_json(evidence/'environment.json', {})
    bandit = read_json(evidence/'bandit.json', {})
    audit = read_json(evidence/'pip-audit.json', {})
    notebook = read_json(ROOT/'notebooks/02_baseline_robustness.ipynb')
    code_cells = [cell for cell in notebook['cells'] if cell['cell_type']=='code']
    junit = evidence/'tests.xml'
    if junit.is_file():
        suites=ET.parse(junit).getroot()
        totals={'tests':sum(int(s.get('tests',0)) for s in suites.iter('testsuite')),
                'failures':sum(int(s.get('failures',0))+int(s.get('errors',0)) for s in suites.iter('testsuite'))}
    else:totals={'tests':0,'failures':0}
    deps=audit.get('dependencies',[])
    vulnerabilities=sum(len(d.get('vulns',[])) for d in deps)
    skipped=sum('skip_reason' in d for d in deps)
    sha=hashlib.sha256((ROOT/'models/lab2-v1/model.skops').read_bytes()).hexdigest()
    checks={
        'Датасет соответствует SHA256 ЛР1': data['source_sha256']=='7d039a24a6083ed9ef0f806ebad56bbb976e3aeb8de05669173bfdc4996c239d',
        'Тексты между train, CI и test не пересекаются': data['group_overlap_count']==0,
        'Модель сохранена и SHA256 совпадает': sha==model['sha256']==baseline['model_sha256']==ci['model_sha256'],
        'Основная метрика и отдельный контроль CI сохранены': baseline['main_metric']=='f1_spam' and ci['role']=='fixed_ci_control',
        'Позитивная и минимум четыре негативные проверки прошли': len(cases)>=5 and all(row['passed'] for row in cases) and all(row['model_calls']==0 for row in cases if row['expected']!='valid prediction'),
        'Pytest прошёл без ошибок': totals['tests']>=5 and totals['failures']==0,
        'Bandit не содержит находок или ошибок сканирования': bool(bandit) and not bandit.get('results') and not bandit.get('errors') and text(evidence/'bandit.exitcode').strip()=='0',
        'pip-audit завершён без находок и пропусков': bool(deps) and vulnerabilities==0 and skipped==0 and text(evidence/'pip-audit.exitcode').strip()=='0',
        'Окружение соответствует requirements.txt': text(evidence/'requirements-observed.txt')==(ROOT/'requirements.txt').read_text(),
        'Эксперимент выполнен на 20 тестовых SMS': robustness['samples']==20 and set(robustness['variants'])=={'typos','case_and_whitespace'},
        'Notebook содержит выполненные ячейки без ошибок': len(code_cells)==9 and all(c.get('execution_count') is not None and not any(o['output_type']=='error' for o in c.get('outputs',[])) for c in code_cells),
    }
    if args.target_vm:
        checks.update({
            'ML-работа выполнена от mluser': environment.get('user')=='mluser' and environment.get('uid') not in {0,None},
            'Notebook выполнен Jupyter на целевой VM': notebook['metadata'].get('validation',{}).get('jupyter_kernel_start_verified') is True and notebook['metadata']['validation'].get('execution_user')=='mluser',
            'Внешний эталон модели принадлежит root и закрыт для записи': runtime.get('reference_owned_by_root_read_only') is True,
            'Сохранённая модель загружается; изменение копии обнаружено': runtime.get('model_load_and_prediction_ok') is True and runtime.get('model_tamper_detected') is True,
            'Jupyter привязан к loopback и требует аутентификацию': runtime.get('jupyter_host')=='127.0.0.1' and runtime.get('jupyter_authentication_enabled') is True and runtime.get('unauthenticated_api_status') in {302,401,403},
            'Доступ через SSH-туннель проверен': tunnel.get('unauthenticated_api_status') in {302,401,403},
            'Каталоги данных и модели закрыты для остальных': all(value in text(evidence/'system/file-permissions.txt') for value in [
                'mluser mluser 750 /home/mluser',
                'mluser mluser 700 /home/mluser/ml-project/data/raw',
                'mluser mluser 700 /home/mluser/ml-project/models',
                'mluser mluser 400 /home/mluser/ml-project/models/lab2-v1/model.skops',
                'root root 444 /var/lib/ml-lab/model-integrity/lab2-v1.json',
            ]),
        })
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    scope='Целевая Ubuntu VM, пользователь mluser' if args.target_vm else 'Проверка в среде подготовки; не подтверждает выполнение на целевой VM'
    lines=[
        '# Лабораторная работа №2. Базовая NLP-модель и устойчивость входов',
        f'Сформировано: {now}. Среда: **{scope}**.',
        'Репозиторий: https://github.com/VaisouI/NLP. Модель — TF-IDF + LogisticRegression для англоязычных SMS; классы ham и spam. Вход — объект с единственным строковым полем text, выход — prediction и model_version.',
        '## Данные, решения и достаточность',
        'Источник: UCI SMS Spam Collection, https://archive.ics.uci.edu/dataset/228/sms+spam+collection, DOI 10.24432/C5CC84. Один текстовый признак и две метки. Исходный файл не изменён.',
        f"SHA256: `{data['source_sha256']}`. Исходных объектов: {data['raw_profile']['records']}; ham: {data['raw_profile']['classes']['ham']}, spam: {data['raw_profile']['classes']['spam']}. Пропусков и пустых текстов: {data['raw_profile']['missing_cells']} и {data['raw_profile']['empty_texts']}.",
        f"Исключено недопустимых входов: {data['removed_invalid_inputs']} ({data['invalid_input_exclusions']}); удалено повторов нормализованного текста сверх первого: {data['removed_normalized_duplicates']}. Осталось {data['retained_records']}: {data['retained_classes']}. Метки не изменялись, пропуски не заполнялись, ресэмплинг классов не выполнялся.",
        'Управляющие символы U+0091…U+0096 встречаются в старом корпусе; такие строки отклоняются той же политикой, что вход предсказания. NFKC, casefold и объединение пробелов используются для сравнения текстов; первое вхождение каждой группы сохраняется.',
        'Объёма и представленности обоих классов достаточно для учебной линейной модели и отдельных оценок, но корпус старый, англоязычный и несбалансированный. Нет идентификаторов пользователей и времени: гарантируется отсутствие одинаковых нормализованных текстов между выборками, но не всех возможных связей источника. Представленность современного и русскоязычного спама не установлена.',
        '## Разделение и обучение',
        f"Seed = {baseline['seed']}. Стратифицированные train/CI/test около 60/20/20; SHA256 схемы разделения: `{data['split_sha256']}`. Пересечений нормализованных текстов: {data['group_overlap_count']}.",
        '| Выборка | Всего | ham | spam |', '|---|---:|---:|---:|',
    ]
    for name,info in data['splits'].items():lines.append(f"| {name} | {info['records']} | {info['classes'].get('ham',0)} | {info['classes'].get('spam',0)} |")
    lines += [
        'Словарь TF-IDF и IDF обучены только на train. Предобработка одинакова при fit, оценке и предсказании. class_weight=balanced учитывает дисбаланс в функции потерь. Параметры заданы заранее; по тесту ничего не настраивалось.',
        '```json',json.dumps(parameters['configuration'],ensure_ascii=False,indent=2),'```',
        f"Время обучения: {parameters['training_seconds']:.6f} с; признаков в словаре: {parameters['features_learned']}; scikit-learn: {parameters['sklearn_version']}. Сохранены параметры, время, версия, fingerprint кода и исходный commit: `{model.get('source_commit')}`.",
        '## Качество',
        'Основная метрика — binary F1 для spam, zero_division=0. Precision, recall и F1 показаны по классам; macro-F1 усредняет классы поровну.',
        '| Модель / выборка | Accuracy | F1 spam | Macro-F1 | Balanced accuracy |', '|---|---:|---:|---:|---:|',
    ]
    for name,m in [('TF-IDF + LR, test',baseline['metrics']),('Всегда ham, test',majority),('TF-IDF + LR, CI',ci['metrics'])]:
        lines.append(f"| {name} | {m['accuracy']:.6f} | {m['f1_spam']:.6f} | {m['macro_f1']:.6f} | {m['balanced_accuracy']:.6f} |")
    lines += ['| Класс | Precision | Recall | F1 | Support |','|---|---:|---:|---:|---:|']
    for name,m in baseline['metrics']['per_class'].items():lines.append(f"| {name} | {m['precision']:.6f} | {m['recall']:.6f} | {m['f1-score']:.6f} | {int(m['support'])} |")
    lines += [
        '![Матрица ошибок](../figures/lab2/confusion_matrix.png)',
        f"Порядок строк и столбцов: ham, spam. Матрица: `{baseline['metrics']['confusion_matrix']}`. Отложенный тест: {baseline['samples']} SMS. `metrics/baseline.json` — независимый тест, `metrics/baseline_ci.json` — отдельный неизменяемый контроль для повторных проверок ЛР3. Они автоматически не перезаписываются.",
        '### Примеры ошибочных решений',
        f"Всего ошибок: {errors['total_errors']}. Тексты не публикуются; номер строки позволяет сверить пример в приватной копии исходного корпуса. Длина и покрытие словаря описывают ошибку, но не доказывают её причину.",
        '| Строка источника (с 0) | Истинный класс | Предсказание | Символов | Ненулевых признаков | Score spam |','|---|---|---|---:|---:|---:|',
    ]
    for row in errors['examples']:lines.append(f"| {row['source_row']} | {row['expected']} | {row['predicted']} | {row['characters']} | {row['known_nonzero_features']} | {row['decision_score_spam']:.4f} |")
    lines += [
        'Ham → spam — ложное срабатывание, spam → ham — пропуск спама. Лексическая модель не моделирует намерение автора; короткие сообщения и необычные формулировки требуют отдельного анализа. Дальнейшие изменения следует проверять на CI/валидации, не подбирая параметры по финальному тесту.',
        'В data/processed/lab2/error-analysis-private.json приватного архива приведены исходные тексты этих примеров и пять наибольших по абсолютному значению вкладов TF-IDF × коэффициент LR. Положительный вклад увеличивает score spam, отрицательный уменьшает. Это разбор вычисленного решения, а не доказательство реального намерения автора.',
        '## Позитивные и негативные проверки',
        'Рабочие пределы: 4096 кодовых точек и 16384 байта UTF-8 до и после NFKC/casefold/пробельной нормализации. Это больше максимальной длины корпуса и ограничивает обработку одного SMS. Null, NaN/Inf, неверный тип, лишние поля, управляющие символы и невалидный Unicode отклоняются. В демонстрации пределы уменьшены до 64/96; больших файлов не создавалось.',
        '| Случай | Ожидается | Фактически | Вызовов модели | Результат |','|---|---|---|---:|---|',
    ]
    for row in cases:lines.append(f"| {row['case']} | {row['expected']} | {json.dumps(row['actual'],ensure_ascii=False)} | {row['model_calls']} | {'PASS' if row['passed'] else 'FAIL'} |")
    lines += [
        f"Pytest: {totals['tests']} тестов, ошибок/падений: {totals['failures']}. Проверяются форма ответа, известный расчёт метрик, отсутствие утечки, неизменность baseline, контроль загрузки и валидация до обращения к модели. Полный JUnit XML и вывод — в приватном архиве.",
        'CLI читает максимум 65536 байт JSON. Проверка уже созданного Python-объекта не предотвращает расход памяти до вызова функции; потоковый HTTP body limit относится к ЛР4.',
        '## Эксперимент с изменёнными входами',
        'Фиксированный seed, 20 сообщений из теста: 10 ham и 10 spam. Опечатки — перестановка двух букв максимум в трёх словах. Предполагается сохранение смысла и метки. Исходный файл не изменялся; приватная копия преобразований включена в архив. Параметры модели после эксперимента не подбирались.',
        '| Вариант | Изменилось ответов | Доля изменений | F1 spam | Среднее абсолютное изменение decision score |','|---|---:|---:|---:|---:|',
        f"| Исходные | 0 | 0 | {robustness['original_metrics']['f1_spam']:.6f} | 0 |",
    ]
    for name,m in robustness['variants'].items():lines.append(f"| {name} | {m['changed_predictions']} | {m['prediction_change_rate']:.4f} | {m['metrics']['f1_spam']:.6f} | {m.get('mean_absolute_decision_score_shift',0):.6f} |")
    atypical=robustness['atypical_input']
    lines += [
        '![Эксперимент](../figures/lab2/robustness.png)',
        'Регистр и пробелы нормализуются. Нулевая доля смены класса на этой малой выборке не доказывает устойчивость; изменение decision_function отражает чувствительность численного решения, а не калиброванную вероятность.',
        f"Нетипичный вход: синтетическая строка только из эмодзи, {atypical['characters']} кодовых точек. Вход допустим по схеме; результат `{atypical['prediction']}`, ненулевых TF-IDF-признаков {atypical['nonzero_tfidf_features']}. Формальный OOD-детектор не реализован. Проверка формы не устанавливает принадлежность обучающему распределению.",
        'Предложено отдельно оценить покрытие словаря и механизм отказа на валидационной выборке, расширить эксперимент типичными опечатками и современными SMS. Этот эксперимент не является доказательством устойчивости ко всем adversarial-атакам.',
        '## Защита данных, модели и Jupyter',
        f"Модель `{model['file']}`, {model['bytes']} байт, формат skops. SHA256: `{model['sha256']}`. До десериализации проверяются размер, SHA256, версия scikit-learn и отсутствие неизвестных типов. Автоматического доверия к содержимому артефакта нет; загружается только собственная модель.",
        'Обученный TF-IDF и классификатор сохранены вместе. Нормализация — версионированная функция в src/preprocessing.py, её правила и конфигурация фиксируются вместе с моделью. Хэш не доказывает корректность обучения; root остаётся доверенной границей.',
        'Модель, исходные SMS, индексы разбиения, приватные примеры и журналы исключены из публичного Git. Для преподавателя они передаются в lab2-results.zip через закрытую учебную платформу. В Git находятся код, обезличенные результаты, хэши и Notebook.',
        '### Фактическая проверка среды',
        '```json', json.dumps(runtime if args.target_vm else {'scope':'preparation','target_vm_security':'not yet verified'},ensure_ascii=False,indent=2),'```',
    ]
    if args.target_vm:
        lines += ['```json',json.dumps(tunnel,indent=2),'```','```text',clean(text(evidence/'system/file-permissions.txt')).rstrip(),'```',
                  '```text',clean(text(evidence/'system/listening-ports.txt')).rstrip(),'```']
    lines += [
        'Jupyter работает от mluser на loopback с включённой аутентификацией. Вывод содержит только факт настройки, HTTP-код отказа без токена и проверку SSH-туннеля. Значение токена и приватный SSH-ключ в отчёт не включаются.' if args.target_vm else 'Защита Jupyter, внешний root-эталон и SSH-туннель должны быть проверены на целевой VM. Этот подготовительный отчёт не подтверждает их.',
        '## Bandit, зависимости и версии',
        f"Bandit: находок {len(bandit.get('results',[]))}, ошибок сканирования {len(bandit.get('errors',[]))}. Исключения и nosec не используются. Применимых находок для исправления нет при успешном отчёте.",
        f"pip-audit: пакетов {len(deps)}, уязвимостей {vulnerabilities}, пропусков {skipped}. Проверка относится к известным уязвимостям на дату запуска; фиксация версий не заменяет аудит.",
        '```json',json.dumps(environment,ensure_ascii=False,indent=2),'```',
        '## Итог проверок', '| Проверка | Результат |','|---|---|',
    ]
    for name,passed in checks.items():lines.append(f"| {name} | {'PASS' if passed else 'ТРЕБУЕТ ПРОВЕРКИ'} |")
    lines += [
        '## Команды воспроизведения',
        '```bash','python -m src.cli train','python -m src.cli evaluate','python -m src.cli robustness','python -m src.cli validate','python -m pytest tests/ -q','python -m bandit -r src/',
        "printf '%s' '{\"text\":\"Project lab2 meeting tomorrow at noon\"}' | python -m src.cli predict",'sha256sum models/lab2-v1/model.skops','```',
        'После клонирования восстановите models/ из приватного архива преподавателя. Автоматическая замена установленного baseline другим обучением запрещена. Подготовку и сбор фактических доказательств выполняет scripts/codespaces/run_lab2.sh в сохранённом Codespace ЛР1.',
        'Материалы ЛР1 сохранены в docs/VM_REPORT.md и notebooks/01_dataset_analysis.ipynb. Для ЛР2 сдаётся этот отчёт, notebooks/02_baseline_robustness.ipynb, metrics/, код и приватный архив с артефактом.',
    ]
    summary={'scope':scope,'target_vm':args.target_vm,'checks':checks,'all_checks_passed':all(checks.values()),'generated_at_utc':now}
    (evidence/'summary.json').parent.mkdir(parents=True,exist_ok=True)
    (evidence/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    target=ROOT/'docs/LAB2_REPORT.md' if args.target_vm else evidence/'LAB2_PREPARATION_REPORT.md'
    content='\n\n'.join(lines)+'\n'
    content=re.sub(r'(?m)^(\|[^\n]*\|)\n\n(?=\|)', r'\1\n', content)
    target.write_text(content)
    print(target)
    if args.target_vm and not summary['all_checks_passed']:
        for name,passed in checks.items():
            if not passed:print('REVIEW:',name)
        raise SystemExit('Target VM report has incomplete checks')


if __name__ == '__main__':
    main()
