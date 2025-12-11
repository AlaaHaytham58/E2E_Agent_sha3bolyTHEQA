import json
import time
import io
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont


class PageExplorer:
    def __init__(self):
        self.results = {
            "metadata": {},
            "elements": [],
            "fingerprints": [],
            "errors": [],
            "metrics": {}
        }

    def explore(self, url: str):
        """
        Phase 1: Exploration & Knowledge Acquisition
        Extracts:
        - Full DOM
        - Interactive elements
        - Bounding boxes
        - Screenshot
        - Candidate locators
        - Metrics (time, element counts)
        """
        start_time = time.time()

        with sync_playwright() as p:
            print("Launching browser...")
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()

            try:
                print(f"Navigating to {url}...")
                page.goto(url, timeout=15000)

                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except:
                    print("Networkidle timeout — continuing anyway.")

                # Metadata
                self.results["metadata"] = {
                    "url": page.url,
                    "title": page.title()
                }

                # Full DOM snapshot
                dom_html = page.content()
                self.results["dom_html"] = dom_html

                # Screenshot (Base64 hex)
                screenshot_bytes = page.screenshot(type="png")
                self.results["screenshot"] = screenshot_bytes.hex()

                # Locate interactive elements
                selector = "a, button, input, select, textarea"
                locators = page.locator(selector)
                count = locators.count()

                print(f"Found {count} candidate interactive elements.")

                for i in range(count):
                    el = locators.nth(i) # Get the i-th element

                    try:
                        if not el.is_visible(): # Skip invisible elements
                            continue

                        # Extract element details e.g. <button> → "button"
                        tag_name = el.evaluate("el => el.tagName.toLowerCase()") 

                        # Get the visible text inside the element e.g. <button>Submit</button> → "Submit"
                        text_content = (el.text_content() or "").strip()

                        # Get all HTML attributes of the element as a dict
                        attrs = el.evaluate(
                            """el => {
                                const out = {};
                                for (let a of el.attributes) out[a.name] = a.value;
                                return out;
                            }"""
                        )

                        # Get the element's position and size on the screen
                        # Returns: Dictionary with coordinates
                        bbox = el.bounding_box()

                        # Filter out elements with invalid bounding boxes (off-screen, zero size, or negative coords)
                        if bbox is None or bbox["width"] <= 0 or bbox["height"] <= 0:
                            continue
                        if bbox["x"] < 0 or bbox["y"] < 0:
                            continue
                        
                        # Filter out elements that are too small to interact with (less than 4x4 pixels)
                        if bbox["width"] < 4 or bbox["height"] < 4:
                            continue

                        # Categorize element for better organization
                        category = self._categorize_element(tag_name, attrs)

                        element_data = {
                            "tag": tag_name,
                            "category": category,
                            "text": text_content,
                            "attributes": attrs,
                            "bounding_box": bbox,
                            "is_enabled": el.is_enabled(),
                            "is_visible": True,
                            "selectors": {
                                "css": self._generate_css_selector(tag_name, attrs),
                                "xpath": self._generate_xpath(tag_name, attrs, text_content)
                            }
                        }

                        self.results["elements"].append(element_data)

                        # Extract fingerprint for self-healing
                        fingerprint = self._extract_fingerprint(element_data, len(self.results["elements"]) - 1)
                        self.results["fingerprints"].append(fingerprint)

                    except Exception as e:
                        self.results["errors"].append(f"Element {i} error: {e}")

            except Exception as nav_err:
                self.results["errors"].append(f"Navigation error: {nav_err}")

            finally:
                browser.close()

        # Create annotated screenshot for visual coverage
        try:
            self._create_annotated_screenshot()
            print("Annotated coverage map created.")
        except Exception as e:
            self.results["errors"].append(f"Annotation error: {e}")
            print(f"Failed to create annotated screenshot: {e}")

        # Metrics
        end_time = time.time()
        
        # Aggregate statistics by category
        category_stats = {}
        for element in self.results["elements"]:
            category = element.get("category", "other")
            category_stats[category] = category_stats.get(category, 0) + 1
        
        self.results["metrics"] = {
            "exploration_time_seconds": round(end_time - start_time, 3),
            "total_elements_found": len(self.results["elements"]),
            "total_errors": len(self.results["errors"]),
            "element_statistics": category_stats
        }

        print("Exploration completed.")
        return self.results

    # ---------------------- VISUAL FINGERPRINTS (FOR SELF-HEALING) ----------------------

    def _extract_fingerprint(self, element_data, index):
        """
        Creates a visual/structural fingerprint of an element for self-healing.
        This lightweight signature allows the agent to compare old vs new page versions
        and detect if an element has moved, changed, or been replaced.
        
        Returns a dict with:
        - element_id: unique identifier
        - tag: HTML tag name
        - text: element text content
        - category: categorized element type
        - bounding_box: position on page
        - attributes_key: tuple of attribute names for matching
        - dominant_attribute: best locator strategy (CSS selector)
        """
        attrs = element_data.get("attributes", {})
        bbox = element_data.get("bounding_box", {})
        
        fingerprint = {
            "element_id": f"{element_data.get('tag', 'unknown')}-{index}",
            "index": index,
            "tag": element_data.get("tag"),
            "category": element_data.get("category"),
            "text": element_data.get("text"),
            "bounding_box": bbox,
            # Attributes key helps match elements across page versions
            "attributes_key": sorted(list(attrs.keys())),
            # Dominant attribute is the best locator strategy
            "dominant_attribute": element_data.get("selectors", {}).get("css", "unknown"),
            # Alternative locators for fallback
            "fallback_selectors": {
                "xpath": element_data.get("selectors", {}).get("xpath")
            },
            # Key attributes for visual matching
            "key_attributes": {
                "id": attrs.get("id"),
                "name": attrs.get("name"),
                "data-testid": attrs.get("data-testid"),
                "placeholder": attrs.get("placeholder"),
                "class": attrs.get("class")
            },
            "is_enabled": element_data.get("is_enabled")
        }
        
        return fingerprint

    # ---------------------- ELEMENT CATEGORIZATION ----------------------

    def _categorize_element(self, tag, attrs):
        """
        Categorize an element based on tag and type.
        Returns: button, input, link, select, textarea, checkbox, radio, or other
        """
        if tag == "button":
            return "button"
        elif tag == "a":
            return "link"
        elif tag == "select":
            return "select"
        elif tag == "textarea":
            return "textarea"
        elif tag == "input":
            input_type = attrs.get("type", "text").lower()
            
            # Map input types to categories
            if input_type in ["submit", "button", "reset"]:
                return "button"
            elif input_type == "checkbox":
                return "checkbox"
            elif input_type == "radio":
                return "radio"
            elif input_type in ["text", "password", "email", "number", "url", "tel", "search"]:
                return "input"
            elif input_type == "hidden":
                return "hidden"
            else:
                return "input"  # Default to input for unknown types
        else:
            return "other"

    # ---------------------- LOCATOR HELPERS ----------------------

    def _generate_css_selector(self, tag, attrs):
        """
        Creates a CSS-based address for finding elements
        """
        if "id" in attrs:
            return f"#{attrs['id']}"
        if "data-testid" in attrs:
            return f"[data-testid='{attrs['data-testid']}']"
        if "name" in attrs:
            return f"{tag}[name='{attrs['name']}']"
        if "class" in attrs:
            first_class = attrs["class"].split(" ")[0]
            return f"{tag}.{first_class}"
        return tag

    def _generate_xpath(self, tag, attrs, text):
        """
        Simple XPath fallback.
        """
        if "id" in attrs:
            return f"//*[@id='{attrs['id']}']"
        if text and len(text) <= 40:
            safe_text = text.replace("'", "\"")
            return f"//{tag}[contains(text(), '{safe_text}')]"
        return f"//{tag}"

    # ---------------------- VISUAL COVERAGE MAP ----------------------

    def _create_annotated_screenshot(self):
        """
        Creates a visual coverage map by drawing rectangles around detected elements.
        This helps visualize what was found and spot coverage gaps.
        """
        # Decode screenshot from hex
        screenshot_bytes = bytes.fromhex(self.results["screenshot"])
        img = Image.open(io.BytesIO(screenshot_bytes))
        draw = ImageDraw.Draw(img)

        # Define colors for different element categories
        color_map = {
            "button": "#FF0000",      # Red
            "input": "#00FF00",       # Green
            "link": "#0000FF",        # Blue
            "select": "#FFFF00",      # Yellow
            "textarea": "#FF00FF",    # Magenta
            "checkbox": "#00FFFF",    # Cyan
            "radio": "#FFA500",       # Orange
            "hidden": "#808080",      # Gray
            "other": "#A9A9A9"        # Dark Gray
        }

        # Try to load a default font, fallback to default if unavailable
        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except:
            font = ImageFont.load_default()

        # Draw rectangles for each element
        for idx, element in enumerate(self.results["elements"]):
            bbox = element.get("bounding_box")
            if not bbox:
                continue

            x, y, width, height = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
            x2, y2 = x + width, y + height

            # Determine color based on category (not tag)
            category = element.get("category", "other")
            color = color_map.get(category, color_map["other"])

            # Draw rectangle
            draw.rectangle([x, y, x2, y2], outline=color, width=2)

            # Draw label with element index and category
            label = f"#{idx}({category[:3]})"

            # Add background for text readability
            draw.rectangle([x, y - 15, x + 70, y], fill=color)
            draw.text((x + 2, y - 13), label, fill="white", font=font)

        # Save annotated image
        output_path = "exploration_annotated.png"
        img.save(output_path)
        print(f"Annotated screenshot saved to: {output_path}")

    # ---------------------- SAVE TO JSON ----------------------

    def save_results(self, filename="exploration_results.json"):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2)
        print(f"Results saved to: {filename}")


if __name__ == "__main__":
    import sys
    
    # Get URL from command line or prompt user
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    else:
        target_url = input("\nEnter the URL to explore (e.g., https://www.example.com): ").strip()
        
        if not target_url:
            print("\nError: URL cannot be empty. Exiting.")
            sys.exit(1)
    
    print()
    explorer = PageExplorer()
    explorer.explore(target_url)
    explorer.save_results()
