import ollama
import json
import re
import os
import time
import numpy as np
from langfuse import Langfuse
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
def normalize_llm_output(content):
    """
    Ensures LLM output is returned as a Python list of dicts.
    Accepts:
      - JSON string
      - already-parsed list
    """
    if isinstance(content, list):
        # Already parsed
        return content

    if isinstance(content, str):
        content = content.strip()
        return json.loads(content)

    raise TypeError(f"Unsupported LLM output type: {type(content)}")
class LLMBrain:
    def __init__(
        self,
        model="gpt-5-mini",
        api_key=None,
        is_copilot=True
    ):
        self.model = model
        self.api_key = api_key or os.getenv("API_KEY")
        self.is_copilot = is_copilot

        self.client = None
        self.metrics = []
        self.llm_calls = 0 

        self.langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )
        print("copilot: ",self.is_copilot)
        if self.api_key:
            if self.is_copilot:
                self.client = OpenAI(
                    api_key=os.getenv("API_KEY"),
                    base_url="https://api.githubcopilot.com"
                )
                print("[LLM Config] Using GitHub Copilot backend")
            else:
                print("[LLM Config] Using Ollama backend")

        else:
            print("[LLM Config] No API key found, falling back to Ollama")
   
    def chat(
    self,
    system_prompt,
    user_prompt,
    *,
    response_format=None,
    temperature=0.1,
    parse_matrix=True,
    to_numpy=False
    ):
        start_time = time.time()
        tokens = 0
        content = None

        self.llm_calls += 1
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
            if self.client:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                )
                content = response.choices[0].message.content
                tokens = response.usage.total_tokens or 0

            else:
                response = ollama.chat(
                    model="freehuntx/qwen3-coder:8b",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    format="json" if response_format == "json" else None,
                    options={"temperature": temperature}
                )
                content = response["message"]["content"]
                tokens = response.get("eval_count", 0)

            content = normalize_llm_output(content)
            if parse_matrix:
                content = self._parse_matrix(content)
            if to_numpy:
                content = np.array(content)
            elapsed = time.time() - start_time
            self.metrics.append({
                "model": self.model,
                "mode": "openai" if self.client else "ollama",
                "time": elapsed,
                "tokens": tokens,
                "llm_calls": self.llm_calls
            })

            if generation:
                generation.end(
                    output=content,
                    usage={"total_tokens": tokens},
                    metadata={"latency_sec": elapsed}
                )
            
            elapsed = time.time() - start_time
            self.metrics.append({
                "model": self.model,
                "mode": "openai" if self.client else "ollama",
                "time": elapsed,
                "tokens": tokens,
                "llm_calls": self.llm_calls
            })

            if generation:
                generation.end(
                    output=content,
                    usage={"total_tokens": tokens},
                    metadata={"latency_sec": elapsed}
                )
            return content  # ✅ RETURN HERE

        except Exception as e:
            elapsed = time.time() - start_time
            self.metrics.append({
                "model": self.model,
                "mode": "openai" if self.client else "ollama",
                "time": elapsed,
                "tokens": 0,
                "error": str(e),
                "llm_calls": self.llm_calls
            })

            if generation:
                generation.end(error=str(e))

            raise RuntimeError(f"LLM call failed: {e}")
    def _parse_matrix(self, content):
        """
        Converts LLM output to Python matrix (list of lists).
        Accepts:
        - list of lists (already parsed)
        - stringified JSON matrix
        - simple string with numbers separated by commas/spaces
        """
        if isinstance(content, list):
            return content

        if isinstance(content, str):
            try:
                # Try JSON parse first
                parsed = content
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                # fallback: parse lines and numbers
                lines = content.strip().splitlines()
                matrix = []
                for line in lines:
                    # split by comma or space
                    row = [float(x) for x in re.split(r"[,\s]+", line.strip()) if x]
                    if row:
                        matrix.append(row)
                return matrix

        # fallback: return as-is
        return content
    

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
You are a senior QA Automation Engineer specializing in Playwright E2E testing.

Your task:
Analyze the provided HTML/DOM and visible elements, then generate 3–5
high-value end-to-end test scenarios that reflect realistic user behavior.

The tests should focus on CORE USER FLOWS (e.g., login, signup, checkout,
form submission, navigation, CRUD actions) — not trivial UI checks.

========================
🚨 OUTPUT RULES (STRICT)
========================
1. Output MUST be a valid JSON ARRAY only.
2. Do NOT wrap in markdown. Do NOT add explanations.
3. Each item MUST strictly follow this schema:

[
  {{
    "name": string,
    "description": string,
    "missing_data": list[string],
    "requires_auth": boolean
  }}
]

4. No trailing commas. No comments. No extra fields.

