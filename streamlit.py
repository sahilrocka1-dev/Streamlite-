# Developer: Darkstar Boii Sahiil (Modified by assistant)
# Updated Streamlit app:
# - Modern, icon-based UI & animations (CSS)
# - Multi-task per user support (unique task IDs)
# - Task persistence in DB; tasks resume after restart if running
# - Per-user task visibility (other users can't see tasks)
# - Admin mode (username: SAHIL123, password: SAHILKOOK) — can view/stop all tasks
# - Cookie mode: single (paste) or multiple (file upload). Multiple uses round-robin across messages.
# - Infinite loop sending until user stops the task; progress persisted
# - Uses database.py for persistence (make sure database.py from repository is present/updated)

import streamlit as st
import time
import threading
import uuid
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import database as db

# --- Page config & CSS (modern / icon-based / subtle animations) ---
st.set_page_config(page_title="Darkstar E2EE — MultiTask", page_icon="🚀", layout="wide")

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');

:root{
  --accent:#2563eb;
  --muted:#64748b;
  --glass: rgba(255,255,255,0.7);
  --card-shadow: 0 8px 30px rgba(7,89,133,0.08);
}

*{ font-family: 'Inter', sans-serif !important; }

/* App background */
.stApp {
  background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 40%, #eef9f8 100%);
  min-height:100vh;
  color: #0f172a;
}

