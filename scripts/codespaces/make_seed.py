#!/usr/bin/env python3
"""NoCloud seed для новой VM. Закрытые ключи остаются в приватном каталоге .labvm."""
import json
import os
import sys
import uuid
from pathlib import Path

state = Path(sys.argv[1]).resolve()
instance_path = state / 'instance-id'
if not instance_path.exists():
    instance_path.write_text('ml-lab-' + uuid.uuid4().hex + '\n')
public = ' '.join((state / 'client_key.pub').read_text().strip().split()[:2])
host_public = ' '.join((state / 'host_key.pub').read_text().strip().split()[:2])
configuration = {
    'users': [
        {'name': 'labadmin', 'gecos': 'Lab administrator', 'groups': ['sudo'],
         'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'shell': '/bin/bash', 'lock_passwd': True,
         'ssh_authorized_keys': [public]},
        {'name': 'mluser', 'gecos': 'ML development user',
         'shell': '/bin/bash', 'lock_passwd': True, 'ssh_authorized_keys': [public]},
    ],
    'disable_root': True,
    'ssh_pwauth': False,
    'ssh_deletekeys': True,
    'ssh_keys': {'ed25519_private': (state / 'host_key').read_text(), 'ed25519_public': host_public},
    'ssh': {'emit_keys_to_console': False},
    'write_files': [
        {'path': '/etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf',
         'owner': 'root:root', 'permissions': '0644',
         'content': '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin labadmin --noclear %I $TERM\n'},
        {'path': '/var/lib/ml-lab/managed-by-lab1', 'owner': 'root:root',
         'permissions': '0444', 'content': 'codespaces-qemu-lab1\n'},
    ],
    'runcmd': [
        ['systemctl', 'daemon-reload'],
        ['systemctl', 'restart', 'serial-getty@ttyS0.service'],
    ],
}
(state / 'user-data').write_text('#cloud-config\n' + json.dumps(configuration, ensure_ascii=False, indent=2) + '\n')
(state / 'meta-data').write_text('instance-id: ' + instance_path.read_text().strip() + '\nlocal-hostname: ml-lab\n')
os.chmod(state / 'user-data', 0o600)
os.chmod(state / 'meta-data', 0o600)

