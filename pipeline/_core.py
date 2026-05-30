"""Core utilities: SDK root resolution, credential loading, TypeScript runner."""

import re
import subprocess
import json
import urllib.request
from pathlib import Path
from typing import Literal

from .config import (
    SDK_ROOT,
    CREDENTIALS_FILENAME,
    AUTH_FETCH_TIMEOUT_SEC,
    AUTH_USER_AGENT,
)


def _parse_dotenv(path: Path) -> dict:
    """Parse a .env file, stripping any outer quote wrapping on values."""
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        if not sep:
            continue
        val = val.strip()
        for q in ['"""', "'''", '"', "'"]:
            if val.startswith(q) and val.endswith(q) and len(val) >= len(q) * 2:
                val = val[len(q) : -len(q)]
                break
        result[key.strip()] = val
    return result


def _fetch_auth_token(cookie_str: str) -> str:
    """Fetch a fresh SNlM0e CSRF token from the NotebookLM page using saved cookies."""
    req = urllib.request.Request(
        "https://notebooklm.google.com/",
        headers={
            "User-Agent": AUTH_USER_AGENT,
            "Cookie": cookie_str,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=AUTH_FETCH_TIMEOUT_SEC) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    m = re.search(r'"SNlM0e"\s*:\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    raise RuntimeError(
        "Could not extract SNlM0e token from NotebookLM — cookies may be expired.\n"
        "Run: python pipeline/login.py"
    )


def load_credentials(
    mode: Literal["auto", "cookies", "patchright"] = "auto",
) -> dict:
    """Load credentials, returning ``{"mode": "cookies", "authToken": ..., "cookies": ...}``.

    * ``"patchright"`` — reads ``credentials.json`` saved by ``pipeline/login.py``.
    * ``"cookies"``   — reads ``NOTEBOOKLM_AUTH_TOKEN`` + ``NOTEBOOKLM_COOKIES`` from ``.env``.
    * ``"auto"``      — tries patchright first, falls back to cookies.
    """
    creds_file = SDK_ROOT / CREDENTIALS_FILENAME

    if mode == "patchright":
        if not creds_file.exists():
            raise RuntimeError(
                "credentials.json not found. Run the login script first:\n"
                "  python pipeline/login.py"
            )
        data = json.loads(creds_file.read_text(encoding="utf-8"))
        cookies = data["cookies"]
        auth_token = _fetch_auth_token(cookies)
        # Update the file with the fresh token for the TS SDK to pick up
        data["authToken"] = auth_token
        creds_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Credentials ready — token: {len(auth_token)} chars, cookies: {len(cookies)} chars")
        return {"mode": "cookies", "authToken": auth_token, "cookies": cookies}

    # cookies / auto: read from .env
    env = _parse_dotenv(SDK_ROOT / ".env")
    has_cookies = bool(env.get("NOTEBOOKLM_AUTH_TOKEN") and env.get("NOTEBOOKLM_COOKIES"))

    if mode == "auto":
        if creds_file.exists():
            print("credentials: using patchright (credentials.json found)")
            return load_credentials("patchright")
        if has_cookies:
            print("ℹ credentials: credentials.json not found — falling back to .env cookies")
            mode = "cookies"
        else:
            raise RuntimeError(
                "No credentials found. Run login.py or add "
                "NOTEBOOKLM_AUTH_TOKEN + NOTEBOOKLM_COOKIES to .env"
            )

    if not has_cookies:
        raise RuntimeError("NOTEBOOKLM_AUTH_TOKEN or NOTEBOOKLM_COOKIES missing from .env")
    auth_token = env["NOTEBOOKLM_AUTH_TOKEN"]
    cookies = env["NOTEBOOKLM_COOKIES"]
    print(f"Credentials loaded (cookies) — token: {len(auth_token)} chars")
    return {"mode": "cookies", "authToken": auth_token, "cookies": cookies}


def _ts_client(creds: dict) -> str:
    return f"""const sdk = new NotebookLMClient({{
  authToken: {json.dumps(creds["authToken"])},
  cookies:   {json.dumps(creds["cookies"])},
  autoRefresh: false,
}});
await sdk.connect();"""


def login() -> None:
    """Run the patchright browser login and save credentials.json."""
    login_script = Path(__file__).parent / "login.py"
    result = subprocess.run(
        f'python "{login_script}"',
        cwd=str(SDK_ROOT), shell=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Login script exited with an error.")


def check_tsx() -> None:
    """Verify that npx tsx is available and print its version."""
    r = subprocess.run(
        "npx tsx --version",
        capture_output=True, text=True, cwd=str(SDK_ROOT), shell=True,
    )
    print("tsx:", r.stdout.strip() or r.stderr.strip())


def run_ts(script_name: str, content: str) -> str:
    """Write *content* to ``{SDK_ROOT}/{script_name}.ts``, execute with tsx, return stdout."""
    script_path = SDK_ROOT / f"{script_name}.ts"
    script_path.write_text(content, encoding="utf-8")
    result = subprocess.run(
        f'npx tsx "{script_path}"',
        capture_output=True, text=True, cwd=str(SDK_ROOT), shell=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script_name} failed:\n{result.stderr[-3000:]}")
    return result.stdout
