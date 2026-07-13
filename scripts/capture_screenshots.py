"""Captures the six README screenshots from the real Streamlit dashboard on real
seeded runs. Launches its own dashboard instance on a dedicated port so it does not
collide with a dev server the user may already have running.

Usage: .venv/Scripts/python.exe scripts/capture_screenshots.py
Requires: playwright (pip install playwright && playwright install chromium)
"""

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PORT = 8502
BASE_URL = f"http://localhost:{PORT}"
VIEWPORT = {"width": 1600, "height": 1000}


def _wait_for_server(timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(BASE_URL, timeout=2)
            return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"dashboard did not come up on {BASE_URL} within {timeout}s")


def _select_scenario(page: Page, label: str) -> None:
    combo = page.get_by_role("combobox", name="Attack")
    combo.click()
    combo.fill(label)
    page.get_by_role("option", name=label, exact=True).click()


def _set_seed(page: Page, seed: int) -> None:
    seed_input = page.get_by_role("spinbutton", name="Random seed")
    seed_input.fill(str(seed))
    seed_input.press("Tab")


def _run_scenario(page: Page, label: str, seed: int) -> None:
    _select_scenario(page, label)
    _set_seed(page, seed)
    page.get_by_role("button", name="Run scenario").click()
    page.wait_for_selector(".rl-topbar", timeout=120_000)
    page.wait_for_timeout(1500)  # let the tab content finish rendering


def _click_tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    page.wait_for_timeout(800)


def capture(page: Page) -> None:
    ASSETS.mkdir(exist_ok=True)

    # A sustained LOAD_INFLATION run at the default seed drives a real incident
    # through the full pipeline: detection, containment, dispatch impact.
    _run_scenario(page, "LOAD_INFLATION", seed=42)

    page.screenshot(path=str(ASSETS / "dashboard-overview.png"))
    print("captured dashboard-overview.png (LOAD_INFLATION, seed 42, Security Overview)")

    page.locator(".rl-card", has_text="Unified threat score").screenshot(path=str(ASSETS / "threat-scoring.png"))
    print("captured threat-scoring.png (LOAD_INFLATION, seed 42)")

    _click_tab(page, "Detection Analytics")
    page.locator('[data-testid="stTabPanel"]:visible').screenshot(path=str(ASSETS / "detection-analytics.png"))
    print("captured detection-analytics.png (LOAD_INFLATION, seed 42)")

    _click_tab(page, "Live Agent Activity")
    page.locator('[data-testid="stTabPanel"]:visible .rl-pipeline').screenshot(path=str(ASSETS / "agent-pipeline.png"))
    print("captured agent-pipeline.png (LOAD_INFLATION, seed 42)")

    _click_tab(page, "Counterfactual")
    page.wait_for_timeout(500)
    page.locator('[data-testid="stTabPanel"]:visible').screenshot(path=str(ASSETS / "counterfactual.png"))
    print("captured counterfactual.png (LOAD_INFLATION, seed 42)")

    # ESCALATING_FDI at its documented demo seed: the one frame where TRUSTED,
    # ESTIMATED, and QUARANTINED are all present (see evaluation/harness.py's
    # ESCALATING_FDI_DEMO_SEED / ESCALATING_FDI_SNAPSHOT_TICK).
    _run_scenario(page, "ESCALATING_FDI (demo)", seed=19)
    _click_tab(page, "Gateway State")
    page.locator('[data-testid="stTabPanel"]:visible .rl-gateway-grid').screenshot(path=str(ASSETS / "gateway-states.png"))
    print("captured gateway-states.png (ESCALATING_FDI demo, seed 19, tick 35)")


def main() -> None:
    server = subprocess.Popen(
        [
            str(ROOT / ".venv" / "Scripts" / "streamlit.exe"),
            "run",
            str(ROOT / "dashboard" / "app.py"),
            "--server.port",
            str(PORT),
            "--server.headless",
            "true",
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT)
            page.goto(BASE_URL)
            page.wait_for_selector('text=Pick a scenario', timeout=30_000)
            capture(page)
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
