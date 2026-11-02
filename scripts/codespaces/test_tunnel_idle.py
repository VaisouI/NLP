#!/usr/bin/env python3
"""Изолированный CI-тест двух SSH-туннелей; не запускать на целевой VM."""

from pathlib import Path
import contextlib
import http.server
import importlib.util
import json
import os
import pwd
import socket
import subprocess
import tempfile
import threading
import time

source = Path(__file__).with_name("lab4-fix-access.py")
spec = importlib.util.spec_from_file_location("lab4_access", source)
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps({"status": "healthy", "model_version": "lab2-v1"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port):
    try:
        return access.health(port)["status"]
    except (OSError, ValueError):
        return "unreachable"


privsep = Path("/run/sshd")
created = not privsep.exists()
if created:
    privsep.mkdir(mode=0o755)
try:
    with tempfile.TemporaryDirectory(prefix="lab4-ssh-regression-", dir="/run") as tmp:
        p = Path(tmp)
        state = p / ".labvm"
        state.mkdir(mode=0o700)
        for name in ["host", "client"]:
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(p / name)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        ssh_port = free_port()
        forward_port = free_port()
        known = p / "known_hosts"
        known.write_text(f"[127.0.0.1]:{ssh_port} " + (p / "host.pub").read_text())
        daemon = p / "sshd_config"
        daemon.write_text(f"""Port {ssh_port}
ListenAddress 127.0.0.1
HostKey {p / "host"}
PidFile {p / "sshd.pid"}
AuthorizedKeysFile {p / "client.pub"}
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
PermitRootLogin prohibit-password
AllowUsers {pwd.getpwuid(os.getuid()).pw_name}
AllowTcpForwarding local
PermitOpen 127.0.0.1:8000
GatewayPorts no
LogLevel VERBOSE
""")
        shared = p / "shared-control"
        config = state / "ssh_config"
        config.write_text(f"""Host ml-lab
 HostName 127.0.0.1
 Port {ssh_port}
 User {pwd.getpwuid(os.getuid()).pw_name}
 IdentityFile {p / "client"}
 IdentitiesOnly yes
 UserKnownHostsFile {known}
 StrictHostKeyChecking yes
 ControlMaster auto
 ControlPersist 1
 ControlPath {shared}
""")
        subprocess.run(["/usr/sbin/sshd", "-t", "-f", str(daemon)], check=True)
        http = http.server.ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        with (p / "sshd.log").open("w") as log:
            sshd = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(daemon)], stdout=log, stderr=log)
            control = access.control_socket(state, forward_port)
            try:
                time.sleep(0.15)
                base = ["ssh", "-F", str(config)]
                with (p / "client.log").open("w") as client_log:
                    bootstrap = subprocess.run(
                        base + ["ml-lab", "true"], stdout=subprocess.DEVNULL, stderr=client_log, timeout=10
                    )
                if bootstrap.returncode:
                    raise RuntimeError(
                        "Test SSH setup failed: "
                        + (p / "client.log").read_text()
                        + " / "
                        + (p / "sshd.log").read_text()
                    )
                subprocess.run(
                    base
                    + [
                        "-f",
                        "-N",
                        "-o",
                        "ExitOnForwardFailure=yes",
                        "-L",
                        f"127.0.0.1:{forward_port}:127.0.0.1:8000",
                        "ml-lab",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                old_initial = request(forward_port)
                time.sleep(2.3)
                old_idle = request(forward_port)
                control, made = access.ensure_tunnel(state, forward_port)
                fixed_initial = request(forward_port)
                time.sleep(2.3)
                fixed_idle = request(forward_port)
                reused_control, reused_created = access.ensure_tunnel(state, forward_port)
                result = {
                    "test": "isolated loopback sshd and HTTP health server; idle timeout shortened to 1 second",
                    "old_initial": old_initial,
                    "old_after_idle": old_idle,
                    "fixed_initial": fixed_initial,
                    "fixed_after_idle": fixed_idle,
                    "fixed_reused_same_controller": control == reused_control and reused_created is False,
                    "bind_address": "127.0.0.1",
                    "source_sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
                }
                assert old_initial == "healthy" and old_idle == "unreachable", result
                assert fixed_initial == fixed_idle == "healthy" and result["fixed_reused_same_controller"], result
                print(json.dumps(result, indent=2))
            finally:
                if control:
                    subprocess.run(
                        base + ["-S", str(control), "-O", "exit", "ml-lab"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                subprocess.run(base + ["-O", "exit", "ml-lab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                sshd.terminate()
                sshd.wait(timeout=5)
                http.shutdown()
                http.server_close()
                if control:
                    with contextlib.suppress(OSError):
                        control.parent.rmdir()
finally:
    if created:
        with contextlib.suppress(OSError):
            privsep.rmdir()
