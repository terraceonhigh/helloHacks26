"""Quickly inspect the local API without starting either UI."""
import argparse
import json
import os
import sys

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BASE_URL_ENV = "UBC_HUB_BASE_URL"
TIMEOUT_SECONDS = 30
COMMANDS = {
    "upcoming": ("GET", "/api/upcoming"),
    "announcements": ("GET", "/api/announcements"),
    "courses": ("GET", "/api/courses"),
    "connect-canvas": ("POST", "/api/connect/canvas"),
    "connect-prairielearn": ("POST", "/api/connect/prairielearn"),
}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL),
        help=f"API base URL (default: {BASE_URL_ENV} or {DEFAULT_BASE_URL})",
    )
    parser.add_argument("command", choices=COMMANDS)
    return parser


def endpoint_url(base_url, path):
    return f"{base_url.rstrip('/')}{path}"


def request_json(method, url):
    try:
        response = requests.request(method, url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        print(f"error: {method} {url}: {error}", file=sys.stderr)
        return 1

    if not 200 <= response.status_code < 300:
        print(f"error: {method} {url}: HTTP {response.status_code}", file=sys.stderr)
        return 1

    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(f"error: {method} {url}: response was not valid JSON", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    method, path = COMMANDS[args.command]
    return request_json(method, endpoint_url(args.base_url, path))


if __name__ == "__main__":
    raise SystemExit(main())
