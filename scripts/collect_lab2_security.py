#!/usr/bin/env python3
"""Системные доказательства ЛР2; модель и секреты в вывод не включаются."""
from pathlib import Path
import datetime
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.geteuid() != 0 or not Path('/run/systemd/system').is_dir():
        raise SystemExit('Run inside the Ubuntu VM as administrator')
    directory = ROOT / 'evidence/lab2/vm/system'
    directory.mkdir(parents=True, exist_ok=True)
    commands = {
        'users.txt': ['id', 'mluser'],
        'listening-ports.txt': ['ss', '-tulpn'],
        'ufw-status.txt': ['ufw', 'status', 'verbose'],
        'sshd-effective.txt': ['/usr/sbin/sshd', '-T', '-C', 'user=mluser,host=localhost,addr=127.0.0.1'],
        'file-permissions.txt': ['stat', '-c', '%U %G %a %n', '/home/mluser', str(ROOT), str(ROOT/'data/raw'),
                                 str(ROOT/'models'), str(ROOT/'models/lab2-v1/model.skops'),
                                 '/var/lib/ml-lab/model-integrity/lab2-v1.json'],
    }
    for name, command in commands.items():
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        (directory / name).write_text(result.stdout + result.stderr)
    observed = {
        'collected_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'platform': 'target Ubuntu VM; root collects system evidence; mluser performs ML work',
        'model_reference_mode': oct(Path('/var/lib/ml-lab/model-integrity/lab2-v1.json').stat().st_mode & 0o777),
    }
    (directory/'collected.json').write_text(json.dumps(observed,indent=2)+'\n')
    for path in directory.iterdir():path.chmod(0o644)
    directory.chmod(0o755)


if __name__ == '__main__':
    main()
