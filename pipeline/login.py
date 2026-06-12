"""
Open a Chrome window to NotebookLM, wait for login, save session cookies.
The authToken (SNlM0e) is fetched fresh on each pipeline run, so we only
need to persist the long-lived session cookies here.
"""
import argparse
import asyncio
import json
import shutil
from pathlib import Path
from patchright.async_api import async_playwright

HERE = Path(__file__).parent
SDK_ROOT = HERE.parent
PROFILES_DIR = HERE / "profiles"

DEFAULT_PROFILE = "default"


def _profile_dir(profile: str) -> Path:
    return PROFILES_DIR / profile


def _credentials_file(profile: str) -> Path:
    if profile == DEFAULT_PROFILE:
        return SDK_ROOT / "credentials.json"
    return SDK_ROOT / f"credentials.{profile}.json"


def _clear_session(profile: str) -> None:
    """Delete the profile directory and credentials so a fresh login is forced."""
    profile_dir = _profile_dir(profile)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
        print(f"Cleared profile: {profile_dir}")
    creds = _credentials_file(profile)
    if creds.exists():
        creds.unlink()
        print(f"Cleared credentials: {creds}")


async def login(profile: str = DEFAULT_PROFILE, logout: bool = False):
    profile = profile or DEFAULT_PROFILE
    if logout:
        _clear_session(profile)

    user_data_dir = _profile_dir(profile)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    creds_file = _credentials_file(profile)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
            ],
        )
        page = await context.new_page()
        await page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded")

        if "accounts.google.com" in page.url:
            print("Log in to your Google account in the browser window.")
            await page.wait_for_url("https://notebooklm.google.com/**", timeout=300000)

        print("On NotebookLM — waiting for page to settle...")
        await page.wait_for_load_state("networkidle", timeout=20000)

        raw_cookies = await context.cookies("https://notebooklm.google.com")
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in raw_cookies)
        print(f"Cookies saved ({len(raw_cookies)} entries, {len(cookie_str)} chars)")

        credentials = {"authToken": "", "cookies": cookie_str}
        creds_file.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
        print(f"Saved → {creds_file}")
        print("Auth token will be fetched automatically when you run the pipeline.")

        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Profile name (default: 'default')")
    parser.add_argument("--logout", action="store_true", help="Clear saved session before logging in")
    args = parser.parse_args()
    asyncio.run(login(profile=args.profile, logout=args.logout))
