#!/usr/bin/env python3
"""
Streamlit app UI for the FacebookMessenger automation.
Collects all inputs via form and runs messenger in a background thread.
"""
import streamlit as st
import threading
import time
from messenger import FacebookMessenger
import os

st.set_page_config(page_title="Facebook Messenger Automation", layout="centered")

if "thread" not in st.session_state:
    st.session_state.thread = None
if "stop_event" not in st.session_state:
    st.session_state.stop_event = None
if "logs" not in st.session_state:
    st.session_state.logs = []
if "messenger" not in st.session_state:
    st.session_state.messenger = None

def log_append(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.logs.append(f"[{ts}] {msg}")

def start_process(form_values):
    # form_values: dict with keys collected from form
    st.session_state.logs = []
    stop_event = threading.Event()
    st.session_state.stop_event = stop_event

    def run_worker():
        try:
            log_append("Initializing messenger...")
            m = FacebookMessenger(
                firefox_binary=form_values["firefox_binary"] or None,
                geckodriver_path=form_values["geckodriver_path"] or None,
                headless=form_values["headless"],
                speed_seconds=form_values["speed_seconds"],
                log_callback=log_append
            )
            st.session_state.messenger = m

            ok, err = m.setup_driver()
            if not ok:
                log_append(f"Driver setup failed: {err}")
                return

            if not m.login_with_cookies(form_values["cookie_str"]):
                log_append("Login failed. Check cookies or network.")
                m.quit()
                return

            m.haters_name = form_values["haters_name"]
            if form_values["messages_text"]:
                m.load_messages_from_text(form_values["messages_text"])
            elif form_values["messages_file"]:
                m.load_messages_from_fileobj(form_values["messages_file"])
            else:
                log_append("No messages provided.")
                m.quit()
                return

            m.target_uid = form_values["target_uid"]
            if not m.open_conversation(m.target_uid):
                log_append("Could not open conversation. Aborting.")
                m.quit()
                return

            # start sending (blocking inside thread)
            summary = m.start_sending(stop_event=stop_event)
            log_append(f"Finished sending: {summary}")
        except Exception as e:
            log_append(f"Fatal error: {e}")
        finally:
            try:
                if st.session_state.messenger:
                    st.session_state.messenger.quit()
            except Exception:
                pass

    t = threading.Thread(target=run_worker, daemon=True)
    st.session_state.thread = t
    t.start()
    log_append("Background worker started.")

st.title("Facebook Messenger Automation (Streamlit)")
st.write("Fill the form below and click Start. Use Stop to halt the process.")

with st.form("config_form"):
    cookie_str = st.text_area("Facebook cookies", height=120, help="Paste the cookie string (name=value; name2=value2; ...)")
    target_uid = st.text_input("Target UID (conversation ID)")
    st.write("Messages source:")
    uploaded_file = st.file_uploader("Upload .txt with messages (one per line)", type=["txt"])
    messages_text = st.text_area("Or paste messages (one per line)")
    haters_name = st.text_input("Haters name (optional, prefixed to each message)")
    speed_seconds = st.number_input("Speed between messages (seconds)", min_value=1, value=10)
    headless = st.checkbox("Run browser headless", value=True)
    firefox_binary = st.text_input("Optional: Firefox binary path (leave empty to auto-detect)")
    geckodriver_path = st.text_input("Optional: geckodriver path (leave empty to auto-detect)")

    submitted = st.form_submit_button("Start")
    if submitted:
        if not cookie_str:
            st.error("Cookies are required.")
        elif not target_uid:
            st.error("Target UID is required.")
        elif (not messages_text) and (not uploaded_file):
            st.error("Provide messages via file or paste them.")
        else:
            form_values = {
                "cookie_str": cookie_str.strip(),
                "target_uid": target_uid.strip(),
                "messages_file": uploaded_file,
                "messages_text": messages_text.strip(),
                "haters_name": haters_name.strip(),
                "speed_seconds": int(speed_seconds),
                "headless": headless,
                "firefox_binary": firefox_binary.strip(),
                "geckodriver_path": geckodriver_path.strip()
            }
            start_process(form_values)

col1, col2 = st.columns([3,1])
with col1:
    st.subheader("Logs")
    log_box = st.empty()
    # continuously refresh logs
    def render_logs():
        log_text = "\n".join(st.session_state.logs[-400:])  # keep last 400 lines
        log_box.code(log_text, language=None)
    render_logs()

with col2:
    st.subheader("Controls")
    if st.session_state.thread and st.session_state.thread.is_alive():
        if st.button("Stop"):
            if st.session_state.stop_event:
                st.session_state.stop_event.set()
                log_append("Stop requested. Waiting for worker to finish...")
    else:
        st.write("Worker not running.")

# small auto-refresh to update logs
st.experimental_rerun() if False else None
# Instead of forcing rerun, provide a small "Refresh logs" button
if st.button("Refresh logs"):
    pass
