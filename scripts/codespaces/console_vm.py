#!/usr/bin/env python3
"""Независимая serial-консоль QEMU. Для интерактивного выхода нажмите Ctrl+]."""
from __future__ import annotations
import argparse
import os
import select
import socket
import sys
import termios
import time
import tty

parser = argparse.ArgumentParser()
parser.add_argument('socket_path')
parser.add_argument('--probe', action='store_true')
args = parser.parse_args()
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.connect(args.socket_path)
    if args.probe:
        connection.sendall(b'\r')
        time.sleep(0.5)
        connection.sendall(b'printf "ML_CONSOLE_USER=%s\\n" "$(id -un)"\r')
        deadline = time.monotonic() + 20
        next_command = time.monotonic() + 3
        output = bytearray()
        while time.monotonic() < deadline:
            if time.monotonic() >= next_command:
                connection.sendall(b'printf "ML_CONSOLE_USER=%s\\n" "$(id -un)"\r')
                next_command = time.monotonic() + 3
            ready, _, _ = select.select([connection], [], [], 0.5)
            if ready:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                output.extend(chunk)
                if b'ML_CONSOLE_USER=labadmin' in output:
                    break
        sys.stdout.write(output.decode('utf-8', errors='replace'))
        if b'ML_CONSOLE_USER=labadmin' not in output:
            raise SystemExit('Serial console probe did not confirm labadmin login')
    else:
        previous = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(sys.stdin.fileno())
            connection.sendall(b'\r')
            while True:
                ready, _, _ = select.select([sys.stdin, connection], [], [])
                if connection in ready:
                    data = connection.recv(65536)
                    if not data:
                        break
                    os.write(sys.stdout.fileno(), data)
                if sys.stdin in ready:
                    data = os.read(sys.stdin.fileno(), 1024)
                    if b'\x1d' in data:
                        break
                    connection.sendall(data)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, previous)
