# Запуск лабораторной на Windows

Сценарии предназначены для отдельной учебной VM Ubuntu 24.04. По умолчанию выделяются
2 vCPU, 4 ГБ RAM и виртуальный диск 30 ГБ. При необходимости передайте `-Cpus`, `-Memory`, `-Disk`.
На Windows должно быть достаточно свободных ресурсов; виртуализация Intel VT-x / AMD-V
должна быть включена в UEFI.

В этой версии выбран Multipass 1.17 или новее с поддержкой Windows Home/Pro через HCS.
Требования проверены по [документации Canonical](https://canonical.com/multipass/docs/latest/how-to-guides/install-multipass/)
и [описанию версии 1.17](https://github.com/canonical/multipass/releases/tag/v1.17.0).

## 1. Распаковать проект

Распакуйте архив так, чтобы получился каталог `ml-project`, например `C:\Labs\ml-project`.
Откройте Windows Terminal / PowerShell и перейдите в этот каталог:

```powershell
cd C:\Labs\ml-project
```

Исходный ZIP датасета и его файлы входят в комплект, но исключены из Git.
При получении проекта через Git вместо архива загрузчик скачает тот же снимок UCI и проверит хэши.

## 2. Установить системные компоненты Windows

Откройте PowerShell **от имени администратора**, перейдите в каталог проекта и запустите:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\prepare-windows.ps1
```

Сценарий включает Virtual Machine Platform, устанавливает OpenSSH Client при отсутствии,
включает ssh-agent и скачивает официальный стабильный MSI Multipass из репозитория Canonical.
Перед запуском MSI проверяется действительная Authenticode-подпись Canonical.
Установщик открывается обычным окном. Если потребуется, перезагрузите Windows самостоятельно.
Сценарий не перезагружает компьютер автоматически. `ExecutionPolicy Bypass` действует
только на этот процесс PowerShell и не меняет постоянную политику системы.

Если Multipass уже установлен, проверьте версию: `multipass version`.
Для этой инструкции используйте 1.17 или новее. При ручной установке используйте
[официальную страницу Canonical](https://canonical.com/multipass/install).

Установите [VS Code](https://code.visualstudio.com/download) от обычного пользователя.
После установки откройте новое окно PowerShell, чтобы обновился PATH.

## 3. Создать и настроить VM

В **обычном** PowerShell из каталога `ml-project`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start-lab.ps1
```

При первом запуске `ssh-keygen` предложит парольную фразу для нового приватного ключа.
Введите её на своей машине; `ssh-add` затем загрузит ключ в ssh-agent. Секрет не передаётся
в чат, на VM, в проект или в отчёт. Существующий ключ с тем же именем не перезаписывается.

Сценарий выполняет:

1. Создание Ubuntu 24.04 VM `ml-lab` и отдельного `mluser` без sudo и группы Docker.
2. Передачу публичного ключа через cloud-init и проверку ключа SSH-сервера.
3. Реальный вход `mluser` по ключу, перенос проекта и установку системных пакетов.
4. Проверку обновлений, обновление пакетов и перезапуск VM при необходимости.
5. Сохранение отдельного эталона SHA256 с владельцем root.
6. Проверку конфигурации SSH, запрет root и паролей, включение UFW и limit на фактическом SSH-порту.
7. Проверку новой SSH-сессии и отдельно — отказа root.
8. Установку venv и зависимостей от `mluser`, аудит и выполнение Notebook через Jupyter.
9. Сбор реальных выводов команд и создание `docs/VM_REPORT.md`.

Во время hardening сохраняется установленная SSH-сессия. Перед изменениями внутри VM
ставится таймер отката на 180 секунд: если новая сессия/отказ root не подтверждены,
конфигурация SSH восстанавливается, UFW отключается. После успешных проверок таймер отменяется.
Это механизм восстановления, а не доказательство успешной настройки.

`multipass shell` и `multipass exec` зависят от гостевого SSH. Они **не являются независимой
аварийной консолью**. Если преподаватель требует именно консоль гипервизора, используйте
вариант VirtualBox ниже. Поддерживайте доступ к GUI-консоли при ручной настройке VM.

Если запуск оборвался, сначала изучите `evidence/windows/setup-transcript.txt`.
При срабатывании отката результат hardening не считается подтверждённым. После исправления
можно повторить с `-Resume`; он переиспользует существующий проект без повторной распаковки:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start-lab.ps1 -Resume
```

Ограничение UFW относится и к административным SSH-подключениям Multipass. Не запускайте
много коротких SSH-команд подряд при отладке. Сценарий объединяет выгрузку результатов
в один архив, чтобы сократить число новых соединений.

## 4. Подключить VS Code и Jupyter

Файл SSH-конфигурации создан в `%USERPROFILE%\.ssh\config_ml-lab`.
В VS Code откройте Settings и укажите его полный путь в `Remote.SSH: Config File`.
Затем выполните `Remote-SSH: Connect to Host...`, выберите `ml-lab` и откройте
`/home/mluser/ml-project`. При первом подключении VS Code устанавливает удалённую часть IDE.

Для обычного SSH:

```powershell
ssh -F "$env:USERPROFILE\.ssh\config_ml-lab" ml-lab
```

Внутри VM выполните `id`: пользователь должен быть `mluser`, UID должен отличаться от 0.
Запуск Jupyter:

```bash
cd /home/mluser/ml-project
bash scripts/start_jupyter.sh
```

В другом окне Windows:

```powershell
ssh -F "$env:USERPROFILE\.ssh\config_ml-lab" -L 127.0.0.1:8888:127.0.0.1:8888 ml-lab
```

Откройте `http://127.0.0.1:8888`, введите текущий токен Jupyter и откройте Notebook.
Сохраните вывод `ss -tulpn` также во время работы Jupyter: он должен слушать `127.0.0.1:8888`.

## 5. Просмотреть доказательства

- `docs/VM_REPORT.md` — отчёт, составленный из реальных журналов VM и клиента.
- `evidence/vm/system/ufw-status.txt` — UFW.
- `evidence/vm/system/listening-ports.txt` — адреса, порты, процессы.
- `evidence/vm/system/versions.txt` — версии Python, pip, Git, Docker, Compose.
- `evidence/vm/system/apt-history.log` — реально установленные обновления.
- `evidence/vm/pip-audit.json` и `pip-audit-summary.txt` — аудит.
- `evidence/vm/system/sha256.txt` — хэши и права отдельного эталона.
- `evidence/windows/ssh-login-after.txt` — вход по ключу обычного пользователя.
- `evidence/windows/root-login-denied.txt` — отказ root; сопоставьте с эффективным конфигом.
- `evidence/vm/tamper-demo.log` — обнаружение изменения временной копии.

Проверьте каждый слушающий процесс. Локальный DNS stub нужен разрешению имён,
DHCP может быть нужен сети VM, SSH нужен доступу, Jupyter допускается только на loopback.
Для иного сервиса запишите конкретное обоснование либо отключите ненужную службу.
Не отключайте сетевую службу только по номеру порта без проверки её роли.

Скриншоты необязательны, если преподаватель принимает вывод команд, как указано в задании.
Ключевые файлы и отчёт уже содержат текстовые результаты. Кадр с токеном Jupyter
или приватным ключом для сдачи не используется.

## 6. Создать удалённый Git-репозиторий

Локальный репозиторий уже входит в комплект. Создайте свой пустой репозиторий на GitHub
или другом разрешённом сервисе, затем из каталога проекта:

```bash
git remote add origin URL_ВАШЕГО_ПУСТОГО_РЕПОЗИТОРИЯ
git add docs/VM_REPORT.md notebooks/01_dataset_analysis.ipynb
git commit -m "Add verified VM security results"
git push -u origin main
```

Для нового коммита укажите собственные Git name/email. Первоначальный технический коммит
помечен как автоматически подготовленный. Не добавляйте `.venv`, исходный датасет,
ключи и токены. Предоставьте преподавателю доступ к репозиторию, если он приватный.

## Вариант с полноценной GUI-консолью: VirtualBox

Если независимая консоль гипервизора является обязательной частью приёмки, установите
[VirtualBox](https://www.virtualbox.org/wiki/Downloads) и Ubuntu Server 24.04 из
[официального образа Ubuntu](https://releases.ubuntu.com/24.04/).
Создайте VM с 2 CPU, 4 ГБ RAM и диском 30 ГБ. При установке создайте отдельную
административную учётную запись, установите OpenSSH Server и сохраните доступ к её
GUI-консоли. Для связи используйте NAT с пробросом SSH или отдельную host-only сеть;
при NAT различайте клиентский проброшенный порт и гостевой порт 22 для UFW.

Далее от администратора внутри VM:

```bash
sudo adduser mluser
sudo install -d -o mluser -g mluser -m 0700 /home/mluser/.ssh
```

Создайте ключ на Windows через `ssh-keygen -t ed25519 -a 64`. На VM поместите **только**
содержимое `.pub` в `/home/mluser/.ssh/authorized_keys`, установите владельца `mluser`
и права 0600. Проверьте новый вход по ключу. Перенесите проект в `/home/mluser/ml-project`.
Оставьте действующую SSH-сессию и GUI-консоль открытыми.

Административные этапы из каталога проекта:

```bash
sudo bash scripts/install_system.sh
sudo -H -u mluser python3 scripts/download_dataset.py
sudo bash scripts/protect_baseline.sh
```

В SSH-сессии `mluser`: `touch /home/mluser/.lab1-key-verified`.
Из административной сессии:

```bash
sudo bash scripts/harden_vm.sh --key-login-verified
```

В течение 180 секунд проверьте новый вход `mluser` и отказ root с клиента.
После успешных проверок выполните из административной сессии:

```bash
sudo bash scripts/confirm_hardening.sh
```

От `mluser`: `bash scripts/setup_project.sh`.
От администратора: `sudo bash scripts/collect_security.sh`.
Клиентские доказательства сохраните в `evidence/windows/`, затем выполните
`.venv/bin/python scripts/build_vm_report.py`. В этом варианте ручные системные
шаги остаются обязательными; сценарий Multipass для этой VM не запускается.
