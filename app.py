import os
import tempfile
import streamlit as st
import json
import uuid

from rag_engine import RAGSystem, clean_directory
from firebase_admin import initialize_app, credentials, firestore, auth
from google.cloud.firestore import Client as FirestoreClient

# --- App Setup and Configuration ---
st.set_page_config(layout="wide", page_title="AI Codebase Reviewer")
st.title("AI Code Reviewer, Auditor & Codebase Archaeologist")

# Onboarding OR How-To Guide
st.markdown("""
Welcome to the **AI Codebase Archaeologist**! This tool uses advanced Retrieval-Augmented Generation (RAG) 
to analyze, index, and answer questions about any public GitHub repository.

### Demonstration Workflow:

1.  **Input:** Paste a public GitHub repository URL below. Use the **suggested repos** for an instant test.
2.  **Index:** Click **'Clone & Index'** to load and process the code.
3.  **Query:** Use the dedicated **Audit Button** for a specialized report, or ask custom questions in the chat.
""")
st.markdown("---")

# Initialize session state variables
if 'temp_dir' not in st.session_state:
    st.session_state.temp_dir = tempfile.mkdtemp()
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if 'rag_system' not in st.session_state:
    st.session_state.rag_system = None
if 'indexed_repo' not in st.session_state:
    st.session_state.indexed_repo = None
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'is_firebase_initialized' not in st.session_state:
    st.session_state.is_firebase_initialized = False

# Firestore/Firebase Initialization
try:
    if not st.session_state.is_firebase_initialized:
        app_id = os.environ.get('__app_id', 'default-app-id')
        firebase_config_str = os.environ.get('__firebase_config', '{}')
        initial_auth_token = os.environ.get('__initial_auth_token', None)

        firebase_config = json.loads(firebase_config_str) if firebase_config_str else {}

        if firebase_config:
            try:
                # Check if the app is already initialized before initializing again
                app_instance = initialize_app(name=app_id)
            except ValueError:
                # If it doesn't exist, initialize it
                cred = credentials.Certificate(firebase_config)
                initialize_app(cred, name=app_id)

        db = firestore.client(app=app_id)
        st.session_state.db = db

        if initial_auth_token:
            user = auth.sign_in_with_custom_token(initial_auth_token)
            st.session_state.user_id = user.uid
        else:
            st.session_state.user_id = "anonymous_user"

        st.session_state.is_firebase_initialized = True
        st.sidebar.success(f"🔑 Firebase Ready. User ID: {st.session_state.user_id[:8]}...")

except Exception as e:
    st.sidebar.warning(f"Running in Local Mode (Firebase not configured).")
    st.session_state.is_firebase_initialized = True
# END of Firebase Initialization

# Sidebar for Context Info and Cleanup
st.sidebar.title("Application Controls")
st.sidebar.markdown(f"**App ID:** `{os.environ.get('__app_id', 'N/A')}`")
if st.sidebar.button("Clear All Context & Restart"):
    clean_directory(st.session_state.temp_dir)
    # Reset specific keys but keep session_id and temp_dir structure
    for key in ['rag_system', 'indexed_repo', 'messages']:
        if key in st.session_state:
            del st.session_state[key]
    # Re-generate session ID for a truly fresh start logic
    st.session_state.session_id = str(uuid.uuid4())
    st.rerun()
st.sidebar.markdown("---")

