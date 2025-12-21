import streamlit as st
import asyncio
from browser_manager import BrowserManager
import nest_asyncio
import os 
import shutil
from llm_brain import LLMBrain
import subprocess
import sys
import pandas as pd
from ui_utils import config_model_selector



# Fix for Playwright's async loop inside Streamlit
nest_asyncio.apply()

# ---- Auto cleanup on new Streamlit session ----
if "initialized" not in st.session_state:
    st.session_state.initialized = True

    for folder in ["generated_tests", "test_videos", "artifacts"]:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Cleanup failed for {folder}: {e}")

st.set_page_config(layout="wide", page_title="AI QA Agent")

# Initialize Session State
if "browser_manager" not in st.session_state:
    st.session_state.browser_manager = BrowserManager()
if "scraped_data" not in st.session_state:
    st.session_state.scraped_data = None

# Salma: Multipage Explorartion
if "brain" not in st.session_state:
    st.session_state.brain = LLMBrain() # Make sure you have this model pulled!

# Salma: Multipage Explorartion
if "multipage_result" not in st.session_state:
    st.session_state.multipage_result = None

# # Initialize a state to track if we are editing the plan or filling data
# if "plan_locked" not in st.session_state:
#     st.session_state.plan_locked = False
    
# # Initialize specific session states for granular control
# if "accepted_tests" not in st.session_state:
#     st.session_state.accepted_tests = []
# if "test_plan" not in st.session_state:
#     st.session_state.test_plan = []
def render_llm_metrics_sidebar(brain):
    st.sidebar.header("📊 LLM Metrics")

    summary = brain.get_metrics_summary()

    col1, col2 = st.sidebar.columns(2)
    col1.metric("LLM Calls", summary["total_calls"])
    col2.metric("Total Tokens", summary["total_tokens"])

    st.sidebar.metric(
        "Avg Latency (s)",
        f"{summary['average_time']:.3f}"
    )

    st.sidebar.metric("Errors", summary["errors"])

    st.sidebar.divider()

    if brain.metrics:
        df = pd.DataFrame(brain.metrics)

        st.sidebar.subheader("🔢 Per-Call Metrics")
        st.sidebar.dataframe(
            df[["llm_calls", "tokens", "time", "model", "mode"]],
            use_container_width=True,
            height=250
        )

        numeric = df[["llm_calls", "tokens", "time"]].to_numpy()

        # st.sidebar.subheader("🧮 Metrics Matrix")
        # st.sidebar.code(numeric, language="python")
    else:
        st.sidebar.info("No LLM calls yet.")


# if "brain" not in st.session_state:
#     st.session_state.brain = LLMBrain()

def render_sidebar():
    # 1. Model selector (from ui_utils)
    config_model_selector()
    
    current_config = (
        st.session_state.model_mode,
        st.session_state.model_name,
        st.session_state.api_key,
    )
    previous_config = st.session_state.get("_llm_config")

    if current_config != previous_config:
        st.session_state._llm_config = current_config

        st.session_state.brain = LLMBrain(
            model=st.session_state.model_name,
            api_key=st.session_state.api_key,
            # is_copilot=st.session_state.model_mode == "API (Copilot)",
        )

        st.toast("🔄 LLM backend switched")
        
    st.sidebar.divider()

    # 2. LLM metrics
    render_llm_metrics_sidebar(st.session_state.brain)

    st.sidebar.divider()

    # 3. System status
    st.sidebar.header("🖥️ System Status")
    st.sidebar.metric(
        "Status",
        "Ready" if "llm_output" in st.session_state else "Idle"
    )
render_sidebar()


#render_llm_metrics_sidebar(st.session_state.brain)

# Sidebar
# with st.sidebar:
#     st.header("System Metrics")
#     st.metric("Status", "Ready" if "llm_output" in st.session_state else "Idle")

# Main output
if "llm_output" in st.session_state:
    st.subheader("Output")
    st.dataframe(st.session_state.llm_output)

# --- MAIN LAYOUT ---
st.title("🤖 Human-in-the-Loop Web Tester")

col1, col2 = st.columns([1, 1])

