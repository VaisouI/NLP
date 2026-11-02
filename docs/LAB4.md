# ЛР4. Защищённый API модели, веб-интерфейс и мониторинг

## Проект и модель

Сервис классифицирует **англоязычную SMS** как `ham` или `spam`. Используется
сохранённый Pipeline ЛР2: NFKC → casefold → свёртка пробелов → TF-IDF →
LogisticRegression. Версия модели — `lab2-v1`; новая архитектура не обучается.
Проверенная точка входа — `SmsPredictor`, одинаковая для CLI, CI и API.
Возвращается только класс, без произвольного score под видом вероятности.

На сохранённой Ubuntu VM launcher использует исходную модель ЛР2 и внешний
эталон `/var/lib/ml-lab/model-integrity/lab2-v1.json`. В GitHub Actions по протоколу
ЛР3 воспроизводится кандидат того же алгоритма на неизменном train; его метрика
проверяется на отдельном CI-контроле. Финальный test повторно не оценивается.
SHA сериализации каждого CI-запуска относится к его собственному артефакту.

## Быстрый запуск в существующем Codespace

Получите актуальную версию этого репозитория, затем из его корня:

```bash
bash scripts/codespaces/run_lab4.sh
```

Требуется сохранённая `.labvm/` ЛР1–ЛР2. Launcher возобновляет Ubuntu, переносит
исходный код, устанавливает зафиксированные зависимости в существующую `.venv`,
запускает тесты, Ruff, Bandit, pip-audit и реальную HTTP-демонстрацию от `mluser`.
Модель ЛР2, исходные SMS, SSH и правила UFW не перезаписываются.

Интерактивный API работает от `mluser` в `ml-lab4-api.service` на **VM
127.0.0.1:8000**. Системная служба ограничена 512 MiB, одним CPU и 64 tasks,
имеет `NoNewPrivileges`, read-only доступ к домашним каталогам и отдельный `/tmp`.
SSH перенаправляет **Codespace 127.0.0.1:18000 → VM 127.0.0.1:8000**.
Вкладка **Ports → 18000 → Visibility: Private → Open in Browser** открывает страницу
по HTTPS GitHub. При наличии GitHub CLI launcher сам устанавливает Private.
Не переводите учебный порт в Public.

Два разных случайных runtime-токена находятся в VM `.env.lab4`, mode 0600.
Приватная копия доступна в Codespace `.labvm/lab4.env`. Для формы скопируйте только
значение `ML_API_TOKEN` из этого файла. Значение `ML_METRICS_TOKEN` используется
отдельным сборщиком `/metrics`. Не отправляйте эти значения в чат, отчёт или Git.
Launcher их не печатает. Итоги VM собираются в `lab4-results.zip` без токенов,
дисков, SSH-ключей, модели и исходного датасета.

Остановка интерактивного сервиса с клиента Codespaces:

```bash
ssh -F .labvm/ssh_config ml-lab-admin 'sudo systemctl stop ml-lab4-api.service'
python3 scripts/codespaces/lab4-fix-access.py --port 18000 --stop
```

Если ссылка возвращает HTTP 502 после простоя, восстановите только доступ:

```bash
python3 scripts/codespaces/lab4-fix-access.py
```

