from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print("Opening...")

    page.goto(
        "https://bromotenggersemeru.id",
        timeout=60000,
        wait_until="domcontentloaded"
    )

    print("Title:", page.title())
    print("URL:", page.url)

    browser.close()
