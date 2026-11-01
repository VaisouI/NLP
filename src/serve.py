"""Единственный Uvicorn worker; proxy headers и access log отключены."""
import argparse
import logging

import uvicorn

from src.api import create_app

CONTAINER_HOST = '0.0.0.0'  # nosec B104


def main():
    parser = argparse.ArgumentParser()
    # The all-interface choice is explicit for the container; host publication stays on loopback.
    parser.add_argument('--host', choices=['127.0.0.1', CONTAINER_HOST], default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger = logging.getLogger('ml_api')
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1, access_log=False,
                proxy_headers=False, server_header=False, timeout_keep_alive=5, timeout_graceful_shutdown=5,
                h11_max_incomplete_event_size=16384, ws='none', log_level='warning')


if __name__ == '__main__':
    main()