========================
🧪 TEST QUALITY RULES
========================
5. Each test MUST:
   - Be automatable using Playwright.
   - Describe a full user journey (actions + assertions).
   - Include at least one meaningful assertion
     (URL change, success message, element visible, data updated, etc.).

6. Prefer user-centric actions:
   - click buttons/links
   - fill inputs
   - submit forms
   - navigate pages
   - verify results

7. Avoid:
   - “Page loads” only tests.
   - Duplicate or overlapping scenarios.
   - Pure UI style checks (colors, fonts).

========================
🔎 SELECTOR GUIDANCE
========================
8. When describing steps, prefer resilient selectors:
   - get_by_role()
   - get_by_label()
   - get_by_text()
   - get_by_placeholder()
   over brittle CSS/XPath.

========================
📥 DATA HANDLING RULES
========================
9. "missing_data" is ONLY for values the user must provide later, such as:
   - valid_username
   - valid_password
   - email
   - product_name

10. If a value is clearly available in the DOM (e.g., visible text, options),
    do NOT ask for it in "missing_data".

11. NEGATIVE TESTS:
    If a field must be EMPTY, do NOT include it in missing_data.
    Example:
      Name: "Login with empty password"
      missing_data: ["username"]

========================
🔐 AUTH RULES
========================
12. Set "requires_auth": true ONLY if:
    - The test assumes the user is already logged in
    - Or starts from an authenticated area (dashboard, profile, etc.)

    Otherwise, false.

========================
🧠 REASONING RULES
========================
13. Base scenarios STRICTLY on:
    - Provided DOM
    - Elements list
    - Page title

14. Do NOT invent pages, features, or flows not implied by the content.

15. If the page appears to be:
    - Auth page → include login/validation flows.
    - Product/listing → include browse/select/action flows.
    - Form → include submit & validation flows.
    - Dashboard → include core management actions.

========================
📚 LESSONS LEARNED (RAG)
========================
You MUST respect the following guidance from past feedback:
{memory_prompt}

