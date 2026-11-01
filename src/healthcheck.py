"""Docker healthcheck не перезагружает модель и не требует API-секрета."""
import json
import urllib.request


def main() -> int:
    try:
        # Fixed loopback URL, not supplied by the caller or environment.
        with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2) as response:  # nosec B310
            body = json.loads(response.read(1024))
            return 0 if response.status == 200 and body == {'status': 'healthy', 'model_version': 'lab2-v1'} else 1
    except (OSError, ValueError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