# LEFT COLUMN: Controls & Dialogue
with col1:
    st.subheader("1. Exploration")
    url_input = st.text_input("Enter URL to Test", "https://saucedemo.com")
    
    if st.button("Start Exploration"):
        with st.spinner("Agent is analyzing the page..."):
            # Run the Async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 1. Start Browser & Go to URL
            manager = st.session_state.browser_manager
            data = loop.run_until_complete(manager.explore_url(url_input))
            st.session_state.scraped_data = data
            
            # 2. Capture Screenshot for visualization
            screenshot = loop.run_until_complete(manager.capture_screenshot())
            st.session_state.current_screenshot = screenshot

    # Salma: Multipage Explorartion
    st.markdown("---")
    st.caption("Multipage (Main Path) Exploration")
    max_steps = st.number_input("Max steps", min_value=1, max_value=25, value=5, step=1, key="mp_max_steps")
    journey_hint = st.selectbox(
        "Journey type",
        options=["auto", "signup", "ecommerce"],
        index=0,
        key="mp_journey_hint",
    )
    stop_on_input_required = st.checkbox(
        "Stop when user input is required (checkpoint)",
        value=True,
        key="mp_stop_on_input",
    )

    # Salma: Multipage Explorartion
    if st.button("Auto Explore Main Path"):
        with st.spinner("Agent is exploring the main path..."):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            manager = st.session_state.browser_manager
            hint = None if journey_hint == "auto" else journey_hint

            result = loop.run_until_complete(
                manager.explore_main_path(
                    url_input,
                    brain=st.session_state.brain,
                    max_steps=int(max_steps),
                    journey_hint=hint,
                    strict=True,
                    stop_on_input_required=bool(stop_on_input_required),
                )
            )
            st.session_state.multipage_result = result

            checkpoint = (result or {}).get("checkpoint")
            if checkpoint and isinstance(checkpoint, dict):
                # Promote checkpoint page into the existing pipeline shape.
                st.session_state.scraped_data = {
                    "title": checkpoint.get("title"),
                    "url": checkpoint.get("url"),
                    "cleaned_dom": checkpoint.get("cleaned_dom"),
                    "elements": checkpoint.get("elements", []),
                }

                # Reset design/execution state so Phase 2 starts clean.
                st.session_state.test_plan = []
                st.session_state.accepted_tests = []
                st.session_state.plan_locked = False
                st.session_state.pop("approved_tests", None)
                st.session_state.pop("generated_code_map", None)
                st.session_state.pop("current_step", None)

            # Update screenshot to show the checkpoint page.
            screenshot = loop.run_until_complete(manager.capture_screenshot())
            st.session_state.current_screenshot = screenshot

            st.rerun()

    # Display Results (The "Agent's Brain")
    if st.session_state.scraped_data:
        st.success(f"Analyzed: {st.session_state.scraped_data.get('title')}")
        st.json(st.session_state.scraped_data.get('elements'))

        # Salma: Multipage Explorartion
        if st.session_state.get("multipage_result"):
            mp = st.session_state.multipage_result
            visited_count = len((mp or {}).get("history") or [])
            st.info(
                f"Multipage result: visited={visited_count}, stop_reason={mp.get('stop_reason')}, stop_details={mp.get('stop_details')}"
            )

            with st.expander("Visited Pages (Main Path)", expanded=False):
                for step in (mp.get("history") or []):
                    meta = (step or {}).get("_meta") or {}
                    st.write(f"Step {meta.get('step_index')}: {step.get('url')}")

# RIGHT COLUMN: Visual Context
with col2:
    st.subheader("Live Browser View")
    if "current_screenshot" in st.session_state and st.session_state.current_screenshot:
        st.image(st.session_state.current_screenshot, caption="Agent's View")
    else:
        st.info("No active browser session.")

# Salma : Multipage Explorartion 
# Commenting out to avoid re-initialization
# if "brain" not in st.session_state:
#     st.session_state.brain = LLMBrain(model="qwen3:4b") # Make sure you have this model pulled!

# Initialize specific session states for granular control
if "accepted_tests" not in st.session_state:
    st.session_state.accepted_tests = []
if "test_plan" not in st.session_state:
    st.session_state.test_plan = []
if "plan_locked" not in st.session_state:
    st.session_state.plan_locked = False

