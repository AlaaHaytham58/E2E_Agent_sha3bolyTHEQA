import streamlit as st
import asyncio
from browser_manager import BrowserManager
import nest_asyncio
import os 
from llm_brain import LLMBrain
import subprocess
import sys
# Fix for Playwright's async loop inside Streamlit
nest_asyncio.apply()

st.set_page_config(layout="wide", page_title="AI QA Agent")

# Initialize Session State
if "browser_manager" not in st.session_state:
    st.session_state.browser_manager = BrowserManager()
if "scraped_data" not in st.session_state:
    st.session_state.scraped_data = None

# # Initialize a state to track if we are editing the plan or filling data
# if "plan_locked" not in st.session_state:
#     st.session_state.plan_locked = False
    
# # Initialize specific session states for granular control
# if "accepted_tests" not in st.session_state:
#     st.session_state.accepted_tests = []
# if "test_plan" not in st.session_state:
#     st.session_state.test_plan = []

# --- SIDEBAR: METRICS ---
with st.sidebar:
    st.header("System Metrics")
    st.metric("Status", "Ready" if st.session_state.scraped_data else "Idle")

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

    # Display Results (The "Agent's Brain")
    if st.session_state.scraped_data:
        st.success(f"Analyzed: {st.session_state.scraped_data.get('title')}")
        st.json(st.session_state.scraped_data.get('elements'))

# RIGHT COLUMN: Visual Context
with col2:
    st.subheader("Live Browser View")
    if "current_screenshot" in st.session_state and st.session_state.current_screenshot:
        st.image(st.session_state.current_screenshot, caption="Agent's View")
    else:
        st.info("No active browser session.")


if "brain" not in st.session_state:
    st.session_state.brain = LLMBrain(model="qwen3:4b") # Make sure you have this model pulled!

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
        
        if st.button("Generate Test Code"):
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
                # expand_key = f"expand_{test_file}"
                # if expand_key not in st.session_state:
                #     st.session_state[expand_key] = True  # افتراضي: مفتوح

                # with st.expander(f"🐍 Run: {test_file}", expanded=st.session_state[expand_key]):
                with st.expander(f"🐍 Run: {test_file}", expanded=True):  
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
                                    if new_videos:
                                        # خذ أول فيديو جديد (عادةً واحد فقط)
                                        video_name = next(iter(new_videos))
                                        video_path = os.path.join(video_dir, video_name)
                                    
                                    # --- احفظ النتيجة + مسار الفيديو ---
                                    st.session_state[f"result_{test_file}"] = result
                                    st.session_state[f"video_{test_file}"] = video_path
                                    
                                except subprocess.TimeoutExpired:
                                    st.error("Test Timed Out (Limit: 120s)")
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
                                    st.video(st.session_state[video_key])
                                
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
                                
                                if col_next_2.button("🚀 Explore This URL", key=f"cont_{test_file}"):
                                    if next_url:
                                        # 1. Update the Target URL
                                        st.session_state.url_input = next_url # Update input box
                                        
                                        # 2. Reset Pipeline States
                                        st.session_state.scraped_data = None
                                        st.session_state.test_plan = None
                                        st.session_state.approved_tests = None
                                        st.session_state.generated_code_map = {}
                                        
                                        # 3. Trigger Exploration immediately
                                        with st.spinner(f"Agent is analyzing {next_url} (with saved session)..."):
                                            # The browser_manager will automatically pick up 'auth.json'
                                            # because we implemented that check in start_browser()!
                                            async def run_next_explore():
                                                # Ensure browser is restarted to pick up new auth.json
                                                await st.session_state.browser_manager.close() 
                                                st.session_state.browser_manager = BrowserManager()
                                                
                                                data = await st.session_state.browser_manager.explore_url(next_url)
                                                screenshot = await st.session_state.browser_manager.capture_screenshot()
                                                return data, screenshot

                                            data, screenshot = asyncio.run(run_next_explore())
                                            st.session_state.scraped_data = data
                                            st.session_state.current_screenshot = screenshot
                                            
                                            # 4. Force Reset to Phase 2 (Design)
                                            st.session_state.current_step = "design" # Or clear it to fall through
                                            # Note: You might need to adjust your main if/else logic to handle this
                                            # Easier way: Just clear everything and let the user see the new 'Exploration' result
                                            del st.session_state["current_step"] 
                                            st.rerun()
                                    else:
                                        st.warning("Please enter the URL you want to test next.")
                            else:               
                                st.error("❌ TEST FAILED")
                                st.text("Error Trace:")
                                st.code(res.stderr, language="bash")
                                
                                # عرض الفيديو إن وُجد
                                video_key = f"video_{test_file}"
                                if video_key in st.session_state and st.session_state[video_key]:
                                    st.markdown("### 🎥 Test Execution Video")
                                    st.video(st.session_state[video_key])
                                
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
                                        # 1. Read the broken file (نفس المتغيرات)
                                        file_path = f"generated_tests/{test_file}"
                                        with open(file_path, "r", encoding="utf-8") as f:
                                            broken_code = f.read()
                                        
                                        # 2. Call the Healer (نفس الاستدعاء)
                                        fixed_code = st.session_state.brain.fix_generated_code(
                                            broken_code, 
                                            res.stderr
                                        )
                                        
                                        # 3. Overwrite the file (نفس المنطق)
                                        with open(file_path, "w", encoding="utf-8") as f:
                                            f.write(fixed_code)
                                            
                                        st.success("Code patched automatically! Re-running test...")
                                        
                                        # Clear old result and trigger re-run to test the fix
                                        del st.session_state[f"result_{test_file}"]
                                        st.rerun()
                                else:
                                    st.error(f"🚑 Self-Healing FAILED after {max_attempts} attempts.")
                                # Leave the error visible for debugging
                                # st.error("❌ TEST FAILED")
                                # st.text("Error Trace:")
                                # st.code(res.stderr, language="bash")
                                # # If there was standard output before crash, show it too
                                # st.markdown("---")
                                # st.write("### 🚑 Self-Healing")
                                
                                # if st.button(f"Attempt Auto-Fix for {test_file}", key=f"fix_{test_file}"):
                                #     with st.spinner("Analyzing error and patching code..."):
                                        
                                #         # 1. Read the broken file
                                #         file_path = f"generated_tests/{test_file}"
                                #         with open(file_path, "r", encoding="utf-8") as f:
                                #             broken_code = f.read()
                                        
                                #         # 2. Call the Healer
                                #         fixed_code = st.session_state.brain.fix_generated_code(
                                #             broken_code, 
                                #             res.stderr # Pass the error log
                                #         )
                                        
                                #         # 3. Overwrite the file with the fix
                                #         with open(file_path, "w", encoding="utf-8") as f:
                                #             f.write(fixed_code)
                                            
                                #         st.success("Code patched! Try running it again.")
                                        
                                #         # Optional: Clear the old error result so the UI looks clean
                                #         del st.session_state[f"result_{test_file}"]
                                #         st.rerun()
            
            st.divider()
            if st.button("🔄 Start New Session (Reset)"):
                # Clear state to loop back to Phase 1
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()



# Cleanup on exit (optional but good practice)
if st.button("Close Browser"):
  asyncio.run(st.session_state.browser_manager.close())  
  
  
  