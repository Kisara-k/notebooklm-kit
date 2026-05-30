"""
Open a Chrome window to NotebookLM, wait for login, save session cookies.
The authToken (SNlM0e) is fetched fresh on each pipeline run, so we only
need to persist the long-lived session cookies here.
"""
import asyncio
import json
from pathlib import Path
from patchright.async_api import async_playwright

HERE = Path(__file__).parent
SDK_ROOT = HERE.parent
USER_DATA_DIR = str(HERE / "notebooklm_profile")
CREDENTIALS_JSON = SDK_ROOT / "credentials.json"


async def login():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
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
        CREDENTIALS_JSON.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
        print(f"Saved → {CREDENTIALS_JSON}")
        print("Auth token will be fetched automatically when you run the pipeline.")

        await context.close()


asyncio.run(login())
