# Лабораторная № 1: защищённый NLP-проект

Проект — классификация англоязычных SMS на ham и spam. Вход — текст, результат —
метка класса; пользователь — разработчик фильтра сообщений. В следующих лабораторных
исходной моделью могут быть TF–IDF и логистическая регрессия. В работе № 1 обучение
модели не требуется.

## Запуск в Codespaces

Используется отдельная Ubuntu 24.04 VM с аппаратным ускорением QEMU/KVM внутри
Codespaces. На Windows не устанавливаются программы. Администратор VM — labadmin,
разработчик — mluser без sudo и группы Docker. VS Code в браузере служит IDE на клиенте.

Загрузите lab1-codespaces.sh в корень Codespace и выполните:

```bash
bash lab1-codespaces.sh
```

Подробности и независимая serial-консоль: [START_CODESPACES.md](docs/START_CODESPACES.md).
Окончательный отчёт создаётся после реальных проверок: [VM_REPORT.md](docs/VM_REPORT.md).
До запуска сценария этот файл отсутствует и системные результаты не считаются подтверждёнными.
Предварительные проверки среды подготовки сохранены отдельно в evidence/local/ и
не заменяют доказательства из VM.

## Датасет и распределение

[UCI SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/sms+spam+collection),
DOI [10.24432/C5CC84](https://doi.org/10.24432/C5CC84).
Авторы: Tiago Almeida и José María Gómez Hidalgo, 2011. Указанная UCI лицензия — CC BY 4.0.
Тип — текст UTF-8; один исходный признак text, целевая метка target, два класса.
Исходный файл — 477 907 байт; ZIP — 203 415 байт.

| Класс | Сообщений | Доля |
|---|---:|---:|
| ham | 4 827 | 86,60% |
| spam | 747 | 13,40% |

Всего 5 574 сообщения, отношение численности классов — 6,46:1. Найдено 403 избыточные
повторные строки и 415 повторных нормализованных текстов сверх первого вхождения.
Пропуски и пустые тексты отсутствуют. Датасет не балансировался и не очищался.
При последующем разбиении нужно группировать одинаковые нормализованные тексты.
Accuracy постоянного прогноза ham равна 86,60%; нужны precision, recall и F1 класса spam,
macro-F1, balanced accuracy и матрица ошибок. Возраст корпуса ограничивает переносимость.

![Распределение классов](figures/class_distribution.png)

Анализ: [01_dataset_analysis.ipynb](notebooks/01_dataset_analysis.ipynb).

## Воспроизведение Python-части

Внутри Ubuntu, обычным пользователем:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_dataset.py
python scripts/check_integrity.py
python -m unittest discover -s tests -v
python -m pip_audit
python -m ipykernel install --user --name ml-lab
python -m jupyter nbconvert --execute --to notebook --inplace --ExecutePreprocessor.kernel_name=ml-lab notebooks/01_dataset_analysis.ipynb
```

При первом развёртывании на VM зависимости разрешаются из requirements.in, проверяются
и фактически установленные версии фиксируются в requirements.txt. Исходный список среды
подготовки сохраняется в docs/requirements-preparation.txt. Дальнейшее воспроизведение
использует итоговый lockfile VM. Фиксация версий и pip check не заменяют pip-audit.
Аудит сообщает о известных уязвимостях на момент запроса, а не гарантирует их отсутствие.

## Контроль целостности

SHA256 основного файла data/raw/SMSSpamCollection:

```text
7d039a24a6083ed9ef0f806ebad56bbb976e3aeb8de05669173bfdc4996c239d
```

```bash
sha256sum data/raw/SMSSpamCollection
sha256sum --check security/SHA256SUMS
python scripts/check_integrity.py --require-protected-baseline
python scripts/tamper_demo.py
```

Проверка выполняется до чтения данных и никогда не обновляет эталон сама.
В VM эталон дополнительно хранится вне проекта в /var/lib/ml-lab/integrity/,
каталог root:root 0755, файлы root:root 0444. Негативная проверка меняет один байт
временной копии и должна обнаружить изменение. Исходный файл не меняется.
Хэш не подтверждает достоверность источника, правильность меток или отсутствие
отравления до фиксации снимка. Root способен заменить системный эталон.

## Структура и секреты

Требуемые каталоги: data/, notebooks/, src/, models/, tests/. Дополнительно:
security/ — эталоны и модель угроз; scripts/ — автоматизация; docs/ — отчёты;
evidence/vm/ — реальные журналы Ubuntu; evidence/client/ — проверки с клиента Codespaces.

.gitignore исключает .venv, .env, приватные ключи, кэши, исходные данные, модели и .labvm/.
.env может содержать пароли и API-ключи; коммит распространяет их через историю и клоны.
.gitignore не удаляет уже созданные коммиты: опубликованные секреты требуют отзыва/ротации.
Все VM-диски, NoCloud seed и закрытые SSH-ключи остаются в приватной .labvm/ и не входят
в сдаваемый архив. Для контроля SSH в отчёт включаются только выводы проверок и права файлов.

## Мини-модель угроз и сдача

В [security/THREAT_MODEL.md](security/THREAT_MODEL.md) зафиксирована исходная модель угроз.
Таблица с фактическим статусом SSH, UFW, данных и зависимостей формируется в docs/VM_REPORT.md.
Для предложенных мер явно сохраняется статус предложения.

Нужно сдать ссылку на свой Git-репозиторий, Notebook, requirements.txt, .gitignore,
README и отчёт. После запуска материалы также собраны в lab1-results.zip.
Файл docs/LAB1_REPORT.md относится к предварительной подготовке; основной итоговый
отчёт после запуска — docs/VM_REPORT.md. Публикация в GitHub выполняется отдельно:
ссылка на Codespace не заменяет ссылку на репозиторий. При работе из Blank-шаблона
используйте Publish to GitHub в Source Control. Приватному репозиторию предоставляется
доступ преподавателю.

Остальные сценарии Windows сохранены для альтернативного стенда; в Codespaces они
не используются. Доступность sudo, KVM и текущих сетевых ресурсов проверяет launcher.
Полный запуск в конкретном Codespace подтверждается только его фактическими журналами.
