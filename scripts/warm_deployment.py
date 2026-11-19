"""Keeps this project's Streamlit Cloud deployment reachable.

Streamlit Community Cloud suspends an app after roughly 12 hours without
traffic. It also only starts the Python process once a real browser loads the
page and opens a WebSocket to /_stcore/stream, so a plain HTTP request gets
the static shell back and wakes nothing. This uses a headless browser instead,
and clicks the wake button if the app has already been suspended. The app's
iframe tag can attach before the app inside it has actually connected, so the
non-wake path also waits for the app's own content to render there.

Streamlit Cloud occasionally answers one navigation slowly for no real reason,
so this retries once on a timeout before giving up.

Doubles as a deployment smoke test: a non-zero exit means the live app is
unreachable.
"""

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

APP_URL = "https://relay-soc.streamlit.app/"
WAKE_TEXT = "get this app back up"
APP_IFRAME_SELECTOR = 'iframe[title="streamlitApp"]'


def visit(browser):
    page = browser.new_page()
    try:
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=90_000)
        wake_button = page.get_by_text(WAKE_TEXT, exact=False)
        app_frame = page.locator(APP_IFRAME_SELECTOR)
        wake_button.or_(app_frame).first.wait_for(timeout=60_000)
        if wake_button.count():
            wake_button.first.click()
            page.wait_for_timeout(45_000)
            print(f"WOKE {APP_URL}")
        else:
            page.frame_locator(APP_IFRAME_SELECTOR).locator(
                '[data-testid="stApp"]'
            ).wait_for(timeout=60_000)
            print(f"OK   {APP_URL}")
    finally:
        page.close()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    try:
        try:
            visit(browser)
        except PlaywrightTimeoutError:
            print("attempt 1 timed out, retrying in 30s")
            time.sleep(30)
            visit(browser)
    finally:
        browser.close()
