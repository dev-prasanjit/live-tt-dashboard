import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto("http://localhost:8080", wait_until="networkidle")
        await page.wait_for_timeout(1000)
        
        # Click to open
        await page.click("details.collapse summary")
        await page.wait_for_timeout(1000)
        
        styles = await page.evaluate("""() => {
            const details = document.querySelector('details.collapse');
            const summary = details.querySelector('summary');
            const content = details.querySelector('.collapse-content');
            const grid = details.querySelector('#strategiesGrid');
            
            return {
                details: {
                    display: window.getComputedStyle(details).display,
                    height: window.getComputedStyle(details).height,
                    overflow: window.getComputedStyle(details).overflow
                },
                summary: {
                    display: window.getComputedStyle(summary).display,
                    height: window.getComputedStyle(summary).height
                },
                content: {
                    display: window.getComputedStyle(content).display,
                    height: window.getComputedStyle(content).height,
                    maxHeight: window.getComputedStyle(content).maxHeight,
                    visibility: window.getComputedStyle(content).visibility,
                    opacity: window.getComputedStyle(content).opacity,
                    overflow: window.getComputedStyle(content).overflow
                },
                grid: {
                    display: window.getComputedStyle(grid).display,
                    height: window.getComputedStyle(grid).height
                }
            };
        }""")
        
        print("Styles when details is open:")
        import json
        print(json.dumps(styles, indent=2))
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
