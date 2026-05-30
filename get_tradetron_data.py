import json
import time
import os

# Force Playwright browser path inside the project directory when running in cloud environments
if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") is None and (os.path.exists("/app") or os.environ.get("RAILWAY_ENVIRONMENT")):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/app/.cache/ms-playwright"

from playwright.sync_api import sync_playwright

def main():
    # Load from .env file if it exists
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    # Attempt to load credentials from environment variables for automation (e.g. VPS)
    # If not found, securely prompt the user.
    email = os.environ.get("TRADETRON_EMAIL")
    password = os.environ.get("TRADETRON_PASSWORD")

    if not email or not password:
        import getpass
        print("--- Tradetron Automated Login ---")
        email = input("Enter Tradetron Email: ")
        password = getpass.getpass("Enter Tradetron Password: ")

    print("\nStarting automated headless login sequence...")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            err_str = str(e)
            if "Executable doesn't exist" in err_str or "playwright install" in err_str or "headless_shell" in err_str:
                print("[Playwright] Browser executable not found. Running dynamic installation ('playwright install chromium')...")
                import subprocess
                subprocess.run(["python3", "-m", "playwright", "install", "chromium"])
                browser = p.chromium.launch(headless=True)
            else:
                raise
        context = browser.new_context()
        page = context.new_page()

        print("[1/5] Navigating to Tradetron login page...")
        page.goto("https://tradetron.tech/login")
        page.wait_for_load_state("domcontentloaded")

        print("[2/5] Entering credentials...")
        # Tradetron login form inputs
        page.fill('input[type="email"]', email)
        page.fill('input[type="password"]', password)

        print("[3/5] Solving ALTCHA Proof-of-Work (this takes a few seconds)...")
        # ALTCHA is a purely mathematical captcha. We just check the box and wait for it to compute!
        page.wait_for_selector(".altcha-label")
        page.click(".altcha-label")
        
        try:
            # Wait for the computation to finish and verify
            page.wait_for_selector(".altcha[data-state='verified']", timeout=15000)
            print("      ✅ ALTCHA Cryptographic Proof Solved Successfully!")
        except Exception as e:
            print("      ❌ Failed to solve ALTCHA. Timeout exceeded.")
            browser.close()
            return

        print("[4/5] Submitting login form...")
        # Find the submit button and click it
        page.click('button[type="submit"]')

        print("[5/5] Waiting for Dashboard verification...")
        try:
            # Wait until we successfully land on the dashboard
            page.wait_for_url("**/user/dashboard**", timeout=30000)
            print("      ✅ Login Successful! Dashboard loaded.")
        except Exception as e:
            print(f"      ❌ Login failed! Please check your email/password. Error: {e}")
            # Save screenshot for debugging
            page.screenshot(path="login_failed.png")
            print("      📸 Saved failure screenshot to 'login_failed.png'")
            browser.close()
            return

        # Extract and save the new session cookies
        cookies = context.cookies()
        with open("tradetron_cookies.json", "w") as f:
            json.dump(cookies, f, indent=4)
            
        print("\n🎉 AUTOMATION COMPLETE!")
        print("Session cookies successfully saved to tradetron_cookies.json")
        print("The dashboard_server.py will automatically pick up these fresh cookies.")

        browser.close()

if __name__ == "__main__":
    main()
