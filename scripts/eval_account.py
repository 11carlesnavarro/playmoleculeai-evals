"""The eval account on the dev backend: check the login (or create a new account once).

set -a && . ./.env && set +a
uv run python scripts/eval_account.py check         # user info and default project
uv run python scripts/eval_account.py signup        # a code goes to PM_EMAIL
uv run python scripts/eval_account.py verify CODE
"""

import json
import os
import sys

import httpx

B = os.environ.get("PM_BACKEND_URL", "http://computer19.acellera.lan:8002") + "/v3"
EMAIL, PASSWORD = os.environ["PM_EMAIL"], os.environ["PM_PASSWORD"]


def login(c: httpx.Client) -> dict[str, str]:
    """The auth header. The cookies can be Secure, which httpx does not send over http: send them by hand."""
    csrf = c.get(f"{B}/auth/csrf").json()["csrf_token"]
    r = c.post(
        f"{B}/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"X-CSRF-Token": csrf, "Cookie": f"csrf_token={csrf}"},
    )
    r.raise_for_status()
    token = r.cookies["access_token"].strip('"').removeprefix("Bearer ")
    return {"Authorization": f"Bearer {token}"}


def get(c: httpx.Client, path: str, h: dict[str, str]):
    r = c.get(f"{B}{path}", headers=h)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    cmd = sys.argv[1]
    with httpx.Client(timeout=30) as c:
        if cmd == "signup":  # an email that matches no group email_patterns, or the account joins that group
            r = c.post(
                f"{B}/auth/signup",
                json={
                    "username": "pmai-evals",
                    "email": EMAIL,
                    "password": PASSWORD,
                    "institution_name": "Acellera",
                    "country": "Spain",  # PMView asks for it in a modal when it is empty
                    "city": "Barcelona",
                },
            )
            print(r.status_code, r.text)
        elif cmd == "verify":
            r = c.post(f"{B}/auth/verify/mail", json={"email": EMAIL, "code": sys.argv[2]}, headers=login(c))
            print(r.status_code, r.text)
        elif cmd == "check":
            h = login(c)
            print(json.dumps(get(c, "/auth/user-info", h), indent=2))
            print("default project:", json.dumps(get(c, "/default-project", h)))
        else:
            sys.exit(__doc__)
