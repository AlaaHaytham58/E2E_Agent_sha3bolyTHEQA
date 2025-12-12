import time
import json
import re
import ollama
import concurrent.futures
import os
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

# Import classes from your files
from explorer import PageExplorer 
from schemas import StructuredRepresentation 

# --- UTILITY FUNCTIONS ---

def clean_dom(raw_html: str) -> str:
    """
    Cleans the raw HTML to prepare it for LLM consumption.
    Removes comments, script/style tags, and collapses whitespace.
    """
    cleaner_html = re.sub(r"", "", raw_html)
    cleaner_html = re.sub(r"<script[\s\S]*?</script>", "", cleaner_html)
    cleaner_html = re.sub(r"<style[\s\S]*?</style>", "", cleaner_html)
    cleaner_html = re.sub(r"<(meta|link|base|br|hr)\s*[^>]*?/?>", "", cleaner_html)
    cleaner_html = re.sub(r"\s+", " ", cleaner_html).strip()
    return cleaner_html[:10000] 

def extract_valid_links(base_url: str, raw_html: str, visited: set) -> list:
    """
    Parses raw HTML to find and validate new links for multi-page exploration.
    """
    new_links = set()
    href_matches = re.findall(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\'#]*)["\']', raw_html, re.IGNORECASE)

    for href in href_matches:
        absolute_url = urljoin(base_url, href).split('#')[0].split('?')[0]
        
        if absolute_url.startswith(("http://", "https://")):
            # Check if the domain is the same for focused exploration
            if urlparse(absolute_url).netloc == urlparse(base_url).netloc:
                if absolute_url not in visited:
                    new_links.add(absolute_url)
                    
    return list(new_links)

def save_state_concurrently(url: str, results: dict, base_dir: str = "knowledge_base"):
    """
    Concurrent task to save the structured representation for state management/versioning.
    """
    # Simulate setup and file writing time
    time.sleep(0.05) 
    
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    filename = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(".", "_") + ".json"
    filepath = os.path.join(base_dir, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"   > State Management: Saved knowledge for {url} concurrently to {filepath}")
        return True, filepath
    except Exception as e:
        print(f"   > State Management Error: Failed to save state for {url}: {e}")
        return False, str(e)


# --- EXPLORER AGENT ---

