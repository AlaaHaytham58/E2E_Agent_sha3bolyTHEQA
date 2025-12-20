import ollama
import json
import re
import os
import time
from langfuse import Langfuse
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

class LLMBrain:
    def __init__(
        self,
        model="llama3.2",
        api_key=None,
        api_base=None,
        is_copilot=False
        ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.is_copilot = is_copilot

        self.client = None
        self.metrics = []

        self.langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )

        # ---- Global LLM  ----
        OPENAI_AVAILABLE = api_key is not None

        if OPENAI_AVAILABLE and self.api_key:
            if self.is_copilot:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.api_base,
                    default_headers={
                        "Copilot-Integration-Id": "vscode-chat",
                        "Editor-Version": "vscode/1.85.0",
                        "Editor-Plugin-Version": "copilot-chat/0.12.0",
                        "Openai-Intent": "conversation-panel",
                        "X-Request-Id": "qa-testing-agent",
                        "Copilot-Vision-Request": "true"
                    }
                )
                print("[LLM Config] Using GitHub Copilot mode with custom headers")
            else:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.api_base
                )
        else:
            self.client = None

    def chat(self, system_prompt, user_prompt, *, response_format=None, temperature=0.1):
        start_time = time.time()
        tokens = 0
        content = None

        # ----------------------
        # Optional Langfuse Trace
        # ----------------------
        trace = None
        generation = None

        if self.langfuse:
            trace = self.langfuse.trace(
                name="agent_brain_iteration",
                metadata={
                    "model": self.model,
                    "backend": "openai" if self.client else "ollama"
                }
            )

            generation = trace.generation(
                name="llm_call",
                model=self.model,
                input={
                    "system": system_prompt,
                    "user": user_prompt
                }
            )

        try:
            # ======================
            # OPENAI / COPILOT
            # ======================
            if self.client:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    response_format={"type": "json"} if response_format == "json" else None
                )

                content = response.choices[0].message.content
                tokens = response.usage.total_tokens or 0

            # ======================
            # LOCAL (OLLAMA)
            # ======================
            else:
                import ollama

                response = ollama.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    format="json" if response_format == "json" else None,
                    options={"temperature": temperature}
                )

                content = response["message"]["content"]
                tokens = response.get("eval_count", 0)

            # ----------------------
            # Optional JSON Parsing
            # ----------------------
            if response_format == "json":
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    raise ValueError("Model returned invalid JSON")

            latency = time.time() - start_time

            if generation:
                generation.end(
                    output=content,
                    usage={"total_tokens": tokens},
                    metadata={"latency_sec": latency}
                )

            self.metrics.append({
                "latency": latency,
                "tokens": tokens
            })

            return content

        except Exception as e:
            if generation:
                generation.end(error=str(e))
            raise

    def generate_test_plan(self, scraped_data,memory_context=None):
        elements = scraped_data.get("elements", [])
        clean_dom = scraped_data.get("cleaned_dom", "")[:10000] 
        # Construct the "Lessons Learned" string
        memory_prompt = ""
        if memory_context:
            if memory_context.get("avoid"):
                memory_prompt += "\n\n🚫 THINGS TO AVOID (Based on past feedback):\n" + "\n".join(memory_context["avoid"])
            if memory_context.get("emulate"):
                memory_prompt += "\n\n✅ PATTERNS TO FOLLOW (Accepted previously):\n" + "\n".join(memory_context["emulate"])
        system_prompt = f"""
        You are an expert QA Automation Engineer. 
        Analyze the HTML and generate 3-5 Playwright test scenarios.
        
        CRITICAL RULES:
        1. Output MUST be a valid JSON List of objects.
        2. Format: [{{"name": "...", "description": "...", "missing_data": [], "requires_auth": false}}]
        
        DATA HANDLING RULES:
        3. "missing_data" is for values the User must provide (e.g., valid_username).
        4. NEGATIVE TESTING: If a test case requires a field to be EMPTY (e.g., "Login with empty password"), do NOT include that field in "missing_data".
          - Correct: Name: "Empty Password", missing_data: ["username"] (Only ask for user, not password).
          - Incorrect: Name: "Empty Password", missing_data: ["username", "password"].
          
        Lesson Learned: 
        1. Output valid JSON list.
        {memory_prompt}  <-- RAG INJECTION HERE
        """
        
        user_prompt = f"""
        **Page Title:** {scraped_data.get('title')}
        **Elements:** {json.dumps(elements[:50])} 
        **DOM:** {clean_dom}
        """

        print("🧠 Brain is thinking...")
        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )

            parsed_json = json.loads(content)

            print(f"DEBUG: Raw LLM Output: {content}") # Keep this for debugging
            
            
            # --- FIX: ROBUST LIST EXTRACTION ---
            final_plan = []
            
            # Case 1: It's already a list (Perfect)
            if isinstance(parsed_json, list):
                final_plan = parsed_json
                