# --- PHASE 2: GRANULAR COLLABORATIVE DESIGN ---
if st.session_state.scraped_data:
    st.divider()
    st.subheader("2. Collaborative Test Design")
    
    # ---------------------------------------------------------
    # STEP A: INITIAL GENERATION (Only if we have nothing)
    # ---------------------------------------------------------
    if not st.session_state.test_plan and not st.session_state.accepted_tests and not st.session_state.plan_locked:
        if st.button("Generate Initial Plan"):
            with st.spinner("🤖 Agent is designing tests..."):
                # 1. RAG Retrieval (Optional - if you implemented memory)
                memory_context = None
                if "memory" in st.session_state:
                     page_title = st.session_state.scraped_data.get('title', '')
                     memory_context = st.session_state.memory.retrieve_context(page_title)

                # 2. Generation
                plan = st.session_state.brain.generate_test_plan(
                    st.session_state.scraped_data, 
                    memory_context=memory_context
                )
                st.session_state.test_plan = plan
                st.rerun()

    # ---------------------------------------------------------
    # STEP B: THE WORKBENCH (Review, Accept, Refine)
    # ---------------------------------------------------------
    elif not st.session_state.plan_locked:
        
        # --- 1. DISPLAY ACCEPTED TESTS (The "Done" Pile) ---
        if st.session_state.accepted_tests:
            st.success(f"✅ Locked In ({len(st.session_state.accepted_tests)} tests)")
            for i, test in enumerate(st.session_state.accepted_tests):
                with st.expander(f"🔒 {test['name']}", expanded=False):
                    st.write(test['description'])
                    if st.button(f"Unlock / Edit", key=f"unlock_{i}"):
                        st.session_state.test_plan.append(test)
                        st.session_state.accepted_tests.pop(i)
                        st.rerun()
            st.divider()

        # --- 2. DISPLAY PENDING TESTS (The "Working" Pile) ---
        if st.session_state.test_plan:
            st.info(f"📝 Drafts / Pending Review ({len(st.session_state.test_plan)} tests)")
            st.caption("Approve the good ones, delete the bad ones, or refine the rest.")
            
            indices_to_accept = []
            indices_to_remove = []
            
            for i, test in enumerate(st.session_state.test_plan):
                col_desc, col_actions = st.columns([3, 1])
                with col_desc:
                    st.markdown(f"**{test['name']}**")
                    st.caption(test['description'])
                with col_actions:
                    if st.button("✅ Accept", key=f"acc_{i}"):
                        indices_to_accept.append(i)
                    if st.button("🗑️ Remove", key=f"rem_{i}"):
                        indices_to_remove.append(i)
                st.markdown("---")

            # PROCESS ACTIONS
            if indices_to_accept or indices_to_remove:
                all_indices = sorted(list(set(indices_to_accept + indices_to_remove)), reverse=True)
                for idx in all_indices:
                    test_item = st.session_state.test_plan.pop(idx)
                    if idx in indices_to_accept:
                        st.session_state.accepted_tests.append(test_item)
                        # RAG Memory Hook (if enabled)
                        if "memory" in st.session_state:
                            st.session_state.memory.remember_acceptance(
                                test_item['name'], test_item['description'], 
                                st.session_state.scraped_data.get('title', '')
                            )
                    elif idx in indices_to_remove and "memory" in st.session_state:
                        st.session_state.memory.remember_rejection(
                            test_item['name'], "Removed by user", 
                            st.session_state.scraped_data.get('title', '')
                        )
                st.rerun()

            # --- 3. REFINE THE REMAINDER ---
            if st.session_state.test_plan:
                st.write("### 🗣️ Refine Remaining Drafts")
                user_feedback = st.text_area("Feedback for drafts only:", placeholder="E.g. 'Make them specific to the Cart page.'")
                
                if st.button("🔄 Refine Pending Tests"):
                    with st.spinner("Refining only the pending drafts..."):
                        new_plan = st.session_state.brain.refine_test_plan(
                            st.session_state.test_plan, user_feedback, st.session_state.scraped_data
                        )
                        st.session_state.test_plan = new_plan
                        st.rerun()

        # --- 4. LOCK BUTTON (Proceed to Step C) ---
        # Show this if we have accepted tests OR if user just wants to proceed with empty/current state
        if st.session_state.accepted_tests:
            st.divider()
            if st.session_state.test_plan:
                st.warning(f"You still have {len(st.session_state.test_plan)} pending drafts. Proceeding will discard them.")
            
            if st.button("🚀 Proceed to Data Entry (Phase 3)", type="primary"):
                st.session_state.plan_locked = True
                # Promote accepted tests to the main 'test_plan' for the next step
                st.session_state.test_plan = st.session_state.accepted_tests
                st.rerun()

    # ---------------------------------------------------------
    # STEP C: DATA ENTRY (The "Engineer" View)
    # ---------------------------------------------------------
    else:
        st.success("Plan Locked. Now please provide the test data.")
        
        if st.button("🔙 Unlock / Edit Plan"):
            st.session_state.plan_locked = False
            # We need to restore the state so 'accepted_tests' are kept safe
            # Currently test_plan has the accepted tests, so we are good to just unlock.
            st.rerun()
            
        st.divider()
        
        with st.form("final_approval_form"):
            approved_tests = []
            for i, test in enumerate(st.session_state.test_plan):
                st.markdown(f"**Test {i+1}: {test['name']}**")
                is_selected = st.checkbox("Include", value=True, key=f"sel_{i}")
                
                user_data = {}
                missing_fields = test.get("missing_data", [])
                if missing_fields:
                    cols = st.columns(len(missing_fields))
                    for idx, field in enumerate(missing_fields):
                        val = cols[idx].text_input(f"Value for '{field}'", key=f"final_data_{i}_{field}")
                        if val: user_data[field] = val
                else:
                    st.caption("No data input required.")
                st.divider()
                
                if is_selected:
                    test["user_data"] = user_data
                    approved_tests.append(test)
            
            if st.form_submit_button("🚀 Approve & Generate Code", type="primary"):
                st.session_state.approved_tests = approved_tests
                st.session_state.current_step = "implementation"
                st.rerun()
                

