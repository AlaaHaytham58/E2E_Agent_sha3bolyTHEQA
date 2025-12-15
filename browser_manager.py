import sys
import asyncio
import re
import json
import os
from playwright.async_api import async_playwright
# --- FIX FOR WINDOWS & PLAYWRIGHT ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
# ------------------------------------

class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start_browser(self, auth_file="aauth.json"):
        """
        Starts the browser. 
        If 'auth.json' exists, it loads cookies/storage to restore session.
        """
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        
        if self.browser is None:
            # Headless=False is REQUIRED for the "Visual Context" grading pillar
            self.browser = await self.playwright.chromium.launch(headless=False)
        
        # if os.path.exists(auth_file):
        #     print(f"Loading session from {auth_file}") # This log proves it works
        #     self.context = await self.browser.new_context(storage_state=auth_file)
        
        # Load auth state if it exists (Dependency handling)
        if self.context is None:
            if os.path.exists(auth_file):
                print(f"Loading session from {auth_file}")
                self.context = await self.browser.new_context(storage_state=auth_file)
            else:
                self.context = await self.browser.new_context()
        
        if self.page is None:
            self.page = await self.context.new_page()

    async def clean_dom(self, raw_html: str) -> str:
        """
        Cleans HTML to save tokens before sending to the LLM.
        (Adapted from your colleague's approach)
        """
        # Remove script and style tags
        cleaner = re.sub(r"<script[\s\S]*?</script>", "", raw_html)
        cleaner = re.sub(r"<style[\s\S]*?</style>", "", cleaner)
        # Remove comments
        cleaner = re.sub(r"", "", cleaner)
        # Remove meta/link tags
        cleaner = re.sub(r"<(meta|link|base|br|hr)\s*[^>]*?/?>", "", cleaner)
        # Collapse whitespace
        cleaner = re.sub(r"\s+", " ", cleaner).strip()
        return cleaner[:15000]  # Limit context window

    async def explore_url(self, url):
        """
        Navigates to the URL and returns BOTH:
        1. structured_elements (for the UI/Human to see)
        2. cleaned_html (for the LLM to read)
        """
        if not self.page:
            await self.start_browser()

        try:
            print(f"Navigating to {url}...")
            await self.page.goto(url)
            await self.page.wait_for_load_state("domcontentloaded")
            
            # 1. Get Raw HTML and Clean it (For the Brain)
            raw_html = await self.page.content()
            cleaned_html = await self.clean_dom(raw_html)

            # 2. Extract Interactive Elements (For the User Interface)
            # This JS is superior to Regex because it checks 'offsetParent' (Visibility)
            elements = await self.page.evaluate('''() => {
                const interactables = [];
                // Select inputs, buttons, links, and semantic roles
                const selector = 'button, a, input, select, textarea, [role="button"], [role="link"], [role="checkbox"]';
                
                document.querySelectorAll(selector).forEach((el, index) => {
                    // Check if element is visible (has size and is not hidden)
                    const rect = el.getBoundingClientRect();
                    const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                    
                    if (isVisible) {
                        interactables.push({
                            id: index,
                            tag: el.tagName.toLowerCase(),
                            text: el.innerText.slice(0, 50).replace(/\\n/g, " ").trim() || el.getAttribute('placeholder') || "No Text",
                            role: el.getAttribute('role') || el.tagName.toLowerCase(),
                            // Grab attributes helpful for testing
                            attributes: {
                                type: el.getAttribute('type'),
                                name: el.getAttribute('name'),
                                id_attr: el.getAttribute('id'),
                                class: el.getAttribute('class'),
                                placeholder: el.getAttribute('placeholder')
                            }
                        });
                    }
                });
                return interactables;
            }''')

            title = await self.page.title()
            
            return {
                "title": title,
                "url": self.page.url,
                "cleaned_dom": cleaned_html, # Feed this to LLM
                "elements": elements         # Show this in Streamlit
            }

        except Exception as e:
            return {"error": str(e)}

    async def capture_screenshot(self):
        """Returns screenshot bytes for Streamlit display."""
        if self.page:
            try:
                return await self.page.screenshot()
            except:
                return None
        return None

    async def save_storage_state(self, path="auth.json"):
        """Call this after a successful login test to save cookies."""
        if self.context:
            await self.context.storage_state(path=path)
            print(f"Session saved to {path}")

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()