Return ONLY the JSON array.
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

            parsed_json = content

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
        8. ERROR CAPTURE: [CRITICAL]
        - Wrap test steps in try/except.
        - On exception:
            * Save current page HTML using page.content() into:
            artifacts/<TEST_NAME>/failure_dom.html
            * Also save a screenshot to:
            artifacts/<TEST_NAME>/failure.png
            * Then re-raise the exception.
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
            print(f"DEBUG: Raw LLM Output: {content}") # Keep this for debugging
            code = content

            if "```python" in code:
                code = code.split("```python")[1].split("```")[0]
            elif "```" in code:
                code = code.split("```")[1].split("```")[0]
                
            return code.strip()

        except Exception as e:
            return f"# Error generating code: {str(e)}"
    def fix_generated_code(self, broken_code, error_log,dom=None):
        """
        Takes broken code and the error trace, then rewrites the code to fix it.
        """
        system_prompt = """
            You are an expert Playwright self-healing agent and Python debugger.

            Your task is to FIX the provided Playwright Python script using:
            - the ERROR TRACE
            - and the CURRENT PAGE DOM (if provided).

            GOALS:
            - Produce a corrected, executable script.
            - Preserve the original test intent and logic.
            - Make selectors resilient against UI changes.

            RULES:

            1. ROOT CAUSE ANALYSIS:
            - Analyze the ERROR TRACE to identify the true cause:
                syntax error, import error, runtime exception, timeout, missing element,
                wrong locator, assertion failure, or flow issue.

            2. CODE-LEVEL FIXES FIRST:
            - Fix Python issues such as:
                * Syntax/indentation errors
                * NameError / AttributeError
                * Missing or wrong imports
            - If error is ModuleNotFoundError, ensure:
                from playwright.sync_api import sync_playwright

            3. UI / LOCATOR HEALING (when DOM is provided):
            - If the error indicates element not found, strict mode violation, timeout,
                or assertion mismatch:
                * Inspect the CURRENT PAGE DOM.
                * Identify the most likely replacement element.
                * Update selectors to use resilient locators:
                - page.get_by_role()
                - page.get_by_text()
                - page.get_by_placeholder()
            - Prefer visible text, roles, labels, and placeholders from DOM.
            - Avoid brittle selectors (CSS/XPath) unless absolutely necessary.

            4. PRESERVE INTENT & DATA:
            - Retain the original test flow and purpose.
            - Do NOT change the test scenario logic.
            - Do NOT hallucinate new steps or features.
            - Keep all USER_DATA values unchanged.

            5. MINIMAL, TARGETED CHANGES:
            - Modify only what is necessary to fix the failure.
            - Do not refactor unrelated parts of the script.

            6. PLAYWRIGHT BEST PRACTICES:
            - Ensure waits and actions are Playwright-safe.
            - Prefer built-in auto-waiting over arbitrary sleeps.
            - If needed, add small waits only to stabilize flaky steps.

            7. OUTPUT FORMAT (STRICT):
            - Return ONLY the fixed, executable Python code.
            - No markdown.
            - No explanations.
            - No comments about what was changed.
            - The code must compile and be runnable as-is.
            8. ERROR CAPTURE: [CRITICAL]
                - Wrap test steps in try/except.
                - On exception:
                    * Save current page HTML using page.content() into:
                    artifacts/<TEST_NAME>/failure_dom.html
                    * Also save a screenshot to:
                    artifacts/<TEST_NAME>/failure.png
                    * Then re-raise the exception.
            """
        
        user_prompt = f"""
            **BROKEN CODE:**
            {broken_code}

            **ERROR TRACE:**
            {error_log}

            **CURRENT PAGE DOM (after failure):**
            {dom if dom else "N/A"}
            """

        print("🚑 Healer Agent is fixing the code...")
        
        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )
            # Clean up Markdown
            code = content
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

            parsed_json = content


            
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
            - Decide if the candidate action is part of the PRIMARY SERVICE FLOW needed to complete the user's goal.
            - Skip out-of-scope or informational pages that do not advance the main journey
            (e.g., About, Blog, Careers, Contact, Terms, Privacy, Help, FAQ, Docs, Press, Community).

            This explorer supports two common journeys:

            1) SIGNUP / ONBOARDING WIZARD:
            - In-scope actions: Sign up, Register, Get started, Next, Continue, Submit, Finish, Verify.
            - Goal: reach a completed account / dashboard / confirmation.
            - Skip unrelated navigation, marketing pages, and footer links.

            2) ECOMMERCE MAIN PATH:
            - Prefer a single end-to-end purchase flow:
                Browse/list products -> open a product -> add to cart -> view cart -> checkout -> payment.
            - In-scope actions: product links, Add to cart, Cart, Checkout, Place order.
            - Skip unrelated navigation and informational pages.
            - Note: "Add to cart" may not change URL; still in-scope.

            OUT-OF-SCOPE examples:
            - Company info, policies, blogs, help centers, social links, external sites.

            BLOCKER examples:
            - Login/Signup required when already in checkout
            - Captcha, access denied, 404/500 errors
            - Broken links or disabled buttons
            - Hard paywalls that stop progress

            STRICT MODE: {"ON" if strict else "OFF"}
            If STRICT MODE is ON and you are uncertain, return:
            follow=false and category="unclear".

            IMPORTANT RULES:
            - Be conservative with header/footer or global navigation links.
            - Prefer actions that clearly advance the current journey.
            - Do NOT follow if the action might derail the main flow.

            OUTPUT RULES:
            1) Output MUST be a valid JSON object only.
            2) Schema:
            {{
                "follow": true|false,
                "confidence": 0.0-1.0,
                "category": "service_flow" | "out_of_scope" | "blocker" | "unclear",
                "reason": "short explanation",
                "suggested_phase": "signup" | "browse" | "product" | "cart" | "checkout" | "unknown"
            }}

            GUIDELINES:
            - Use category:
            * service_flow → clearly advances the journey.
            * out_of_scope → informational or irrelevant.
            * blocker → prevents progress.
            * unclear → ambiguous or insufficient info.
            - If category is not service_flow, suggested_phase should usually be "unknown".
            """
        user_prompt = f"""
            **Current Page Title:** {title}
            **Current Page URL:** {url}
            **Current Page DOM Snippet:** {dom_snippet}

            **Candidate Action Details:**
            {json.dumps(candidate)}

            {"**Journey Hint:** " + journey_hint if journey_hint else ""}
            """

        try:
            content = self.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
                temperature=0.1
            )

            parsed = content


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
    def get_metrics_summary(self):
        if not self.metrics:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "average_time": 0.0,
                "errors": 0,
                "per_model": {}
            }

        total_time = sum(m["time"] for m in self.metrics)
        total_tokens = sum(m.get("tokens", 0) for m in self.metrics)
        errors = sum(1 for m in self.metrics if "error" in m)

        per_model = {}
        for m in self.metrics:
            key = f"{m['mode']} / {m['model']}"
            stats = per_model.setdefault(
                key, {"count": 0, "total_time": 0.0, "total_tokens": 0, "errors": 0}
            )
            stats["count"] += 1
            stats["total_time"] += m["time"]
            stats["total_tokens"] += m.get("tokens", 0)
            if "error" in m:
                stats["errors"] += 1

        return {
            "total_calls": len(self.metrics),
            "total_tokens": total_tokens,
            "average_time": total_time / len(self.metrics),
            "errors": errors,
            "per_model": per_model
        }
    # --------------------------------------------------
    # RESET METRICS
    # --------------------------------------------------
    def reset_metrics(self):
        self.metrics.clear()