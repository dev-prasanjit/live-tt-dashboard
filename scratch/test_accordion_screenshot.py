import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to page
        print("Navigating to dashboard...")
        await page.goto("http://localhost:8080", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        # Check details block styles
        info = await page.evaluate("""() => {
            const details = document.querySelector('details.collapse');
            if (!details) return { exists: false };
            const style = window.getComputedStyle(details);
            const summary = details.querySelector('summary');
            const summaryStyle = summary ? window.getComputedStyle(summary) : {};
            const grid = details.querySelector('#strategiesGrid');
            const gridStyle = grid ? window.getComputedStyle(grid) : {};
            return {
                exists: true,
                tagName: details.tagName,
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                height: style.height,
                width: style.width,
                classes: details.className,
                summaryDisplay: summaryStyle.display,
                summaryText: summary ? summary.innerText : '',
                gridDisplay: gridStyle.display,
                gridChildCount: grid ? grid.children.length : 0,
                gridHTML: grid ? grid.innerHTML : ''
            };
        }""")
        
        print("DOM Element Info:")
        for k, v in info.items():
            if k != 'gridHTML':
                print(f"  {k}: {v}")
            
        # Click it to open
        print("Clicking summary...")
        await page.click("details.collapse summary")
        await page.wait_for_timeout(2000)
        
        # Check details block info after click
        info_after = await page.evaluate("""() => {
            const details = document.querySelector('details.collapse');
            if (!details) return { exists: false };
            const style = window.getComputedStyle(details);
            const grid = details.querySelector('#strategiesGrid');
            return {
                openAttr: details.open,
                height: style.height,
                gridChildCount: grid ? grid.children.length : 0,
                gridHTML: grid ? grid.innerHTML : ''
            };
        }""")
        print("DOM Element Info After Click:")
        for k, v in info_after.items():
            if k != 'gridHTML':
                print(f"  {k}: {v}")
            else:
                print(f"  gridHTML length: {len(v)}")
                
        # Take a screenshot to visualize
        screenshot_path = "scratch/dashboard_screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"Screenshot saved to {screenshot_path}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