Исправление создаёт отдельный transport-only SSH master без таймера общего
`ControlPersist 120`. Оно использует новый loopback-порт **18001**, проверяет
`/health`, сохраняет прежний API-токен и не переустанавливает окружение. Добавьте
18001 во вкладке Ports, оставьте Private и выберите протокол **HTTP** для
внутреннего сервиса. Внешняя ссылка GitHub остаётся **HTTPS**.
Если даже локальная проверка `/health` не проходит, helper завершится ошибкой,
не объявляя доступ восстановленным.
Регрессионный тест с настоящим локальным SSH-сервером:
[run 41421720322](https://github.com/VaisouI/NLP/actions/runs/41421720322).
Для короткого контролируемого теста idle-timeout уменьшен до 1 с: прежний туннель
стал недоступен после простоя, отдельный master сохранил доступ и корректно
использовался повторно. Это тест транспорта, а не переобучение модели.

## Локальный запуск из CLI без Notebook

После восстановления модели ЛР2 в `models/lab2-v1/model.skops`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --only-binary=:all: -r requirements.txt
python scripts/create_api_env.py
set -a
source .env.lab4
set +a
python -m src.serve --host 127.0.0.1 --port 8000
```

Файл секретов создаётся эксклюзивно с mode 0600: существующий файл не затирается.
Содержимое `.env*` исключено из Git. При отсутствии токенов, их совпадении или
недопустимой длине конфигурация завершается отказом. Реальные секреты не нужны CI:
сценарии создают временные случайные значения только на время проверки.

В CI вместо приватной исходной модели используются подготовленные артефакты:

```bash
python scripts/ci/lab3.py prepare
python scripts/ci/lab3.py data
python scripts/ci/lab3.py train
python scripts/ci/lab3.py model
export ML_MODEL_PATH="$PWD/artifacts/ci/model.skops"
export ML_MODEL_REFERENCE="$PWD/artifacts/ci/model-manifest.json"
python -m src.serve --host 127.0.0.1 --port 8000
```

Пути задаёт оператор через окружение, а не клиент HTTP. Модель загружается один
раз при старте отдельного persistent-процесса; перед десериализацией проверяются
размер и SHA256 относительно отдельного эталона. Затем проверяются версия
sklearn, конфигурация предобработки, допустимые типы skops и структура Pipeline.
Загрузка пользовательских моделей, файлов и произвольных путей через API отсутствует.
При ошибке хэша/загрузки сервер остаётся доступен для `/health`, но не готов к predict.

## Схема API

| Endpoint | Вход и доступ | Успешный ответ |
|---|---|---|
| `POST /predict` | `Authorization: Bearer <ML_API_TOKEN>`; UTF-8 JSON, ровно поле `text: string` | 200, `prediction`, `model_version`, `request_id` |
| `GET /health` | Без секрета; не содержит путей и деталей инфраструктуры | 200 только при готовности модели; иначе 503 |
| `GET /metrics` | Отдельный `Authorization: Bearer <ML_METRICS_TOKEN>` | 200, Prometheus text exposition |
| `GET /` | Страница на том же origin | HTML с формой |

Пример входа:

```json
{"text": "Are we still meeting for lunch tomorrow?"}
```

Схема успешного ответа (request_id генерируется сервером):

```json
{"prediction": "ham", "model_version": "lab2-v1", "request_id": "server-generated-hex-id"}
```

`request_id` также возвращается в `X-Request-ID`. Входящий одноимённый заголовок
не используется. Ошибки возвращают `error.code`, фиксированное понятное
`error.message` и `request_id`, без эха входа или traceback.

| HTTP | Причина |
|---|---|
| 400 | Невалидный JSON/UTF-8, повторные JSON-поля, NaN/Infinity, некорректный Content-Length |
| 401 | Отсутствующий или неверный токен; одинаковый ответ для обоих случаев |
| 408 | Истёк общий срок чтения тела |
| 413 | Превышен размер тела, исходного или нормализованного текста |
| 415 | Формат отличается от несжатого application/json |
| 422 | Пустой текст, неверный тип, null, лишние/недостающие поля, управляющие символы |
| 429 | Исчерпан лимит запросов; есть Retry-After |
| 503 | Модель не готова, занят inference-slot или исчерпан предел HTTP-запросов |
| 504 | Истёк серверный deadline предсказания; процесс вычисления завершён |

Роли и 403 в этом варианте не реализуются: используется один credential для
предсказаний и другой для наблюдаемости. Токены проверяются через constant-time
comparison, не передаются в URL, не сохраняются в логах и localStorage.

## Конкретные ограничения и освобождение ресурсов

Правила хранятся в `config/api.json`; пределы текста сохраняются из ЛР2 в
`config/lab2.json`, автоматически не расширяются ради API.

| Ограничение | По умолчанию | Обоснование и механизм |
|---|---:|---|
| HTTP body | 32 768 байт | Достаточно для одной SMS и JSON; счётчик при чтении потока до JSON-разбора |
| Текст | 4096 символов / 16 384 UTF-8 байта | Проверяется до и после NFKC/casefold/нормализации |
| Чтение тела | 3 с на весь поток | asyncio deadline, остановка чтения с 408 |
| HTTP-запросы одновременно | 16 | Входной ASGI middleware; лишний запрос получает 503 до чтения тела |
| Предсказания одновременно | 1, очередь 0 | Persistent worker и lock; занятый slot даёт 503 |
| Предсказание | 2 с | Deadline включает запись в pipe и чтение ответа; SIGKILL + wait/reap дочернего процесса |
| Старт/восстановление модели | 20 с | Отдельный deadline; неуспешный child тоже завершается и reap |
| Авторизованный predict | 10 запросов / 60 с | Sliding window для единственного credential; в том числе некорректные входы |
| Неверная аутентификация | 20 отказов / 60 с | Один дополнительный общий bounded bucket; далее 429 |
| Контейнер | 512 MiB, 1 CPU, 64 PID | Внешние лимиты Docker дополняют ограничения приложения |

Content-Length используется только как ранний shortcut. При его отсутствии или
занижении поток всё равно ограничен; это проверяется unit-тестами и настоящим
chunked HTTP-запросом. Уже полученный ASGI chunk может занимать память транспортного
буфера; приложение не накапливает всё тело и не копирует сверхлимитный chunk в
буфер JSON. Сжатые тела не распаковываются. Предел применяется также к escape-
представлению JSON: допустимая по числу символов SMS может быть отклонена, если её
конкретное HTTP-представление превышает 32 KiB.

Timeout клиента формы 10 с нужен только интерфейсу. Вычислительный timeout
реализован сервером: зависший child завершается, затем `wait()` освобождает его
ресурсы. Начинается фоновая загрузка проверенной модели в новый процесс. До
восстановления `/health` отвечает 503; после успешного старта готовность возвращается.
Модель не загружается для каждого запроса. При закрытии сервиса worker завершается.

Состояние rate limiter хранится в памяти одного серверного процесса. Перезапуск
API сбрасывает историю; несколько серверных workers потребовали бы общего
хранилища. `src.serve` поэтому запускает ровно один Uvicorn worker.
X-Forwarded-For не участвует в ключе limiter и не позволяет обойти ограничение.
Proxy headers отключены; доверенные внешние proxy в этой лабораторной не настраиваются.

## Веб-интерфейс

`static/index.html`, `app.js`, `style.css` отдаёт тот же API. В форме есть поле
текста и password-поле для ручного токена. Показаны ожидание, результат, неверный
токен, ошибка валидации, превышение лимита, неготовность и timeout.
Любой ответ выводится через `textContent`, без `innerHTML`; CSP разрешает только
собственные скрипт/стиль/соединения. Встроенных API-ключей, сторонних CDN и CORS `*`
нет. Отдельный CORS для same-origin страницы не требуется.

## Логи, метрики и правило обнаружения

Каждый HTTP-запрос создаёт JSON-запись: `timestamp`, `request_id`, нормализованный
`route`, `http_status`, `duration_ms`, `model_version`, `failure_type`.
Неизвестные маршруты записываются как `other`: ни URL query, ни произвольный путь,
ни SMS, IP, заголовки, API-токены и персональные данные в запись не попадают.
Стандартный Uvicorn access log отключён. Для API нет traceback в ответах и логах.

| Метрика | Labels | Назначение |
|---|---|---|
| `ml_api_requests_total` | route, status | Количество завершённых запросов, включая 4xx/5xx |
| `ml_api_request_duration_seconds` | route; технический le у bucket | Распределение длительности |
| `ml_api_rejections_total` | reason | Отказы валидации, аутентификации, лимитера, ёмкости, timeout |
| `ml_api_inference_total` | Нет | Число запросов, направленных worker |
| `ml_api_model_ready` | Нет | Готовность проверенной модели |

Пути и причины берутся из ограниченного набора. Request_id, текст, токен,
имена файлов и произвольные значения не используются в labels. `/metrics`
защищён отдельным Bearer-токеном; Prometheus может передавать его через
`authorization.credentials_file`. Сам Prometheus/Grafana не разворачивается:
для обязательной части сохранены реальные логи, метрики и результат правила.

`config/detection.json`: **не менее трёх HTTP 401 на /predict за интервал до 60 с**.
`src/detection.py` проверяет правило по журналам указанного временного интервала.
Это проверяемое правило и контролируемая демонстрация, а не внешний постоянно
работающий alert-сервис.

`scripts/ci/lab4.py` сначала подтверждает нормальное предсказание. Затем выполняет
отдельную серию ровно из трёх неверных токенов, сохраняет UTC-интервал и сравнивает
метрики до/после. Число 401 увеличивается на три, предсказания для этих входов
не вызываются. По JSON-журналам правило должно сработать. Дополнительно проверяются
10 разрешённых запросов и один 429 с малым демонстрационным окном **2 секунды**;
после ожидания окна проверяются успешные predict и health. Рабочее значение остаётся
**10/60 с**: уменьшение окна передаётся только окружению тестового процесса.

Приложение видит только запросы, дошедшие до ASGI. Отказы TLS, приватного GitHub
доступа и SSH до приложения в эти счётчики не входят: их следует наблюдать в
соответствующей платформе. HTTP 401/429 сами по себе не доказывают атаку на модель,
poisoning или ухудшение качества классификации.

## Контейнер и CI

`Dockerfile` использует официальный `python:3.12.16-slim-trixie`; точный Image ID
фиксируется отчётом CI. Тег фиксирован по версии, digest пока не закреплён.
Устанавливаются только 26 runtime-зависимостей из `requirements-runtime.txt`;
Jupyter, Playwright, pytest и инструменты аудита в runtime-образ не включены.
Код, модель и отдельный манифест принадлежат root и читаются приложением.
`USER 10001:10001`; реальная доступность записи в эталон проверяется при запуске.
`.dockerignore` работает как явный allowlist, исключая `.git`, `.venv`, секреты,
исходный корпус, отчёты и всё, что не требуется предсказанию.

После успешных команд prepare/data/train/model:

```bash
docker build --pull -t ml-project:lab3 .
docker run --rm --entrypoint id ml-project:lab3 -u
docker run --rm --init --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --pids-limit=64 \
  --memory=512m --cpus=1 --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --env-file .env.lab4 -p 127.0.0.1:8000:8000 ml-project:lab3
```

Имя `ml-project:lab3` оставлено для совместимости сохранённых команд CI ЛР3;
текущее содержимое образа включает API ЛР4. `HEALTHCHECK` обращается к `/health`
работающего процесса, не загружает вторую модель. Не применяются privileged и
Docker socket. Runtime-секреты передаются через отдельный локальный env-file,
не через Dockerfile или build arguments. Не выводите полный `docker inspect`
работающего контейнера в отчёт: его Config.Env содержит runtime-секреты.

Сохранены все обязательные проверки ЛР3: Ruff → Bandit → pytest → полный pip-audit
→ data gate → train → model gate → build → Trivy config/image и security gate
→ non-root/smoke. Добавлены HTTP/API/страница и проверка сервиса в контейнере.
GitHub Actions использует минимальное contents:read, полные SHA actions,
ограничение времени 25 мин и upload-artifact с `if: always()`.
Уязвимости не скрываются: pip-audit блокирует любую находку или пропуск,
Trivy — CRITICAL и неразрешённые UNKNOWN; ошибки базы/сканирования также отказ.
HIGH и ниже не означают отсутствие риска и сохраняются в исходном отчёте.

Для Bandit обоснованы только точечные B104/B310:
[`security/BANDIT_EXCEPTIONS.md`](../security/BANDIT_EXCEPTIONS.md).
Общих skips, continue-on-error и подавления обязательных кодов возврата нет.

## Автоматическое воспроизведение и сдача

```bash
python -m pytest tests/ -q
ruff check src/ tests/
python -m bandit -r src/
pip-audit -r requirements.txt
python scripts/ci/lab3.py data
python scripts/ci/lab3.py model
python -m playwright install --with-deps chromium
python scripts/ci/lab4.py local --screenshots
python scripts/ci/lab4.py container
```

Первые два gates требуют предварительных prepare/train и сохранённых артефактов.
Локальные тесты используют собственную небольшую модель и фиксированные примеры,
не скачивают UCI и не обучаются на всём корпусе.

Негативные тесты проверяют отсутствие/ошибку токена, неверную схему/тип, пустоту,
UTF-8, повторные поля, NaN/Infinity, формат, размер тела и нормализованного текста,
stream без/с ложным Content-Length, медленный stream, 429, параллелизм, смерть
worker, timeout загрузки, несовпадение SHA/версии модели. Проверяется отсутствие
предсказания для отклонённых входов, корректный HTTP-код и безопасные логи/labels.

Сдача: ссылка на репозиторий и успешный GitHub Actions run; код API/static/тестов,
Dockerfile/CI; `docs/LAB4.md` и фактический `docs/LAB4_REPORT.md`; artifact
`lab4-reports-<run_id>-<attempt>` со следующими материалами:

* pytest XML/текст, Ruff, Bandit, pip-audit, Trivy и сохранённые gates ЛР3;
* `local/http-cases.json`, `scenario.json`, `requests.jsonl`, `metrics-before.txt`,
  `metrics-after.txt`, `detection.json`, `integrity-probe.json`;
* `local/screenshots/success.png`, `unauthorized.png`, `browser-check.json`:
  настоящая страница в Chromium, поле токена очищено до снимка;
* `container/container-runtime.json`, HTTP-результаты, метрики и detection;
* SHA256 модели, версия и commit из `status.json` и манифеста кандидата.

CI-артефакты хранятся 30 дней; итоговый обезличенный архив также сохраняется в
`evidence/lab4/` для сдачи. Отдельные VM-проверки появляются только после запуска
launcher в существующем Codespace; результат GitHub Actions не объявляется
подтверждением выполнения команд в пользовательской VM.

## Первичные технические источники

* FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/
* Starlette ASGI middleware: https://starlette.dev/middleware/
* Uvicorn: https://uvicorn.dev/settings/
* Prometheus Python client: https://prometheus.github.io/client_python/
* Dockerfile reference: https://docs.docker.com/reference/dockerfile/
* GitHub Actions workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