class ExplorerAgent:
    CHAR_PER_TOKEN = 4 # Approximation for token usage
    
    def __init__(self, start_url, max_pages=3):
        self.queue = [start_url]
        self.visited = set()
        self.max_pages = max_pages
        self.knowledge_base = {}

    def llm_parse_page(self, cleaned_dom: str, element_list_json: str):
        """
        Language-only LLM analysis (Ollama + Qwen3-Coder) of the DOM.
        """
        model_name = "qwen3-coder:30b" 
        
        # Calculate input size
        input_text_length = len(cleaned_dom) + len(element_list_json)
        llm_start_time = time.time()

        # 1. Define the Prompt
        system_prompt = (
            "You are an expert Web Testing Agent specialized in code analysis. "
            "Your task is to analyze the provided CLEANED HTML and the 'ELEMENT CANDIDATES' list. "
            "The list contains locators, attributes, and text for interactive elements. "
            "Based *only* on the textual context (tags, attributes, text), assign a precise, "
            "semantic 'role' (e.g., 'username_input', 'submit_button') to each element. "
            "Output only the JSON object."
        )

        user_prompt = f"""
        **CLEANED HTML (For Context):**
        {cleaned_dom}

        **ELEMENT CANDIDATES (Locators/BBox/Text):**
        {element_list_json}
        """
        
        try:
            # 2. Call Ollama 
            client = ollama.Client() 
            
            response = client.chat(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt} 
                ],
                format="json",
                options={"temperature": 0.2}
            )
            
            llm_end_time = time.time()
            json_str = response['message']['content'].strip()
            
            # Validate and store LLM Metrics
            parsed_data = StructuredRepresentation.model_validate_json(json_str)
            llm_metrics = {
                "llm_response_time_seconds": round(llm_end_time - llm_start_time, 3),
                "tokens_consumed": round(input_text_length / self.CHAR_PER_TOKEN)
            }

            return parsed_data.model_dump(), llm_metrics

        except Exception as e:
            llm_end_time = time.time()
            llm_metrics = {
                "llm_response_time_seconds": round(llm_end_time - llm_start_time, 3),
                "tokens_consumed": round(input_text_length / self.CHAR_PER_TOKEN)
            }
            print(f"   > LLM Processing Error: {e}")
            return {"elements": [], "error": str(e)}, llm_metrics

    def start_exploration(self):
        print("Launching shared browser session...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor: 
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False) 
                page = browser.new_page()

                while self.queue and len(self.visited) < self.max_pages:
                    current_url = self.queue.pop(0)
                    if current_url in self.visited:
                        continue

                    print(f"\nExplorer Agent visiting: {current_url}")
                    explorer_start_time = time.time()
                    
                    try:
                        # 1. Sequential: Exploration (Browser Runner)
                        explorer = PageExplorer()
                        exploration_results = explorer.explore_in_session(page, current_url) 
                        
                        raw_html = exploration_results.get("dom_html", "")
                        clean_html = clean_dom(raw_html)
                        screenshot_hex = exploration_results.get("screenshot", "") 
                        
                        element_candidates_for_llm = {
                            "elements": exploration_results.get("elements", []),
                            "fingerprints": exploration_results.get("fingerprints", [])
                        }
                        element_candidates_json = json.dumps(element_candidates_for_llm, indent=2)
                        input_text_length = len(clean_html) + len(element_candidates_json)
                        
                        # --------------------- START PARALLEL EXECUTION ---------------------
                        
                        # 2. Parallel Task 1: LLM Analysis
                        print(f"   > Sending input to Ollama (approx. {round(input_text_length / self.CHAR_PER_TOKEN)} tokens)...")
                        llm_future = executor.submit(
                            self.llm_parse_page, 
                            clean_html, 
                            element_candidates_json
                        )
                        
                        # 3. Parallel Task 2: State Saving/Logging
                        save_future = executor.submit(
                            save_state_concurrently, 
                            current_url, 
                            exploration_results
                        )
                        
                        # Wait for both I/O tasks to complete
                        concurrent.futures.wait([llm_future, save_future])
                        
                        llm_enriched_data, llm_metrics = llm_future.result()

                        # --------------------- END PARALLEL EXECUTION -----------------------

                        # 4. Aggregation and Observability Metrics
                        explorer_end_time = time.time()
                        total_response_time = round(explorer_end_time - explorer_start_time, 3)

                        final_metrics = {
                            "total_response_time_seconds": total_response_time, 
                            "explorer_time_seconds": exploration_results["metrics"]["exploration_time_seconds"],
                            **llm_metrics,
                            "element_statistics": exploration_results["metrics"]["element_statistics"]
                        }
                        
                        print(f"   > Iteration Time: {total_response_time}s | Tokens Used: {llm_metrics['tokens_consumed']}")
                        
                        # 5. Store Knowledge
                        final_structured_representation = {
                            **exploration_results,
                            "llm_analysis": llm_enriched_data,
                            "metrics": final_metrics
                        }
                        
                        self.knowledge_base[current_url] = final_structured_representation
                        self.visited.add(current_url)

                        # 6. Discovery
                        new_links = extract_valid_links(current_url, raw_html, self.visited)
                        print(f"   > Discovered {len(new_links)} new link(s).")
                        for link in new_links:
                            if link not in self.queue:
                                self.queue.append(link)

                    except Exception as e:
                        print(f"Error visiting {current_url}: {e}")

                browser.close()
        print("\nExploration complete. Browser session closed.")
        return self.knowledge_base

# # Usage
# if __name__ == "__main__":
#     # Example (this can be changed as needed)
#     # Note: You must ensure qwen3-coder:30b is pulled in Ollama and the server is running.
#     agent = ExplorerAgent("https://example.com", max_pages=2) 
#     results = agent.start_exploration()