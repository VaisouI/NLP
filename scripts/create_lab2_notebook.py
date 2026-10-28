#!/usr/bin/env python3
"""Создаёт воспроизводимый Notebook; реальные SMS в выводы не попадают."""
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]


def main():
    cells = []
    md = lambda value: cells.append(nbf.v4.new_markdown_cell(value))
    code = lambda value: cells.append(nbf.v4.new_code_cell(value))
    md('''# ЛР2. Базовая модель обнаружения SMS-спама и проверка входов

Направление — NLP; UCI SMS Spam Collection, DOI 10.24432/C5CC84.
Модель — TF-IDF и логистическая регрессия. Пользователь передаёт объект `{"text": "..."}`,
получает `ham` или `spam`. Готовые результаты находятся в сохранённых выводах ячеек.

Исходный датасет и артефакт модели не публикуются в Git. Выводы содержат агрегаты,
обезличенные сведения об ошибках и синтетические проверки входов.''')
    md('''## Контекст и методика

SHA256 исходного файла сверяется с ЛР1 до чтения. Недопустимые по политике предсказания
строки исключаются; у повторных нормализованных текстов сохраняется первое вхождение.
Исходный файл не редактируется. Стратифицированные доли: 60% обучение, 20% фиксированный
контроль для будущего CI, 20% независимый тест; seed = 42.

Словарь и IDF обучаются только на train. Параметры заданы до просмотра тестовых метрик;
поиск гиперпараметров не выполняется. `class_weight="balanced"` меняет веса функции потерь,
а не число объектов. Основная метрика — бинарная F1 класса `spam`.

### Ограничения

Корпус 2011 года англоязычный, классы несбалансированы. В нём нет надёжных идентификаторов
пользователей и времени, поэтому исключается утечка одинаковых нормализованных текстов,
но нельзя гарантировать отсутствие всех связей источника. Достаточность оценивается
для учебной базовой модели; перенос на современный или русскоязычный спам не доказан.''')
    code('''from pathlib import Path
import sys, json, getpass, platform
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown

ROOT = next(p for p in [Path.cwd(), Path.cwd().parent] if (p / "config/lab2.json").is_file())
sys.path.insert(0, str(ROOT))
from src.integrity import verify_dataset, default_baseline
from src.splitting import prepare_splits
from src.training import run_training
from src.robustness import run_robustness
from src.validation_demo import run_validation_demo
from src.artifacts import preferred_reference
from src.prediction import SmsPredictor

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "figure.dpi": 120, "savefig.dpi": 180})
FIGURES = ROOT / "figures/lab2"
FIGURES.mkdir(parents=True, exist_ok=True)
print("Пользователь:", getpass.getuser(), "; Python:", platform.python_version())
print("Эталон данных:", default_baseline())
for name, digest in verify_dataset(ROOT).items():
    print("OK", digest, name)''')
    md('''## Данные и разделение

Контрольные символы, пустой текст, невалидный Unicode и превышения размера отклоняются
одинаково в обучающих данных и при предсказании. NaN, Inf и null не заменяются строками
или нулями. Пропуски исходного корпуса отсутствуют. Все решения фиксируются ниже.''')
    code('''frame, indices, data = prepare_splits(ROOT)
display(pd.DataFrame({"Проверка": ["Исходные SMS", "Пропуски", "Точные дубликаты сверх первого", "Исключённые некорректные входы", "Удалённые нормализованные повторы", "Осталось SMS", "Пересечение групп между выборками"],
                      "Количество": [data["raw_profile"]["records"], data["raw_profile"]["missing_cells"], data["raw_profile"]["duplicate_rows_excess"], data["removed_invalid_inputs"], data["removed_normalized_duplicates"], data["retained_records"], data["group_overlap_count"]]}))
split_table = pd.DataFrame([{"Выборка": name, "SMS": info["records"], "ham": info["classes"].get("ham", 0), "spam": info["classes"].get("spam", 0)} for name, info in data["splits"].items()])
display(split_table)
print("Причины исключений:", data["invalid_input_exclusions"])
print("Версия данных:", data["dataset_version"])
print("SHA256 разделения:", data["split_sha256"])''')
    md('''## Обучение и сохранение

`run_training` обучает модель при первом запуске и сохраняет весь TF-IDF, словарь, IDF
и классификатор в `models/lab2-v1/model.skops`. Повторный запуск проверяет и использует
уже сохранённую модель; существующий baseline автоматически не заменяется.
Нормализация NFKC → casefold → объединение пробелов не имеет обучаемых параметров
и применяется одной функцией при fit, оценке и предсказании.

Skops загружается после проверки размера, SHA256 и версии scikit-learn.
Дополнительные неизвестные типы не разрешаются автоматически.''')
    code('''training = run_training(ROOT)
display(pd.DataFrame([{"Параметр": key, "Значение": str(value)} for key, value in training["parameters"]["configuration"].items()]))
print("Модель использована повторно:", training["reused_existing_model"])
print("Время исходного обучения, с:", training["parameters"]["training_seconds"])
print("Число выученных признаков:", training["parameters"]["features_learned"])
print("SHA256 модели:", training["manifest"]["sha256"])
print("Размер модели, байт:", training["manifest"]["bytes"])''')
    md('''## Оценка на независимом тесте

Положительный класс — `spam`. Precision, recall и F1 показаны по классам; macro-F1
усредняет классы поровну. Нулевые делители обрабатываются как 0. Контроль CI хранится
в `metrics/baseline_ci.json`, независимый тест — в `metrics/baseline.json`.''')
    code('''test = training["metrics"]["test"]
ci = training["metrics"]["ci"]
display(pd.DataFrame([
    {"Модель / выборка": "TF-IDF + LogisticRegression, test", **{key: test[key] for key in ["samples", "accuracy", "f1_spam", "macro_f1", "balanced_accuracy"]}},
    {"Модель / выборка": "Всегда ham, test", **{key: training["dummy"][key] for key in ["samples", "accuracy", "f1_spam", "macro_f1", "balanced_accuracy"]}},
    {"Модель / выборка": "TF-IDF + LogisticRegression, CI control", **{key: ci[key] for key in ["samples", "accuracy", "f1_spam", "macro_f1", "balanced_accuracy"]}},
]).round(4))
display(pd.DataFrame(test["per_class"]).T.round(4))
cm = test["confusion_matrix"]
fig, ax = plt.subplots(figsize=(6.8, 5.2), layout="constrained")
ax.imshow(cm, cmap="Blues", vmin=0)
ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["ham", "spam"], yticklabels=["ham", "spam"],
       xlabel="Предсказанный класс", ylabel="Истинный класс", title=f"Матрица ошибок: {test['samples']} тестовых SMS")
for i in range(2):
    for j in range(2):
        ax.text(j, i, str(cm[i][j]), ha="center", va="center", fontsize=18, color="white" if cm[i][j] > max(map(max, cm)) / 2 else "black")
fig.savefig(FIGURES / "confusion_matrix.png")
plt.show()''')
    md('''### Разбор ошибок

Ниже показаны идентификаторы строк, истинные и предсказанные классы, длина и число
ненулевых TF-IDF-признаков. Текст SMS не публикуется. По этим данным можно описать
случаи ошибки, но нельзя установить её причину без отдельного анализа.''')
    code('''errors = pd.DataFrame(training["errors"])
if len(errors):
    display(errors.drop(columns=["interpretation"]))
print("Всего ошибок:", sum(test["confusion_matrix"][i][j] for i in range(2) for j in range(2) if i != j))
print("Типы ошибок: ham → spam означает ложное срабатывание; spam → ham — пропущенный спам.")''')
    md('''## Эксперимент с изменёнными входами

Фиксированные 20 SMS тестовой выборки: 10 ham и 10 spam. Для каждой создаются версии
с изменённым регистром и пробелами и с перестановкой двух букв максимум в трёх словах.
Вторая операция предполагается сохраняющей смысл и метку; это ограничение эксперимента.
Изменения выполняются в памяти и отдельной приватной копии, исходный файл не меняется.
После наблюдения этих результатов параметры модели не подбираются.''')
    code('''robustness = run_robustness(ROOT)
rows = [{"Вариант": "original", "Изменилось ответов": 0, "Доля изменений": 0.0, "F1 spam": robustness["original_metrics"]["f1_spam"], "Среднее |Δ score|": 0.0}]
for name, result in robustness["variants"].items():
    rows.append({"Вариант": name, "Изменилось ответов": result["changed_predictions"], "Доля изменений": result["prediction_change_rate"], "F1 spam": result["metrics"]["f1_spam"], "Среднее |Δ score|": result["mean_absolute_decision_score_shift"]})
display(pd.DataFrame(rows).round(4))
fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
labels = ["Исходные", "Регистр и пробелы", "Опечатки"]
values = [row["F1 spam"] for row in rows]
bars = ax.bar(labels, values, color=["#245A81", "#245A81", "#C58A19"], width=.55)
ax.set(ylim=(0, 1.12), ylabel="F1 класса spam", title=f"Устойчивость на {robustness['samples']} выбранных SMS")
ax.grid(axis="y", alpha=.2); ax.set_axisbelow(True)
for bar, value, row in zip(bars, values, rows):
    ax.text(bar.get_x() + bar.get_width()/2, value + .025, f"F1={value:.3f}\\nсмен ответов: {row['Изменилось ответов']}/20", ha="center", va="bottom")
fig.savefig(FIGURES / "robustness.png")
plt.show()
print("Score — LogisticRegression.decision_function для spam, не калиброванная вероятность.")
print("Результат относится к выбранным 20 сообщениям, а не ко всему корпусу или всем атакам.")''')
    md('''### Нетипичный вход

Синтетический текст только из эмодзи отличается от обычного англоязычного SMS.
Проверяется реакция, но без формального критерия распределения это не объявляется
доказанным OOD-примером или работающим OOD-детектором.''')
    code('''display(pd.DataFrame([robustness["atypical_input"]]).T.rename(columns={0: "Результат"}))''')
    md('''## Проверка входов до вызова модели

Рабочие пределы — 4 096 кодовых точек Unicode и 16 384 байта UTF-8 до и после
нормализации. Они превышают максимальную длину исходного корпуса, но ограничивают
объём обработки одного SMS. Для демонстрации используются меньшие пределы 64/96:
входы превышают их лишь на небольшое число символов или байтов.

Типы и форма проверяются до предобработки и вызова классификатора. У каждого отказа
фиксируется счётчик вызовов модели. Проверка Python-объекта не защищает от его
предварительной загрузки в память; CLI отдельно ограничивает чтение JSON 65 536 байтами,
потоковое ограничение HTTP будет добавлено в ЛР4.''')
    code('''cases = run_validation_demo(ROOT)
display(pd.DataFrame([{**row, "actual": json.dumps(row["actual"], ensure_ascii=False)} for row in cases]))
print("Успешно:", sum(row["passed"] for row in cases), "/", len(cases))
print("Pytest и Bandit запускаются автоматически скриптом; полные отчёты включены в архив.")''')
    md('''## Контроль сохранённого артефакта

Загружается только собственный файл модели. Эталон SHA256 хранится отдельно в security/;
скрипт стенда дополнительно устанавливает его вне проекта с владельцем root и правами
только для чтения. Последующая проверка защиты и Jupyter фиксируется в отчёте VM.
Неизвестные типы skops запрещены. Хэш не доказывает качество модели или надёжность её источника.''')
    code('''predictor = SmsPredictor.from_project(ROOT)
print("Использованный эталон модели:", preferred_reference(ROOT))
print("Проверка загрузки:", predictor.predict({"text": "Project lab2 meeting tomorrow at noon"}))
print("Повторный SHA256 датасета:", bool(verify_dataset(ROOT)))
display(Markdown(f"""## Основные результаты и выводы

После исключения {data['removed_invalid_inputs']} недопустимых строк и {data['removed_normalized_duplicates']} повторов осталось **{data['retained_records']} SMS**.
На независимом тесте: **accuracy {test['accuracy']:.4f}, F1 spam {test['f1_spam']:.4f}**.
У постоянного прогноза ham F1 spam = {training['dummy']['f1_spam']:.4f}.

Регистр и пробелы изменили {robustness['variants']['case_and_whitespace']['changed_predictions']}/20 ответов,
опечатки — {robustness['variants']['typos']['changed_predictions']}/20.
Эти результаты не доказывают устойчивость ко всем атакам. Для дальнейшей проверки
предлагается отдельный корпус опечаток и оценка отказа при низком покрытии словаря.
В этой работе порог такого отказа не подбирался.
"""))''')
    md('''## Воспроизведение

```bash
python -m src.cli train
python -m src.cli evaluate
python -m src.cli robustness
python -m src.cli validate
python -m pytest tests/ -q
python -m bandit -r src/
printf '%s' '{"text":"Project lab2 meeting tomorrow at noon"}' | python -m src.cli predict
```

Артефакт модели передаётся преподавателю в приватном архиве. После клонирования
репозитория с уже установленным baseline восстановите models/ из этого архива;
baseline автоматически не заменяется новым обучением.''')
    notebook = nbf.v4.new_notebook(cells=cells, metadata={
        'kernelspec': {'name': 'ml-lab', 'display_name': 'Python (ml-lab)', 'language': 'python'},
        'language_info': {'name': 'python'},
        'validation': {'jupyter_kernel_start_verified': False, 'method': 'not executed yet'},
    })
    nbf.validate(notebook)
    path = ROOT / 'notebooks/02_baseline_robustness.ipynb'
    nbf.write(notebook, path)
    print(path)


if __name__ == '__main__':
    main()