# Case 2: It's a dict (single test object or wrapped response)
            elif isinstance(parsed_json, dict):
                # If it looks like a single test object, wrap it
                if parsed_json.get("name") or parsed_json.get("description"):
                    final_plan = [parsed_json]
                    print("DEBUG: Parsed single test object; wrapped into list")
                else:
                    # Prefer lists of dicts (i.e., actual test arrays)
                    found_list = False
                    for key, value in parsed_json.items():
                        if isinstance(value, list) and value and isinstance(value[0], dict):
                            final_plan = value
                            found_list = True
                            print(f"DEBUG: Extracted plan from key: '{key}' (list of dicts)")
                            break

                    if not found_list:
                        # Fallback: first list we find (but warn if it's a list of primitives)
                        for key, value in parsed_json.items():
                            if isinstance(value, list):
                                final_plan = value
                                found_list = True
                                print(f"DEBUG: Extracted plan from key: '{key}' (fallback list)")
                                break

                    if not found_list:
                        print("Error: JSON is a dict but contains no suitable lists.")
                        return [{"name": "Error", "description": "LLM returned invalid format (Dict with no list).", "is_error": True}]
            
            
            # --- VALIDATION LOOP ---
            # Ensure every item has the required fields
            safe_plan = []
            for item in final_plan:
                # specific check to ignore strings if LLM returns ["test1", "test2"]
                if isinstance(item, dict):
                    safe_item = {
                        "name": item.get("name", item.get("test_name", "Unnamed Test")),
                        "description": item.get("description", "No description."),
                        "missing_data": item.get("missing_data", []),
                        "requires_auth": item.get("requires_auth", False)
                    }
                    safe_plan.append(safe_item)
            
            return safe_plan
            
        except Exception as e:
            print(f"LLM Error: {e}")
            return [{
                "name": "Error Generating Plan", 
                "description": f"The LLM failed: {str(e)}", 
                "missing_data": [],
                "is_error": True
            }]
    def generate_playwright_code(self, test_case, scraped_data):
        elements = scraped_data.get("elements", [])
        user_data = test_case.get("user_data", {})
        
        system_prompt = """
        You are an expert Playwright Automation Engineer (Python).
        Your task: Write a complete, standalone Python script.

        STRICT RULES:
        1. IMPORTS: You MUST use exactly this import line:
           from playwright.sync_api import sync_playwright
        2. VIDEO: The script MUST create a browser context with video recording enabled
           - Use: context = browser.new_context(record_video_dir="test_videos", record_video_size={"width":1280,"height":720})
           - Use: page = context.new_page()
           - After the test completes, close the page (page.close()) then copy the finalized video file
             into the test artifacts folder (artifacts/<TEST_NAME>/video.webm) using shutil.copy2(page.video.path(), dst).
        3. LOCATORS: Use resilient locators: page.get_by_role(), page.get_by_placeholder().
        4. DATA: Use the provided USER_DATA values.
        5. STRUCTURE:
           - Define a run() function.
           - Inside run(), use 'with sync_playwright() as p:'.
           - Launch browser with headless=False.
           - Create a context as specified above, and call 'page.set_default_timeout(5000)'.
           - At the end, ensure context.close() and browser.close() are called.
           - Call run() at the end under 'if __name__ == "__main__":'.
        6. STATE MANAGEMENT (CRITICAL):
           - If the test performed a login step and cookies should be preserved, save storage with:
             context.storage_state(path='auth.json')
        7. OUTPUT: Return ONLY the Python code (no markdown or explanations). Ensure code compiles.
        """
        
        user_prompt = f"""
        **Test Case Name:** {test_case['name']}
        **Description:** {test_case['description']}
        **URL:** {scraped_data.get('url')}
        **Available Elements:** {json.dumps(elements[:50])}
        **USER_DATA (Inject these values):** {json.dumps(user_data)}
        """

        print(f"🧠 Generating code for: {test_case['name']}...")
        
        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )

            parsed_json = json.loads(content)

            if "```python" in code:
                code = code.split("```python")[1].split("```")[0]
            elif "```" in code:
                code = code.split("```")[1].split("```")[0]
                
            return code.strip()

        except Exception as e:
            return f"# Error generating code: {str(e)}"
    def fix_generated_code(self, broken_code, error_log):
        """
        Takes broken code and the error trace, then rewrites the code to fix it.
        """
        system_prompt = """
        You are an expert Python Debugger for Playwright scripts.
        Your task is to FIX the provided code based on the error output.
        
        RULES:
        1. Analyze the ERROR TRACE to find the root cause (e.g., missing import, wrong locator, indentation).
        2. Retain the original logic and USER_DATA. Do not hallucinate new data.
        3. If the error is 'ModuleNotFoundError', fix the import statements.
           (Correct: from playwright.sync_api import sync_playwright)
        4. Return ONLY the fixed, executable Python code. No markdown, no explanations.
        """
        
        user_prompt = f"""
        **BROKEN CODE:**
        {broken_code}
        
        **ERROR TRACE:**
        {error_log}
        """

        print("🚑 Healer Agent is fixing the code...")
        
        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )

            parsed_json = json.loads(content)

            
            # Clean up Markdown
            code = response['message']['content']
            if "```python" in code:
                code = code.split("```python")[1].split("```")[0]
            elif "```" in code:
                code = code.split("```")[1].split("```")[0]
                
            return code.strip()

        except Exception as e:
            return f"# Fix failed: {str(e)}"      
    def refine_test_plan(self, current_plan, user_feedback, scraped_data):
        """
        Refines the existing test plan based on user critique.
        """
        elements = scraped_data.get("elements", [])
        clean_dom = scraped_data.get("cleaned_dom", "")[:10000]
        
        system_prompt = """
        You are an expert QA Automation Engineer.
        Your task is to MODIFY the existing Test Plan based on User Feedback.
        
        RULES:
        1. Keep existing tests unless the user asks to remove them.
        2. Add new tests if requested.
        3. Modify descriptions or names if requested.
        4. Output MUST be a valid JSON List of objects (same format as before).
        5. DATA HANDLING: For any new test, identify "missing_data" (e.g. ["username"]).
        6. NEGATIVE TESTING: If the user asks for a negative test (e.g. empty fields), do not ask for that data in "missing_data".
        """
        
        user_prompt = f"""
        **Current Test Plan:**
        {json.dumps(current_plan)}
        
        **User Feedback/Instructions:**
        "{user_feedback}"
        
        **Page Elements (Reference):**
        {json.dumps(elements[:50])}
        """

        print("🧠 Brain is refining the plan...")
        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )

            parsed_json = json.loads(content)


            
            # (Reuse your robust list extraction logic here)
            final_plan = []
            if isinstance(parsed_json, list):
                final_plan = parsed_json
            elif isinstance(parsed_json, dict):
                for val in parsed_json.values():
                    if isinstance(val, list):
                        final_plan = val
                        break
            
            # Validation Loop
            safe_plan = []
            for item in final_plan:
                safe_item = {
                    "name": item.get("name", "Unnamed Test"),
                    "description": item.get("description", ""),
                    "missing_data": item.get("missing_data", []),
                    "requires_auth": item.get("requires_auth", False)
                }
                safe_plan.append(safe_item)
                
            return safe_plan

        except Exception as e:
            return [{"name": "Error Refining Plan", "description": str(e), "is_error": True}]

    # Salma: Multipage Explorartion
    def classify_navigation_candidate(
        self,
        page_snapshot: dict,
        candidate: dict,
        *,
        journey_hint: str | None = None,
        strict: bool = True,
    ) -> dict:
        """Classify whether a navigation candidate should be followed.

        Supports multiple site types by allowing a journey_hint, e.g.:
        - "signup" / "onboarding" (multi-step wizards)
        - "ecommerce" (browse -> product -> add to cart -> cart -> checkout)

        Returns a dict:
        {
          "follow": bool,
          "confidence": float,
          "category": "service_flow"|"out_of_scope"|"blocker"|"unclear",
          "reason": str,
          "suggested_phase": str
        }
        """

        title = (page_snapshot or {}).get("title", "")
        url = (page_snapshot or {}).get("url", "")
        cleaned_dom = (page_snapshot or {}).get("cleaned_dom", "")

        # Keep DOM very small; this is a classification task.
        dom_snippet = (cleaned_dom or "")[:3000]

        system_prompt = f"""
You are an expert QA assistant deciding whether to follow a navigation action during fully-automatic main-path exploration.

Your job:
- Decide if the candidate is part of the MAIN SERVICE FLOW.
- Skip out-of-scope informational pages (e.g. About, Blog, Careers, Contact, Terms, Privacy, Help, FAQ).

This explorer supports two common journeys:
1) SIGNUP / ONBOARDING WIZARD:
   - Follow steps like Sign up / Register / Next / Continue / Submit / Finish.
   - Skip unrelated navigation like About.
2) ECOMMERCE MAIN PATH:
   - Prefer a single end-to-end purchase flow:
     Browse products -> open a product -> add to cart -> go to cart -> checkout.
   - Skip unrelated informational navigation.
   - Note: "Add to cart" may not change URL; it's still in-scope.

STRICT MODE: {"ON" if strict else "OFF"}
If STRICT MODE is ON and you are unsure, return follow=false and category="unclear".

OUTPUT RULES:
1) Output MUST be valid JSON object (not a list, not markdown).
2) Schema:
   {{
     "follow": true|false,
     "confidence": 0.0-1.0,
     "category": "service_flow"|"out_of_scope"|"blocker"|"unclear",
     "reason": "...",
     "suggested_phase": "signup"|"browse"|"product"|"cart"|"checkout"|"unknown"
   }}
3) Be conservative about following nav/footer links.
"""

        user_prompt = f"""
JOURNEY_HINT: {journey_hint or "auto"}

CURRENT_PAGE:
- title: {title}
- url: {url}

CANDIDATE:
{json.dumps(candidate, ensure_ascii=False)}

DOM_SNIPPET:
{dom_snippet}
"""

        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )

            parsed_json = json.loads(content)


            # Minimal validation + defaults.
            follow = bool(parsed.get("follow", False))
            confidence = parsed.get("confidence", 0.0)
            try:
                confidence = float(confidence)
            except Exception:
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))

            category = parsed.get("category", "unclear")
            if category not in {"service_flow", "out_of_scope", "blocker", "unclear"}:
                category = "unclear"

            suggested_phase = parsed.get("suggested_phase", "unknown")
            if suggested_phase not in {"signup", "browse", "product", "cart", "checkout", "unknown"}:
                suggested_phase = "unknown"

            reason = parsed.get("reason", "")
            if not isinstance(reason, str):
                reason = ""

            # Enforce strict-mode conservatism.
            if strict and category == "unclear":
                follow = False

            return {
                "follow": follow,
                "confidence": confidence,
                "category": category,
                "reason": reason,
                "suggested_phase": suggested_phase,
            }

        except Exception as e:
            return {
                "follow": False,
                "confidence": 0.0,
                "category": "unclear",
                "reason": f"classifier_error: {str(e)}",
                "suggested_phase": "unknown",
            }