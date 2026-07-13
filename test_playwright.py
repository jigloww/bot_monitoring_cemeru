from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:

    browser = p.chromium.launch(
        channel="chrome",
        headless=False
    )

    page = browser.new_page()

    print("Opening website...")

    page.goto(
        "https://bromotenggersemeru.id",
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(10000)

    print("=" * 60)
    print("Title :", page.title())
    print("URL   :", page.url)
    print("=" * 60)

    fp = page.evaluate("""
    () => ({
        webdriver: navigator.webdriver,
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        vendor: navigator.vendor,
        language: navigator.language,
        languages: navigator.languages,
        hardwareConcurrency: navigator.hardwareConcurrency,
        deviceMemory: navigator.deviceMemory,
        plugins: navigator.plugins.length,
        cookieEnabled: navigator.cookieEnabled,
    })
    """)

    print(json.dumps(fp, indent=4))

    print("=" * 60)

    cookies = browser.contexts[0].cookies()

    print("Cookies:")
    for c in cookies:
        print(c["name"])

    page.screenshot(path="test.png", full_page=True)

    with open("test.html", "w", encoding="utf-8") as f:
        f.write(page.content())

    print("\nSaved:")
    print("  test.png")
    print("  test.html")

    browser.close()