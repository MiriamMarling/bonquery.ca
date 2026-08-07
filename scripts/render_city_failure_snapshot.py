"""Render the saved City source as evidence after a parser failure.

The scraper writes city_page_parser_failure.html before this script runs. The
PNG therefore shows the same response that the parser could not understand,
not a later version of the live City page.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


DATA_DIR = Path(__file__).parent.parent / "data"
SOURCE_FILE = DATA_DIR / "city_page_parser_failure.html"
SCREENSHOT_FILE = DATA_DIR / "city_page_parser_failure.png"


def main():
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(f"Saved City source not found: {SOURCE_FILE}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.goto(SOURCE_FILE.as_uri(), wait_until="load")
        page.screenshot(path=str(SCREENSHOT_FILE), full_page=True)
        browser.close()

    print(f"Wrote parser-failure screenshot: {SCREENSHOT_FILE}")


if __name__ == "__main__":
    main()
