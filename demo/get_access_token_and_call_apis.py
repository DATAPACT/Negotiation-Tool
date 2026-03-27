"""Fetch negotiations for a provider account, obtaining a token first."""

import argparse
import getpass
import json
import sys

import requests


def login(base_url: str, username: str, password: str, timeout: float = 10.0) -> dict:
    base = base_url.rstrip("/")
    if base.endswith("/user/login/"):
        url = base
    elif base.endswith("/user/login"):
        url = base + "/"
    elif base.endswith("/negotiation-api"):
        url = base + "/user/login/"
    else:
        url = base + "/negotiation-api/user/login/"

    data = {"username": username, "password": password}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = requests.post(url, data=data, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def list_negotiations(base_url: str, account_id: str, token: str, timeout: float = 10.0) -> dict:
    base = base_url.rstrip("/")
    if base.endswith("/negotiation-api"):
        url = f"{base}/providers/{account_id}/negotiations"
    else:
        url = f"{base}/negotiation-api/providers/{account_id}/negotiations"

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_url", help="API base URL (e.g., https://dips.soton.ac.uk)")
    parser.add_argument("--username", help="Login user")
    parser.add_argument("--account_id", help="Provider account id to fetch negotiations for")
    parser.add_argument("--password", help="Password (omit to prompt)")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    password = args.password or getpass.getpass("Password: ")

    try:
        login_payload = login(
            base_url=args.base_url,
            username=args.username,
            password=password,
            timeout=args.timeout,
        )
        access_token = login_payload.get("access_token")
        if not access_token:
            raise RuntimeError("Login response missing access_token")

        payload = list_negotiations(
            base_url=args.base_url,
            account_id=args.account_id,
            token=access_token,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# python get_access_token_and_call_apis.py   --base_url  https://dips.soton.ac.uk     --username upcast_provider@example.com     --account_id 67879ad41985442bac981f86     --password upcastProvider138.