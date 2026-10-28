#!/usr/bin/env python3
"""Интерпретирует фактические слушатели внутри гостевой VM."""
import ipaddress
import json
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
directory = root / 'evidence/vm/system'
directory.mkdir(parents=True, exist_ok=True)
output = subprocess.check_output(['ss', '-H', '-tulpn'], text=True)
rows = []
for line in output.splitlines():
    fields = line.split(None, 6)
    if len(fields) < 6:
        continue
    protocol, address = fields[0], fields[4]
    host, _, port_text = address.rpartition(':')
    port = int(port_text) if port_text.isdigit() else -1
    process_match = re.search(r'users:\(\("([^\"]+)', line)
    process = process_match.group(1) if process_match else 'не указан'
    try:
        loopback = ipaddress.ip_address(host.strip('[]').split('%')[0]).is_loopback
    except ValueError:
        loopback = False
    reason = 'Требуется отдельная проверка назначения процесса'
    classified = False
    if protocol == 'tcp' and port == 22 and process in {'sshd', 'systemd'}:
        reason, classified = 'SSH для удалённой разработки; гостевой порт ограничен UFW, QEMU публикует только loopback клиента', True
    elif port == 53 and loopback and process.startswith(('systemd-resolv', 'dnsmasq')):
        reason, classified = 'Локальный DNS resolver необходим для apt, PyPI и разрешения имён', True
    elif protocol == 'udp' and port in {68, 546} and process.startswith(('systemd-network', 'dhclient')):
        reason, classified = 'DHCP-клиент необходим для адреса и сети VM', True
    elif port == 8888 and protocol == 'tcp' and loopback and process.startswith(('python', 'jupyter')):
        reason, classified = 'Jupyter для Notebook; привязка только к loopback, доступ через SSH-туннель', True
    elif protocol == 'tcp' and loopback and process == 'containerd':
        reason, classified = 'Локальный служебный порт containerd, зависимости Docker; динамический порт оставлен на loopback и не публикуется наружу', True
    elif port == 323 and protocol == 'udp' and loopback and process.startswith('chronyd'):
        reason, classified = 'Локальное управление синхронизацией времени; служба нужна для корректного времени и TLS', True
    rows.append({'protocol': protocol, 'address': address, 'process': process, 'loopback': loopback, 'reason': reason, 'classified': classified})
lines = ['| Протокол | Адрес и порт | Процесс | Назначение и решение |', '|---|---|---|---|']
for row in rows:
    lines.append(f"| {row['protocol']} | `{row['address']}` | {row['process']} | {row['reason']}. {'Оставлен' if row['classified'] else 'Нужен разбор'}. |")
(directory / 'ports-analysis.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
(directory / 'ports-analysis.json').write_text(json.dumps({'rows': rows, 'all_classified': bool(rows) and all(row['classified'] for row in rows)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('\n'.join(lines))