# Repository Indexing Form
with st.form("repo_form", clear_on_submit=False):
    st.subheader("Index a Codebase")

    repo_url = st.text_input(
        "GitHub Repository URL",
        placeholder="e.g., https://github.com/streamlit/streamlit-example",
        value=st.session_state.indexed_repo if st.session_state.indexed_repo else "",
        help="Paste the full HTTPS URL of a PUBLIC GitHub repository (Python)."
    )

    # Suggested repos for easy testing
    with st.expander("Umm... Need a quick example? (Click to view suggested repos)"):
        st.markdown("""
        Try one of these public repositories for an instant demo:
        - **Clean Python:** `https://github.com/streamlit/streamlit-example`
        - **Vulnerable App (PyGoat):** `https://github.com/adeyosemanputra/pygoat` (Great for Security Audit)
        - **Vulnerable Flask:** `https://github.com/we45/Vulnerable-Flask-App` (Contains SQL Injection)
        """)

    submitted = st.form_submit_button("Clone & Index Codebase...", type="primary")

    if submitted and repo_url:
        with st.spinner(f"Cloning and indexing {repo_url}... This may take a moment."):
            try:
                clean_directory(st.session_state.temp_dir)
                # Pass session_id to RAGSystem to create unique paths
                rag_system = RAGSystem(st.session_state.session_id)
                rag_system.load_and_index(repo_url)

                st.session_state.rag_system = rag_system
                st.session_state.indexed_repo = repo_url
                st.session_state.messages = []

                st.success(f"Yayy!!! Indexed **code chunks** from **{repo_url}**! You can now ask questions below.")
                st.rerun()

            except Exception as e:
                st.error(f"Oops!!! Error during indexing: {e}. Please check the URL and ensure the repo is public.")
                st.session_state.rag_system = None
                st.session_state.indexed_repo = None

# Main Application Logic (Code Review & Chat)

if st.session_state.indexed_repo:
    # Display the active repo name clearly
    repo_name = st.session_state.indexed_repo.split('/')[-1]
    st.markdown(f"### Active Codebase: `{repo_name}`")
    st.markdown("---")

if st.session_state.rag_system:

    # ----------------------------------------------------
    # DEDICATED CODE REVIEW BUTTON
    # ----------------------------------------------------
    st.subheader("Specialized Audit & Code Review")
    st.info(
        "Click the button to trigger an expert LLM audit. The system will analyze the **entire indexed codebase** "
        "for security vulnerabilities, complexity, and best practice violations, providing an actionable report."
    )

    if st.button("Run Full Code Review & Audit", type="primary", use_container_width=True):
        audit_query = "Perform a complete security and refactoring audit across the codebase and provide actionable suggestions."

        st.session_state.messages.append({"role": "user", "content": audit_query})

        with st.chat_message("user"):
            st.write(audit_query)

        with st.chat_message("assistant"):
            with st.spinner("Executing Code Review Agent (Analyzing code quality and security)..."):
                try:
                    res = st.session_state.rag_system.ask(audit_query)
                    answer = res['result']
                    sources = res['source_documents']

                    st.write(answer)

                    with st.expander(f"📚 View Source Code Context ({len(sources)} Retrieved Chunks)"):
                        for i, doc in enumerate(sources):
                            source_name = doc.metadata.get('source', 'Unknown')
                            repo_path = st.session_state.rag_system.repo_path
                            display_path = source_name.replace(repo_path, '').strip(os.path.sep)

                            st.markdown(f"**Chunk {i + 1} from:** `{display_path}`")
                            st.code(doc.page_content, language="python")
                            if i < len(sources) - 1:
                                st.markdown("---")

                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    st.rerun()

                except Exception as e:
                    error_message = f"An error occurred during the audit: {e}"
                    st.error(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})

    st.markdown("---")

    # ----------------------------------------------------
    # GENERAL Q&A CHAT
    # ----------------------------------------------------
    st.subheader("General Q&A Chat")
    st.markdown(
        "Ask anything about the indexed codebase, e.g., *'Where is the main entry point?'* or *'How does the authentication flow work?'*")

    # Display previous messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle new user input
    if prompt := st.chat_input("Ask a question about the codebase..."):
        with st.chat_message("user"):
            st.markdown(prompt)

        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Searching for code context and generating answer..."):
                try:
                    res = st.session_state.rag_system.ask(prompt)
                    answer = res['result']
                    sources = res['source_documents']

                    st.write(answer)

                    with st.expander(f"View Source Code Context ({len(sources)} Retrieved Chunks)"):
                        for i, doc in enumerate(sources):
                            source_name = doc.metadata.get('source', 'Unknown')
                            repo_path = st.session_state.rag_system.repo_path
                            display_path = source_name.replace(repo_path, '').strip(
                                os.path.sep)

                            st.markdown(f"**Chunk {i + 1} from:** `{display_path}`")
                            st.code(doc.page_content, language="python")
                            if i < len(sources) - 1:
                                st.markdown("---")

                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as e:
                    error_message = f"An error occurred: {e}"
                    st.error(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})


else:
    st.info("Please complete Step 1 (Index a Codebase) above to enable the chat features.")