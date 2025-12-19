import sys
import asyncio
import re
import json
import os
import time
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
        video_dir = "test_videos"
        os.makedirs(video_dir, exist_ok=True)
        
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        
        if self.browser is None:
            # Headless=False is REQUIRED for the "Visual Context" grading pillar
            self.browser = await self.playwright.chromium.launch(headless=False)
         
        if self.context is None:
            # Configure context to record video for every page created in this context
            context_kwargs = {
                "viewport": {"width": 1280, "height": 720},
                # Playwright will save per-page videos into this directory
                "record_video_dir": video_dir,
                "record_video_size": {"width": 1280, "height": 720}
            }

            if os.path.exists(auth_file):
                print(f"Loading session from {auth_file}")
                context_kwargs["storage_state"] = auth_file

            # Pass the kwargs through so Playwright actually records video
            self.context = await self.browser.new_context(**context_kwargs)
            print(f"DEBUG: Browser context created with video recording enabled -> dir={context_kwargs.get('record_video_dir')} size={context_kwargs.get('record_video_size')}")

        
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

    async def list_recorded_videos(self):
        """Return list of recorded video files (most recent first)."""
        video_dir = "test_videos"
        if not os.path.exists(video_dir):
            return []
        files = [os.path.join(video_dir, f) for f in os.listdir(video_dir) if f.lower().endswith((".webm", ".mp4"))]
        files = sorted(files, key=lambda p: os.path.getmtime(p), reverse=True)
        print("DEBUG: Found recorded videos:", files)
        return files

    async def copy_latest_video_to_artifacts(self, test_name: str, src_video_path: str = None):
        """Copy the most recent video into the test artifacts folder (returns dst or None).

        If src_video_path is provided, copy that file. Otherwise pick the latest from video dir.
        The destination file will include a timestamp to avoid caching issues in the UI.
        """
        # Determine source
        if src_video_path and os.path.exists(src_video_path):
            latest = src_video_path
        else:
            videos = await self.list_recorded_videos()
            if not videos:
                print("DEBUG: No recorded videos to copy")
                return None
            latest = videos[0]

        # Prepare destination with timestamp to avoid client caching showing an old file
        dest_dir = os.path.join("artifacts", test_name)
        os.makedirs(dest_dir, exist_ok=True)
        ext = os.path.splitext(latest)[1] or ".webm"
        # use nanosecond timestamp for maximum uniqueness to avoid caching issues
        timestamp = int(time.time_ns())
        dst = os.path.join(dest_dir, f"video_{timestamp}{ext}")
        try:
            import shutil
            shutil.copy2(latest, dst)
            print(f"DEBUG: Copied video {latest} to {dst}")
            return dst
        except Exception as e:
            print("DEBUG: Failed to copy video:", e)
            return None

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()