# --- PHASE 3: IMPLEMENTATION (Code Generation) ---
if "approved_tests" in st.session_state and st.session_state.approved_tests:
    st.divider()
    st.subheader("3. Implementation (Code Generation)")
    
    # Initialize a place to store the generated code
    if "generated_code_map" not in st.session_state:
        st.session_state.generated_code_map = {}

    col_gen, col_display = st.columns([1, 2])
    
    with col_gen:
        st.info(f"Ready to generate {len(st.session_state.approved_tests)} test scripts.")

        # Manual cleanup helper to remove stale generated files
        if st.button("🧹 Clean Generated Tests"):
            if os.path.exists("generated_tests"):
                try:
                    shutil.rmtree("generated_tests")
                    st.session_state.generated_code_map = {}
                    st.success("Old generated tests removed.")
                except Exception as e:
                    st.error(f"Failed to remove generated tests: {e}")
            else:
                st.info("No generated_tests directory found.")
        
        if st.button("Generate Test Code"):
            # Pre-generation cleanup to avoid stale views
            if os.path.exists("generated_tests"):
                try:
                    shutil.rmtree("generated_tests")
                except Exception as e:
                    st.warning(f"Could not remove old generated_tests: {e}")
            os.makedirs("generated_tests", exist_ok=True)

            progress_bar = st.progress(0)
            
            for i, test in enumerate(st.session_state.approved_tests):
                with st.spinner(f"Writing code for: {test['name']}..."):
                    # 1. Generate Code
                    code = st.session_state.brain.generate_playwright_code(
                        test, 
                        st.session_state.scraped_data
                    )
                    
                    # 2. Store in Session State
                    st.session_state.generated_code_map[test['name']] = code
                    
                    # 3. Save to File (Actual "Implementation")
                    if not os.path.exists("generated_tests"):
                        os.makedirs("generated_tests")
                    
                    # Create a safe filename
                    safe_name = test['name'].lower().replace(" ", "_").replace("/", "")
                    file_path = f"generated_tests/test_{safe_name}.py"
                    
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(code)
                    
                    # Update Progress
                    progress_bar.progress((i + 1) / len(st.session_state.approved_tests))
            
            st.success("All tests generated successfully!")
            st.session_state.current_step = "verification"
            st.rerun()

    # DISPLAY GENERATED CODE (Review Code)
    with col_display:
        if st.session_state.generated_code_map:
            st.write("### 💾 Generated Scripts")
            
            # Create tabs for each test to keep UI clean
            test_names = list(st.session_state.generated_code_map.keys())
            tabs = st.tabs(test_names)
            
            for i, name in enumerate(test_names):
                with tabs[i]:
                    code_content = st.session_state.generated_code_map[name]
                    st.code(code_content, language="python")
                    st.caption(f"Saved to: generated_tests/test_{name.lower().replace(' ', '_')}.py")

                    # Quick helper: inject video recording into generated script if missing
                    if st.button("🔧 Inject Video Recording", key=f"inject_vid_{name}"):
                        file_path = f"generated_tests/test_{name.lower().replace(' ', '_')}.py"
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                orig = f.read()
                        except Exception as e:
                            st.error(f"Could not read file: {e}")
                            orig = None

                        if orig:
                            if "record_video_dir" in orig or "record_video" in orig:
                                st.info("Video recording already present in script.")
                            else:
                                patched = None
                                if "page = browser.new_page()" in orig:
                                    patched = orig.replace(
                                        "page = browser.new_page()",
                                        "context = browser.new_context(record_video_dir=\"test_videos\", record_video_size={'width':1280,'height':720})\n            page = context.new_page()"
                                    )
                                elif "browser.new_page()" in orig:
                                    patched = orig.replace(
                                        "browser.new_page()",
                                        "context = browser.new_context(record_video_dir=\"test_videos\", record_video_size={'width':1280,'height':720})\n            context.new_page()"
                                    )
                                else:
                                    st.warning("Could not find an insertion point to inject video recording. Please edit the script manually.")

                                if patched:
                                    try:
                                        with open(file_path, 'w', encoding='utf-8') as f:
                                            f.write(patched)
                                        st.session_state.generated_code_map[name] = patched
                                        st.success("✅ Injected video recording into script and saved.")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed to write patched file: {e}")

