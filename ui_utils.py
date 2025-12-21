import streamlit as st
def config_model_selector():
    st.sidebar.header("Model Configuration")

    # -----------------------------
    # Mode selection FIRST
    # -----------------------------
    model_mode = st.sidebar.selectbox(
        "Mode",
        ["Local (Ollama)", "API (Copilot)"],
        index=1
    )

    # -----------------------------
    # Model lists
    # -----------------------------
    copilot_models = [
        "gpt-5-mini",
        "gpt-4o-mini-2024-07-18",
        "gpt-4o-2024-11-20",
        "grok-code-fast-1",
        "gpt-4.1-2025-04-14"
    ]

    local_models = [
        "qwen3:4b",
        "freehuntx/qwen3-coder:8b",
    ]

    # -----------------------------
    # Conditional model selector
    # -----------------------------
    if model_mode == "API (Copilot)":
        model_name = st.sidebar.selectbox(
            "Choose Copilot Model",
            copilot_models,
            index=0
        )

        api_key = st.sidebar.text_input(
            "Copilot API Key",
            type="password"
        )

        if not api_key:
            st.sidebar.warning("Copilot API key required")

    else:
        model_name = st.sidebar.selectbox(
            "Choose Local Ollama Model",
            local_models,
            index=0
        )
        api_key = None
        st.sidebar.info("Using local Ollama model")

    # -----------------------------
    # Persist in session state
    # -----------------------------
    st.session_state["model_name"] = model_name
    st.session_state["model_mode"] = model_mode
    st.session_state["api_key"] = api_key