/* Header */
.header {
  display:flex;
  gap:16px;
  align-items:center;
  background: linear-gradient(90deg, rgba(37,99,235,0.09), rgba(14,165,233,0.04));
  padding:28px;
  border-radius:18px;
  box-shadow: var(--card-shadow);
  margin-bottom:18px;
}
.logo {
  width:68px; height:68px; border-radius:14px;
  background:linear-gradient(135deg,#60a5fa,#06b6d4);
  display:flex; align-items:center; justify-content:center; font-size:28px; color:white; font-weight:800;
  box-shadow: 0 6px 18px rgba(6,78,159,0.12);
}
.header h1{ margin:0; font-size:1.6rem; color:var(--accent); }
.header p{ margin:0; color:var(--muted); font-size:0.95rem; }

/* Sidebar tweaks */
[data-testid="stSidebar"]{
  background: linear-gradient(180deg, rgba(255,255,255,0.8), rgba(255,255,255,0.6));
  border-radius:12px;
  padding:18px;
  box-shadow: var(--card-shadow);
}

/* Cards */
.card {
  background: white;
  border-radius:14px;
  padding:18px;
  box-shadow: var(--card-shadow);
  transition: transform .18s ease, box-shadow .18s ease;
}
.card:hover{ transform: translateY(-6px); box-shadow: 0 18px 60px rgba(6,78,159,0.08); }

/* Buttons - modern */
.stButton>button {
  background: linear-gradient(90deg,#2563eb,#06b6d4);
  color: white; font-weight:700; border-radius:10px; padding:10px 16px;
  box-shadow: 0 8px 18px rgba(37,99,235,0.16);
  border: none;
}
.stButton>button:disabled{ opacity:0.55; transform:none; box-shadow:none; }

/* Task list */
.task-row{ display:flex; gap:10px; align-items:center; padding:12px; border-radius:10px; margin-bottom:10px; }
.task-meta{ flex:1; }
.task-actions{ display:flex; gap:8px; }

/* Logs */
.console-output{ background:#0b1220; color:#d1e8ff; padding:14px; border-radius:10px; max-height:320px; overflow:auto; font-family: monospace; font-size:13px; }

/* subtle icon styles */
.icon {
  display:inline-flex; align-items:center; justify-content:center;
  width:40px; height:40px; border-radius:8px; margin-right:8px;
  background:linear-gradient(135deg,#eef2ff, #fff);
  box-shadow: 0 8px 20px rgba(15,23,42,0.04);
  font-weight:800;
}

/* admin badge */
.admin-badge { color:#071754; background: linear-gradient(90deg,#fde68a,#fca5a5); padding:6px 10px; border-radius:10px; font-weight:700; }

/* small helpers */
.small { font-size:0.9rem; color:var(--muted); }
.kv { font-weight:700; color:#0f172a; }

@keyframes pulse {
  0%{ box-shadow: 0 0 0 0 rgba(37,99,235,0.18) }
  70%{ box-shadow: 0 0 0 10px rgba(37,99,235,0) }
  100%{ box-shadow: 0 0 0 0 rgba(37,99,235,0) }
}

.running-dot { width:10px; height:10px; background:#10b981; border-radius:50%; display:inline-block; animation: pulse 2s infinite; box-shadow: 0 6px 20px rgba(16,185,129,0.12); }

</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- Session state defaults ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'username' not in st.session_state:
    st.session_state.username = None
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False

# --- Admin credentials (hardcoded as requested) ---
ADMIN_USERNAME = "SAHIL123"
ADMIN_PASSWORD = "SAHILKOOK"

# --- Task thread manager (in-memory) ---
TASK_THREADS = {}
TASK_THREADS_LOCK = threading.Lock()

def start_task_thread(task_id):
    """Start background thread for a task if not already running."""
    with TASK_THREADS_LOCK:
        if task_id in TASK_THREADS:
            return
        stop_event = threading.Event()
        thread = threading.Thread(target=task_runner_loop, args=(task_id, stop_event), daemon=True)
        TASK_THREADS[task_id] = {"thread": thread, "stop_event": stop_event}
        thread.start()

def stop_task_thread(task_id):
    with TASK_THREADS_LOCK:
        entry = TASK_THREADS.get(task_id)
        if entry:
            entry["stop_event"].set()
            del TASK_THREADS[task_id]

# --- Browser setup (reuse approach from original, headless) ---
def setup_browser_for_cookies(chrome_binary=None):
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    # try to set binary if present
    if chrome_binary:
        chrome_options.binary_location = chrome_binary
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_window_size(1920,1080)
        return driver
    except Exception as e:
        # return None to indicate browser not available
        return None

# --- Helper: find message input on the page (robust selectors) ---
def find_message_input(driver):
    selectors = [
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"][data-lexical-editor="true"]',
        'div[aria-label*="message" i][contenteditable="true"]',
        'div[aria-label*="Message" i][contenteditable="true"]',
        'div[contenteditable="true"][spellcheck="true"]',
        '[role="textbox"][contenteditable="true"]',
        'textarea[placeholder*="message" i]',
        'textarea',
        'input[type="text"]'
    ]
    for sel in selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                try:
                    # simple heuristics
                    if el.get_attribute('contenteditable') == 'true' or el.tag_name.lower() in ('textarea','input'):
                        return el
                except:
                    continue
        except:
            continue
    return None

# --- Core background runner per task ---
def task_runner_loop(task_id, stop_event):
    """
    Persistent loop that sends messages in round-robin using cookies.
    It reads & updates the DB so progress survives restarts.
    """
    # mark running in DB
    db.update_task_running(task_id, True)
    try:
        while not stop_event.is_set():
            task = db.get_task(task_id)
            if not task:
                break  # task deleted
            if not task['running']:
                break  # DB requested stop
            # load messages
            messages = [m for m in (task['messages'] or '').splitlines() if m.strip()]
            if not messages:
                messages = ["Hello!"]
            # load cookies depending on type
            cookies_list = []
            if task['cookies_type'] == 'single':
                if task['cookies']:
                    cookies_list = [task['cookies']]
            else:
                # read cookies file path
                if task['cookies_file']:
                    cookies_list = db.read_cookies_file_lines(task['cookies_file'])
            if not cookies_list:
                # cannot proceed without cookies — pause and retry later
                time.sleep(5)
                continue

            # indices persisted
            msg_idx = task.get('current_message_index', 0) or 0
            cookie_idx = task.get('current_cookie_index', 0) or 0
            delay = int(task.get('delay', 30) or 30)
            chat_id = task.get('chat_id','')
            name_prefix = task.get('name_prefix','').strip()

            # Setup browser once per task iteration (we'll open, send one message, quit — robust)
            try:
                driver = setup_browser_for_cookies()
                if driver is None:
                    # cannot start browser — wait and retry
                    db.append_task_log(task_id, "Browser not available; retrying in 10s")
                    time.sleep(10)
                    continue

                # go to facebook and set cookies for the selected cookie string
                cookie_str = cookies_list[cookie_idx].strip()
                # open base page
                driver.get('https://www.facebook.com/')
                time.sleep(3)

                # set cookies if possible
                try:
                    # cookies string format: name=value; name2=value2; ...
                    for cpart in [c.strip() for c in cookie_str.split(';') if c.strip()]:
                        if '=' in cpart:
                            name, value = cpart.split('=',1)
                            try:
                                driver.add_cookie({'name': name.strip(), 'value': value.strip(), 'domain': '.facebook.com', 'path': '/'})
                            except:
                                pass
                except Exception:
                    pass

                # open conversation (prefer e2ee then classic)
                if chat_id:
                    driver.get(f'https://www.facebook.com/messages/e2ee/t/{chat_id}')
                    time.sleep(3)
                    if '/messages/e2ee' not in driver.current_url:
                        driver.get(f'https://www.facebook.com/messages/t/{chat_id}')
                else:
                    driver.get('https://www.facebook.com/messages')
                time.sleep(6)

                # find input box
                el = find_message_input(driver)
                if not el:
                    db.append_task_log(task_id, f'Input box not found on page: {driver.current_url}')
                else:
                    message_body = messages[msg_idx]
                    if name_prefix:
                        message_body = f"{name_prefix} {message_body}"
                    # fill box and send
                    try:
                        driver.execute_script("""
                        const el = arguments[0];
                        const msg = arguments[1];
                        if (el.tagName === 'DIV') {
                            el.focus();
                            el.innerHTML = msg;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                        } else {
                            el.value = msg;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                        """, el, message_body)
                        time.sleep(0.6)
                        # try to click send buttons
                        sent = driver.execute_script("""
                        const sendButtons = document.querySelectorAll('[aria-label*="Send" i], [data-testid="send-button"]');
                        for (let b of sendButtons) {
                            if (b.offsetParent !== null) { b.click(); return true; }
                        }
                        return false;
                        """)
                        if not sent:
                            # fallback: Enter key events
                            driver.execute_script("""
                            const el = arguments[0];
                            ['keydown','keypress','keyup'].forEach(n=>{
                              el.dispatchEvent(new KeyboardEvent(n, {key:'Enter', code:'Enter', which:13, keyCode:13, bubbles:true}));
                            });
                            """, el)
                        db.append_task_log(task_id, f"Sent message #{msg_idx+1} via cookie #{cookie_idx+1}: {message_body[:60]}")
                    except Exception as e:
                        db.append_task_log(task_id, f"Send error: {str(e)[:200]}")
                # cleanup
                try:
                    driver.quit()
                except:
                    pass

                # update indices & persist
                msg_idx = (msg_idx + 1) % len(messages)
                cookie_idx = (cookie_idx + 1) % len(cookies_list)
                db.update_task_progress(task_id, msg_idx, cookie_idx)

                # loop sleep
                # If global task running turned off in DB, loop will break next iteration
                for _ in range(max(1, int(delay))):
                    if stop_event.is_set():
                        break
                    time.sleep(1)
            except Exception as e:
                db.append_task_log(task_id, f"Fatal loop error: {str(e)[:200]}")
                # short sleep before retry
                time.sleep(5)

    finally:
        # ensure DB reflects stopped
        db.update_task_running(task_id, False)
        # also stop local thread map entry if exists
        try:
            stop_task_thread(task_id)
        except:
            pass

# --- UI Pages: Login / Signup ---
def login_page():
    st.markdown("""
    <div class="header card">
      <div class="logo">DS</div>
      <div>
        <h1>Darkstar E2EE — Multitask</h1>
        <p>Multi-task Facebook E2EE automation • personal tasks & admin control</p>
      </div>
      <div style="margin-left:auto;">
        <div class="small">Server time: <span class="kv">{}</span></div>
      </div>
    </div>
    """.format(time.strftime("%Y-%m-%d %H:%M:%S")), unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Login", "Sign-up"])
    with tab1:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username", placeholder="Enter username")
        password = st.text_input("Password", key="login_password", type="password")
        if st.button("Login", key="login_btn", use_container_width=True):
            # Admin login override
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state.logged_in = True
                st.session_state.user_id = 0
                st.session_state.username = ADMIN_USERNAME
                st.session_state.is_admin = True
                st.success("✅ Admin logged in")
                st.experimental_rerun()
                return
            if username and password:
                user_id = db.verify_user(username, password)
                if user_id:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user_id
                    st.session_state.username = username
                    st.session_state.is_admin = False
                    st.success(f"✅ Welcome back, {username}!")
                    st.experimental_rerun()
                else:
                    st.error("❌ Invalid credentials")
            else:
                st.warning("Please fill both fields")

    with tab2:
        st.subheader("Create account")
        new_username = st.text_input("Choose username", key="signup_username")
        new_password = st.text_input("Choose password", key="signup_password", type="password")
        confirm_password = st.text_input("Confirm password", key="confirm_password", type="password")
        if st.button("Create account", key="signup_btn", use_container_width=True):
            if not (new_username and new_password and confirm_password):
                st.warning("Please fill all fields")
            elif new_password != confirm_password:
                st.error("Passwords do not match")
            else:
                ok, msg = db.create_user(new_username, new_password)
                if ok:
                    st.success("Account created. Please login.")
                else:
                    st.error(f"Error: {msg}")

# --- New Task Form ---
def new_task_form(user_id):
    st.markdown("<div class='card'><h3>➕ Create New Automation Task</h3></div>", unsafe_allow_html=True)
    with st.form("create_task_form", clear_on_submit=False):
        name = st.text_input("Task name / label", placeholder="Friendly name shown in your tasks", value=f"task-{str(uuid.uuid4())[:8]}")
        chat_id = st.text_input("Conversation Chat ID", placeholder="e.g., 10000634210631")
        name_prefix = st.text_input("Name prefix (optional)", placeholder="Prefix added before every message")
        delay = st.number_input("Delay between messages (seconds)", min_value=1, max_value=3600, value=30)
        cookies_type = st.radio("Cookies mode", options=["single", "multiple"], index=0, help="Single: paste one cookie string. Multiple: upload file with one cookie string per line.")
        cookies_text = ""
        cookies_file_path = ""
        if cookies_type == "single":
            cookies_text = st.text_area("Paste full cookie string", height=120, help="Format: name=value; name2=value2; ...")
        else:
            uploaded = st.file_uploader("Upload cookies file (plain text, 1 cookie per line)", type=["txt"], accept_multiple_files=False)
            if uploaded:
                # save to server cookies dir
                saved_path = db.save_uploaded_cookies_file(uploaded)
                cookies_file_path = saved_path

        messages = st.text_area("Messages (one per line)", height=220, placeholder="Type each message on a new line")
        start_immediately = st.checkbox("Start task immediately after creation", value=True)
        submitted = st.form_submit_button("Create Task")
        if submitted:
            # create DB entry
            if cookies_type == "single" and not cookies_text.strip():
                st.error("Please provide cookie string for single mode.")
            elif cookies_type == "multiple" and not cookies_file_path:
                st.error("Please upload cookie file for multiple mode.")
            else:
                task_id = db.create_task(user_id=user_id, name=name, chat_id=chat_id, name_prefix=name_prefix,
                                         delay=delay, cookies_type=cookies_type, cookies=cookies_text.strip(),
                                         cookies_file=cookies_file_path, messages=messages.strip())
                st.success(f"Task created: {task_id}")
                if start_immediately:
                    db.update_task_running(task_id, True)
                    start_task_thread(task_id)
                    st.info("Task started in background")
                st.experimental_rerun()

# --- User Dashboard (tasks list and control) ---
def user_dashboard():
    st.markdown("<div class='card'><h3>👤 Your Tasks</h3></div>", unsafe_allow_html=True)
    user_id = st.session_state.user_id
    col1, col2 = st.columns([3,1])
    with col1:
        new_task_form(user_id)
    with col2:
        st.markdown("<div class='card'><h4>Quick Actions</h4></div>", unsafe_allow_html=True)
        st.write("Create multi cookie files as plain text with one cookie (name=value;...) per line.")
        st.write("Tasks run on the server in background. You can start/stop any of your tasks below.")

    tasks = db.get_user_tasks(user_id)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    if not tasks:
        st.info("You have no tasks yet.")
        return

    st.markdown("<div class='card'><h4>Task List</h4></div>", unsafe_allow_html=True)
    for t in tasks:
        with st.container():
            st.markdown(f"""
            <div class="task-row card">
              <div class="icon">🧭</div>
              <div class="task-meta">
                <div style="display:flex;gap:12px;align-items:center;">
                  <div style="font-weight:800">{t['name']}</div>
                  <div class="small">ID: <span class="kv">{t['id']}</span></div>
                  <div class="small">Chat: <span class="kv">{(t['chat_id'][:12] + '...') if t['chat_id'] else 'NOT SET'}</span></div>
                  <div class="small">Delay: <span class="kv">{t['delay']}s</span></div>
                  <div class="small">Cookies: <span class="kv">{t['cookies_type']}</span></div>
                </div>
                <div class="small" style="margin-top:6px;">Messages: {len([m for m in (t['messages'] or '').splitlines() if m.strip()])} • Running: {"Yes" if t['running'] else "No"}</div>
              </div>
              <div class="task-actions">
                """, unsafe_allow_html=True)
            # Buttons for control
            col_a, col_b, col_c = st.columns([1,1,1])
            # Buttons need unique keys
            if t['running']:
                if st.button("⏹️ Stop", key=f"stop-{t['id']}", help="Stop this task"):
                    db.update_task_running(t['id'], False)
                    stop_task_thread(t['id'])
                    st.success("Stopped")
                    st.experimental_rerun()
            else:
                if st.button("▶️ Start", key=f"start-{t['id']}", help="Start this task"):
                    db.update_task_running(t['id'], True)
                    start_task_thread(t['id'])
                    st.success("Started")
                    st.experimental_rerun()
            if st.button("🗑️ Delete", key=f"delete-{t['id']}", help="Delete task"):
                db.delete_task(t['id'])
                stop_task_thread(t['id'])
                st.success("Deleted")
                st.experimental_rerun()
            # View logs
            if st.button("📜 Logs", key=f"logs-{t['id']}"):
                logs = db.get_task_logs(t['id'])
                if logs:
                    st.markdown("<div class='card'><div class='console-output'>%s</div></div>" % ("\n".join(logs)), unsafe_allow_html=True)
                else:
                    st.info("No logs for this task yet.")
            st.markdown("</div></div>", unsafe_allow_html=True)

# --- Admin Dashboard ---
def admin_dashboard():
    st.markdown("<div class='card'><h3 class='admin-badge'>ADMIN PANEL</h3></div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><h4>All Users & Tasks</h4></div>", unsafe_allow_html=True)
    all_users = db.list_users()
    st.write("Registered users:", len(all_users))
    for u in all_users:
        st.markdown(f" - {u['id']}: {u['username']}")

    st.markdown("---")
    st.markdown("<h4>All Tasks</h4>", unsafe_allow_html=True)
    all_tasks = db.get_all_tasks()
    if not all_tasks:
        st.info("No tasks.")
        return
    for t in all_tasks:
        st.markdown(f"""
        <div class="card" style="margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div><strong>{t['name']}</strong> <span class="small">({t['id']})</span><br><span class="small">Owner: {t['user_id']}</span></div>
            <div style="display:flex;gap:8px;">
        """, unsafe_allow_html=True)
        if t['running']:
            if st.button(f"Stop {t['id']}", key=f"admin-stop-{t['id']}"):
                db.update_task_running(t['id'], False)
                stop_task_thread(t['id'])
                st.success("Stopped")
                st.experimental_rerun()
        else:
            if st.button(f"Start {t['id']}", key=f"admin-start-{t['id']}"):
                db.update_task_running(t['id'], True)
                start_task_thread(t['id'])
                st.success("Started")
                st.experimental_rerun()

        if st.button(f"Logs {t['id']}", key=f"admin-logs-{t['id']}"):
            logs = db.get_task_logs(t['id'])
            st.markdown("<div class='card'><div class='console-output'>%s</div></div>" % ("\n".join(logs)), unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

# --- Main app routing ---
def main():
    if not st.session_state.logged_in:
        login_page()
        return

    # Top bar
    st.markdown(f"""
    <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;">
      <div class="logo">DS</div>
      <div>
        <div style="font-weight:800;font-size:18px">Darkstar E2EE</div>
        <div class="small">Logged in as <span class="kv">{st.session_state.username}</span> {('<span style=\"color:green\">(admin)</span>' if st.session_state.is_admin else '')}</div>
      </div>
      <div style="margin-left:auto;">
        <button id="logout_btn" style="background:#fff;border-radius:8px;padding:8px;border:1px solid #e6eefc;">Logout</button>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Logout handling (Streamlit cannot read the button above directly; provide sidebar logout)
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.is_admin = False
        st.experimental_rerun()

    if st.session_state.is_admin:
        admin_dashboard()
    else:
        user_dashboard()

# --- On app start: resume any running tasks recorded in DB ---
def resume_running_tasks_on_start():
    running_tasks = db.get_all_running_tasks()
    for t in running_tasks:
        # start thread for each running task (ownership doesn't matter)
        start_task_thread(t['id'])

# Start resume
resume_running_tasks_on_start()

# Run main
main()