# --- PHASE 4: VERIFICATION (Execution) ---
if st.session_state.get("current_step") == "verification":
    st.divider()
    st.subheader("4. Verification & Execution")
    
    # 1. List all generated test files
    if not os.path.exists("generated_tests"):
        st.warning("No tests found. Please go back to Implementation.")
    else:
        test_files = [f for f in os.listdir("generated_tests") if f.endswith(".py")]
        
        if not test_files:
            st.warning("No Python files found in generated_tests/")
        
        else:
            st.write(f"Found {len(test_files)} executable test scripts.")
            
            # Create a "Run" card for each test
            for test_file in test_files:
                # --- تتبع حالة التوسيع لكل اختبار ---
                expand_key = f"expand_{test_file}"
                if expand_key not in st.session_state:
                    st.session_state[expand_key] = True  # افتراضي: مفتوح

                with st.expander(f"🐍 Run: {test_file}", expanded=st.session_state[expand_key]):
                    
                    col_actions, col_logs = st.columns([1, 2])
                    
                    with col_actions:
                        if st.button(f"▶️ Run {test_file}", key=f"run_{test_file}"):
                            with st.spinner(f"Executing {test_file}..."):
                                try:
                                    # EXECUTION ENGINE
                                    # Runs the script as a separate process: 'python generated_tests/test_xyz.py'
                                    # # Store results in session state to persist after rerun
                                    # --- قبل التشغيل: احصل على قائمة الفيديوهات الحالية ---
                                    video_dir = "test_videos"
                                    os.makedirs(video_dir, exist_ok=True)
                                    existing_videos = set(os.listdir(video_dir))
                                    
                                    # --- تشغيل الاختبار ---
                                    result = subprocess.run(
                                        [sys.executable, f"generated_tests/{test_file}"],
                                        capture_output=True,
                                        text=True,
                                        timeout=120
                                    )
                                    
                                    # --- بعد التشغيل: اكتشف الفيديو الجديد ---
                                    new_videos = set(os.listdir(video_dir)) - existing_videos
                                    video_path = None
                                    test_name = test_file.replace("test_", "").replace(".py", "")
                                    if new_videos:
                                        # خذ أول فيديو جديد (عادةً واحد فقط)
                                        video_name = next(iter(new_videos))
                                        src_video = os.path.join(video_dir, video_name)
                                        try:
                                            copied = asyncio.run(st.session_state.browser_manager.copy_latest_video_to_artifacts(test_name, src_video))
                                            if copied:
                                                video_path = copied
                                            else:
                                                video_path = src_video
                                        except Exception as e:
                                            print("DEBUG: copy to artifacts failed:", e)
                                            video_path = src_video

                                    # --- احفظ النتيجة + مسار الفيديو ---
                                    st.session_state[f"result_{test_file}"] = result
                                    st.session_state[f"video_{test_file}"] = video_path
                                    
                                except subprocess.TimeoutExpired:
                                    st.error("Test Timed Out (Limit: 60s)")
                                except Exception as e:
                                    st.error(f"Execution Failed: {e}")

                    # Display Logs (The "Evidence")
                    with col_logs:
                        if f"result_{test_file}" in st.session_state:
                            res = st.session_state[f"result_{test_file}"]
                            
                            if res.returncode == 0:
                                st.success("✅ TEST PASSED")
                                st.text("Output Logs:")
                                st.code(res.stdout, language="bash")
                                
                                # عرض الفيديو إن وُجد
                                video_key = f"video_{test_file}"
                                if video_key in st.session_state and st.session_state[video_key]:
                                    st.markdown("### 🎥 Test Execution Video")
                                    video_path = st.session_state[video_key]
                                    try:
                                        if os.path.exists(video_path):
                                            with open(video_path, 'rb') as vf:
                                                st.video(vf.read())
                                        else:
                                            st.video(video_path)
                                    except Exception as e:
                                        print("DEBUG: failed to read/display video bytes:", e)
                                        st.video(video_path)
                                else:
                                    st.info("No test video found for this run. If you want to capture video, use the '🔧 Inject Video Recording' helper on the generated script and re-run the test.")
                                
                                # --- SESSION CONTINUATION (THE LOOP) ---
                                st.markdown("---")
                                st.write("### 🔄 Continue Testing?")
                                st.info("Since this test passed, we might be on a new page (e.g., Dashboard).")
                                
                                col_next_1, col_next_2 = st.columns([2, 1])
                                
                                # Input for the next URL (User usually knows where the test lands)
                                # We pre-fill it with a guess or blank
                                next_url = col_next_1.text_input(
                                    "Enter the URL to explore next:", 
                                    placeholder="e.g. https://saucedemo.com/inventory.html",
                                    key=f"next_url_{test_file}"
                                )
                                
                                # if col_next_2.button("🚀 Explore This URL", key=f"cont_{test_file}"):
                                #     if next_url:
                                #         # 1. Update the Target URL
                                #         st.session_state.url_input = next_url # Update input box
                                        
                                #         # 2. Reset Pipeline States
                                #         st.session_state.scraped_data = None
                                #         st.session_state.test_plan = None
                                #         st.session_state.approved_tests = None
                                #         st.session_state.generated_code_map = {}
                                        
                                #         # 3. Trigger Exploration immediately
                                #         with st.spinner(f"Agent is analyzing {next_url} (with saved session)..."):
                                #             # The browser_manager will automatically pick up 'auth.json'
                                #             # because we implemented that check in start_browser()!
                                #             async def run_next_explore():
                                #                 # Ensure browser is restarted to pick up new auth.json
                                #                 await st.session_state.browser_manager.close() 
                                #                 st.session_state.browser_manager = BrowserManager()
                                                
                                #                 data = await st.session_state.browser_manager.explore_url(next_url)
                                #                 screenshot = await st.session_state.browser_manager.capture_screenshot()
                                #                 return data, screenshot

                                #             data, screenshot = asyncio.run(run_next_explore())
                                #             st.session_state.scraped_data = data
                                #             st.session_state.current_screenshot = screenshot
                                            
                                #             # 4. Force Reset to Phase 2 (Design)
                                #             st.session_state.current_step = "design" # Or clear it to fall through
                                #             # Note: You might need to adjust your main if/else logic to handle this
                                #             # Easier way: Just clear everything and let the user see the new 'Exploration' result
                                #             del st.session_state["current_step"] 
                                #             st.rerun()
                                #     else:
                                #         st.warning("Please enter the URL you want to test next.")
                            else:               
                                st.error("❌ TEST FAILED")
                                st.text("Error Trace:")
                                st.code(res.stderr, language="bash")
                                dom = None
                                art_dir = os.path.join("artifacts", test_file.replace("test_", "").replace(".py", ""))
                                dom_path = os.path.join(art_dir, "failure_dom.html")

                                if os.path.exists(dom_path):
                                    try:
                                        with open(dom_path, "r", encoding="utf-8") as f:
                                            dom = f.read()[:30000]  # cap size
                                        print("DEBUG: Loaded fresh DOM for healing.")
                                    except Exception as e:
                                        print("DEBUG: Could not read DOM:", e)
                                # عرض الفيديو إن وُجد
                                video_key = f"video_{test_file}"
                                if video_key in st.session_state and st.session_state[video_key]:
                                    st.markdown("### 🎥 Test Execution Video")
                                    video_path = st.session_state[video_key]
                                    try:
                                        if os.path.exists(video_path):
                                            with open(video_path, 'rb') as vf:
                                                st.video(vf.read())
                                        else:
                                            st.video(video_path)
                                    except Exception as e:
                                        print("DEBUG: failed to read/display video bytes:", e)
                                        st.video(video_path)
                                else:
                                    st.info("No test video found for this run. If you want to capture video, use the '🔧 Inject Video Recording' helper on the generated script and re-run the test.")
                                
                                # --- SESSION CONTINUATION FOR SELF-HEALING ATTEMPTS ---
                                healing_key = f"healing_{test_file}"
                                if healing_key not in st.session_state:
                                    st.session_state[healing_key] = {"attempts": 0}
                                
                                current_attempts = st.session_state[healing_key]["attempts"]
                                max_attempts = 5
                                
                                if current_attempts < max_attempts:
                                    st.session_state[healing_key]["attempts"] += 1
                                    st.warning(f"🚑 Self-Healing: Attempt {current_attempts + 1}/{max_attempts}")
                                    
                                    with st.spinner("Analyzing error and patching code automatically..."):
                                        # 1. Read the broken file
                                        file_path = f"generated_tests/{test_file}"
                                        with open(file_path, "r", encoding="utf-8") as f:
                                            broken_code = f.read()

                                        # 2. Call the Healer
                                        fixed_code = st.session_state.brain.fix_generated_code(
                                            broken_code,
                                            res.stderr,
                                            dom
                                        )

                                        # 3. Overwrite the file
                                        with open(file_path, "w", encoding="utf-8") as f:
                                            f.write(fixed_code)

                                        # 4. Update session state so the UI reflects the patched code
                                        try:
                                            if "generated_code_map" not in st.session_state:
                                                st.session_state.generated_code_map = {}

                                            # Try to find the display key that matches this file
                                            matched_key = None
                                            for k in st.session_state.generated_code_map.keys():
                                                safe = f"test_{k.lower().replace(' ', '_')}.py"
                                                if safe == test_file:
                                                    matched_key = k
                                                    break

                                            if matched_key:
                                                st.session_state.generated_code_map[matched_key] = fixed_code
                                                print(f"DEBUG: mapped patched code to key '{matched_key}'")
                                            else:
                                                # Fallback: use filename-derived key
                                                fallback_key = test_file.replace("test_", "").replace(".py", "").replace("_", " ")
                                                st.session_state.generated_code_map[fallback_key] = fixed_code
                                                print(f"DEBUG: used fallback key '{fallback_key}' for patched code")

                                            st.success("Code patched automatically and UI updated.")
                                            print("DEBUG: Self-heal updated generated_code_map for:", test_file)
                                        except Exception as e:
                                            print("DEBUG: Failed to update generated_code_map:", e)

                                        # 5. Clear old result
                                        st.session_state.pop(f"result_{test_file}", None)

                                        # Keep the expander open
                                        try:
                                            expand_key = f"expand_{test_file}"
                                            st.session_state[expand_key] = True
                                        except Exception:
                                            pass

                                        # 6. Re-run the patched test INLINE (no full rerun) so UI stays open
                                        st.info("Re-running fixed test now...")
                                        try:
                                            video_dir = "test_videos"
                                            os.makedirs(video_dir, exist_ok=True)
                                            existing_videos = set(os.listdir(video_dir))

                                            result2 = subprocess.run(
                                                [sys.executable, f"generated_tests/{test_file}"],
                                                capture_output=True,
                                                text=True,
                                                timeout=120
                                            )

                                            # Save result
                                            st.session_state[f"result_{test_file}"] = result2

                                            # Try to find new video(s)
                                            new_videos = set(os.listdir(video_dir)) - existing_videos
                                            video_path = None
                                            if new_videos:
                                                video_name = next(iter(new_videos))
                                                video_path = os.path.join(video_dir, video_name)
                                                st.session_state[f"video_{test_file}"] = video_path
                                                st.success("Recorded video attached from test run.")
                                            else:
                                                # Fallback: attempt to copy the latest recorded video into artifacts using BrowserManager
                                                try:
                                                    copied = asyncio.run(st.session_state.browser_manager.copy_latest_video_to_artifacts(test_file.replace("test_", "").replace(".py", "")))
                                                    if copied:
                                                        st.session_state[f"video_{test_file}"] = copied
                                                        st.success("Recorded video found and copied to artifacts.")
                                                        video_path = copied
                                                    else:
                                                        st.info("No video was recorded during re-run.")
                                                except Exception as e:
                                                    print("DEBUG: fallback copy_latest_video_to_artifacts failed:", e)
                                                    st.info("No video was recorded during re-run.")

                                            # Ensure the UI shows the patched code inline so user can see it without reloading
                                            try:
                                                # Display the updated code right here
                                                patched_display = None
                                                if 'generated_code_map' in st.session_state:
                                                    # find matching key
                                                    for k in st.session_state.generated_code_map.keys():
                                                        safe = f"test_{k.lower().replace(' ', '_')}.py"
                                                        if safe == test_file:
                                                            patched_display = st.session_state.generated_code_map[k]
                                                            break
                                                if not patched_display:
                                                    # Try fallback filename key
                                                    fallback_key = test_file.replace("test_", "").replace(".py", "").replace("_", " ")
                                                    patched_display = st.session_state.generated_code_map.get(fallback_key, None)

                                                if patched_display:
                                                    st.markdown("**Patched Script (preview):**")
                                                    st.code(patched_display, language="python")
                                                else:
                                                    st.info("Patched code applied to disk; refresh 'Generated Scripts' section to view it.")
                                            except Exception as e:
                                                print("DEBUG: while displaying patched code inline:", e)

                                            # Show immediate outcome
                                            if result2.returncode == 0:
                                                st.success("✅ Re-run passed")
                                                # also show stdout
                                                if result2.stdout:
                                                    st.text("Re-run output:")
                                                    st.code(result2.stdout, language="bash")
                                            else:
                                                st.error("❌ Re-run failed; inspect logs below")
                                                if result2.stderr:
                                                    st.text("Re-run error:")
                                                    st.code(result2.stderr, language="bash")

                                        except Exception as e:
                                            st.error(f"Re-run failed: {e}")

                                        # Refresh the UI so the 'Generated Scripts' tabs reflect the patched code and any copied video.
                                        # We already set the expander state so it will remain open after rerun.
                                        st.rerun()
                                else:
                                    st.error(f"🚑 Self-Healing FAILED after {max_attempts} attempts.")
                        
            
            st.divider()
            if st.button("🔄 Start New Session (Reset)"):
                # Clear session state
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                if "browser_manager" in st.session_state:
                    try:
                        asyncio.run(st.session_state.browser_manager.close())
                    except:
                        pass
                # Remove generated folders
                for folder in ["generated_tests", "test_videos", "artifacts"]:
                    if os.path.exists(folder):
                        try:
                            shutil.rmtree(folder)
                        except Exception as e:
                            print(f"Failed to remove {folder}: {e}")

                st.rerun()



# Cleanup on exit (optional but good practice)
if st.button("Close Browser"):
  asyncio.run(st.session_state.browser_manager.close())  
  
  
  