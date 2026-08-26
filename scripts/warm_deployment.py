"""Keeps this project's Streamlit Cloud deployment reachable.

Streamlit Community Cloud suspends an app after roughly 12 hours without
traffic. It also only starts the Python process once a real browser loads the
page and opens a WebSocket to /_stcore/stream, so a plain HTTP request gets
the static shell back and wakes nothing. This uses a headless browser instead,
and clicks the wake button if the app has already been suspended.

Doubles as a deployment smoke test: a non-zero exit means the live app is
unreachable.
"""

from playwright.sync_api import sync_playwright

APP_URL = "https://relay-soc.streamlit.app/"
WAKE_TEXT = "get this app back up"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page()
    try:
        page.goto(APP_URL, wait_until="networkidle", timeout=90_000)
        button = page.get_by_text(WAKE_TEXT, exact=False)
        if button.count():
            button.first.click()
            page.wait_for_timeout(45_000)
            print(f"WOKE {APP_URL}")
        else:
            print(f"OK   {APP_URL}")
    finally:
        page.close()
        browser.close()