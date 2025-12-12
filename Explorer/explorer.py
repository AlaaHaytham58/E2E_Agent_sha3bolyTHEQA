import json
import time
import io
import re
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont


class PageExplorer:
    CHAR_PER_TOKEN = 4 # Define constant for token approximation

    def __init__(self):
        self.results = {
            "metadata": {},
            "elements": [],
            "fingerprints": [],
            "errors": [],
            "metrics": {}
        }

    def explore_in_session(self, page, url: str):
        """
        Phase 1: Exploration & Knowledge Acquisition using an existing browser session.
        Extracts DOM, elements, bounding boxes, screenshot, and metrics.
        """
        start_time = time.time()

        try:
            print(f"   > Navigating to {url}...")
            # Use the existing page object to navigate
            page.goto(url, timeout=15000)

            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except:
                print("   > Networkidle timeout — continuing anyway.")

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

            print(f"   > Found {count} candidate interactive elements.")

            for i in range(count):
                el = locators.nth(i)

                try:
                    if not el.is_visible():
                        continue

                    tag_name = el.evaluate("el => el.tagName.toLowerCase()") 
                    text_content = (el.text_content() or "").strip()
                    attrs = el.evaluate(
                        """el => {
                            const out = {};
                            for (let a of el.attributes) out[a.name] = a.value;
                            return out;
                        }"""
                    )
                    bbox = el.bounding_box()

                    # Bbox validation
                    if bbox is None or bbox["width"] <= 0 or bbox["height"] <= 0 or bbox["x"] < 0 or bbox["y"] < 0:
                        continue
                    if bbox["width"] < 4 or bbox["height"] < 4:
                        continue
                    
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

                    # Extract fingerprint
                    fingerprint = self._extract_fingerprint(element_data, len(self.results["elements"]) - 1)
                    self.results["fingerprints"].append(fingerprint)

                except Exception as e:
                    self.results["errors"].append(f"Element {i} error: {e}")

        except Exception as nav_err:
            self.results["errors"].append(f"Navigation error: {nav_err}")

        finally:
            # Create annotated screenshot for visual coverage
            try:
                self._create_annotated_screenshot()
            except Exception as e:
                self.results["errors"].append(f"Annotation error: {e}")

            # Metrics
            end_time = time.time()
            
            # Aggregate statistics by category
            category_stats = {}
            for element in self.results["elements"]:
                category = element.get("category", "other")
                category_stats[category] = category_stats.get(category, 0) + 1
            
            self.results["metrics"] = {
                # Time for the browser runner part of the task
                "exploration_time_seconds": round(end_time - start_time, 3), 
                "total_elements_found": len(self.results["elements"]),
                "total_errors": len(self.results["errors"]),
                "element_statistics": category_stats
            }

            return self.results

    # ---------------------- VISUAL FINGERPRINTS (FOR SELF-HEALING) ----------------------

    def _extract_fingerprint(self, element_data, index):
        attrs = element_data.get("attributes", {})
        bbox = element_data.get("bounding_box", {})
        
        fingerprint = {
            "element_id": f"{element_data.get('tag', 'unknown')}-{index}",
            "index": index,
            "tag": element_data.get("tag"),
            "category": element_data.get("category"),
            "text": element_data.get("text"),
            "bounding_box": bbox,
            "attributes_key": sorted(list(attrs.keys())),
            "dominant_attribute": element_data.get("selectors", {}).get("css", "unknown"),
            "fallback_selectors": {
                "xpath": element_data.get("selectors", {}).get("xpath")
            },
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
                return "input"
        else:
            return "other"

    # ---------------------- LOCATOR HELPERS ----------------------

    def _generate_css_selector(self, tag, attrs):
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
        if "id" in attrs:
            return f"//*[@id='{attrs['id']}']"
        if text and len(text) <= 40:
            safe_text = text.replace("'", "\"")
            return f"//{tag}[contains(text(), '{safe_text}')]"
        return f"//{tag}"

    # ---------------------- VISUAL COVERAGE MAP ----------------------

    def _create_annotated_screenshot(self):
        screenshot_bytes = bytes.fromhex(self.results["screenshot"])
        img = Image.open(io.BytesIO(screenshot_bytes))
        draw = ImageDraw.Draw(img)

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

        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except:
            font = ImageFont.load_default()

        for idx, element in enumerate(self.results["elements"]):
            bbox = element.get("bounding_box")
            if not bbox:
                continue

            x, y, width, height = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
            x2, y2 = x + width, y + height

            category = element.get("category", "other")
            color = color_map.get(category, color_map["other"])

            draw.rectangle([x, y, x2, y2], outline=color, width=2)
            label = f"#{idx}({category[:3]})"

            draw.rectangle([x, y - 15, x + 70, y], fill=color)
            draw.text((x + 2, y - 13), label, fill="white", font=font)

        output_path = "exploration_annotated.png"
        img.save(output_path)
        print(f"   > Annotated coverage map saved to: {output_path}")