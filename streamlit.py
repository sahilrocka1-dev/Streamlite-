# Developer: Darkstar Boii Sahiil (Modified)
# Features:
# - Multi-task per user with unique task IDs
# - Persistent login via encrypted cookie token (survives refresh)
# - Message file upload support + cookie file upload
# - No use of st.experimental_rerun (fixes AttributeError)
# - Stylish UI with 1.7px border on cards

import streamlit as st
import streamlit.components.v1 as components
import time
import threading
import uuid
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import database as db
import urllib.parse
import json

st.set_page_config(page_title="Darkstar E2EE — MultiTask", page_icon="🚀", layout="wide")

# --- CSS: modern, icon-based, 1.7px border on cards ---
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');

:root{
  --accent:#2563eb;
  --muted:#64748b;
  --glass: rgba(255,255,255,0.78);
  --card-shadow: 0 10px 30px rgba(0,0,0,0.06);
  --card-border: 1.7px;
}

*{ font-family: 'Inter', sans-serif !important; }
.stApp{ background: linear-gradient(135deg,#f8fafc 0%, #eef2ff 50%); min-height:100vh; padding:20px; }

/* Header */
.header { display:flex; gap:16px; align-items:center; background:linear-gradient(90deg, rgba(37,99,235,0.06), rgba(6,182,212,0.03)); padding:20px; border-radius:14px; box-shadow: var(--card-shadow); border: var(--card-border) solid rgba(37,99,235,0.06); margin-bottom:18px; }
.logo { width:64px; height:64px; border-radius:12px; background:linear-gradient(135deg,#60a5fa,#06b6d4); display:flex; align-items:center; justify-content:center; color:white; font-weight:800; font-size:22px; }

/* Card look */
.card { background: white; border-radius:12px; padding:16px; box-shadow: var(--card-shadow); border: var(--card-border) solid rgba(15,23,42,0.05); transition: transform .16s ease; }
.card:hover { transform: translateY(-6px); box-shadow: 0 30px 80px rgba(2,6,23,0.06); }

/* Buttons */
.stButton>button { background: linear-gradient(90deg,#2563eb,#06b6d4); color: white; font-weight:700; border-radius:10px; padding:10px 14px; box-shadow: 0 8px 18px rgba(37,99,235,0.12); border:none; }
.stButton>button:disabled { opacity:0.6; }

/* Task row */
.task-row { display:flex; gap:12px; align-items:center; padding:12px; border-radius:10px; margin-bottom:12px; border: 1.7px solid rgba(14,165,233,0.06); }
.icon { width:44px; height:44px; border-radius:10px; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#eef2ff,#fff); font-size:20px; }

/* Console */
.console-output { background:#0b1220; color:#d1e8ff; padding:12px; border-radius:10px; max-height:320px; overflow:auto; font-family: monospace; font-size:13px; }

/* small */
.small { font-size:0.9rem; color:var(--muted); }
.kv { font-weight:700; color:#0f172a; }

/* Admin badge */
.admin-badge { color:#071754; background: linear-gradient(90deg,#fde68a,#fca5a5); padding:8px 12px; border-radius:12px; font-weight:800; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- Session defaults ---
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

# --- Task threads manager ---
TASK_THREADS = {}
TASK_THREADS_LOCK = threading.Lock()

def start_task_thread(task_id):
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

# --- Browser setup (headless) ---
def setup_browser():
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_window_size(1920,1080)
        return driver
    except Exception:
        return None

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
                    if el.get_attribute('contenteditable') == 'true' or el.tag_name.lower() in ('textarea','input'):
                        return el
                except:
                    continue
        except:
            continue
    return None

# --- Task runner (background) ---
def task_runner_loop(task_id, stop_event):
    db.update_task_running(task_id, True)
    try:
        while not stop_event.is_set():
            task = db.get_task(task_id)
            if not task:
                break
            if not task['running']:
                break

            # load messages (from file if present, else from text)
            messages = []
            if task.get('messages_file'):
                messages = db.read_messages_file_lines(task['messages_file'])
            if not messages:
                messages = [m for m in (task.get('messages') or '').splitlines() if m.strip()]
            if not messages:
                messages = ["Hello!"]

            # cookies list
            if task['cookies_type'] == 'single':
                cookies_list = [task['cookies']] if task['cookies'] else []
            else:
                cookies_list = db.read_cookies_file_lines(task.get('cookies_file') or '')

            if not cookies_list:
                db.append_task_log(task_id, "No cookies available; retrying in 10s")
                time.sleep(10)
                continue

            msg_idx = int(task.get('current_message_index', 0) or 0)
            cookie_idx = int(task.get('current_cookie_index', 0) or 0)
            delay = int(task.get('delay', 30) or 30)
            chat_id = task.get('chat_id','')
            name_prefix = (task.get('name_prefix') or '').strip()

            try:
                driver = setup_browser()
                if driver is None:
                    db.append_task_log(task_id, "Browser not available; retrying in 10s")
                    time.sleep(10)
                    continue

                # pick cookie string
                cookie_str = cookies_list[cookie_idx].strip()
                driver.get('https://www.facebook.com/')
                time.sleep(2)

                # add cookies
                try:
                    for cpart in [c.strip() for c in cookie_str.split(';') if c.strip()]:
                        if '=' in cpart:
                            name, value = cpart.split('=',1)
                            try:
                                driver.add_cookie({'name': name.strip(), 'value': value.strip(), 'domain': '.facebook.com', 'path': '/'})
                            except:
                                pass
                except:
                    pass

                # open conversation
                if chat_id:
                    driver.get(f'https://www.facebook.com/messages/e2ee/t/{chat_id}')
                    time.sleep(3)
                    if '/messages/e2ee' not in driver.current_url:
                        driver.get(f'https://www.facebook.com/messages/t/{chat_id}')
                else:
                    driver.get('https://www.facebook.com/messages')
                time.sleep(4)

                el = find_message_input(driver)
                if not el:
                    db.append_task_log(task_id, f"Message input not found; url: {driver.current_url}")
                else:
                    message_body = messages[msg_idx]
                    if name_prefix:
                        message_body = f"{name_prefix} {message_body}"
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
                        sent = driver.execute_script("""
                        const sendButtons = document.querySelectorAll('[aria-label*="Send" i], [data-testid="send-button"]');
                        for (let b of sendButtons) { if (b.offsetParent !== null) { b.click(); return true; } }
                        return false;
                        """)
                        if not sent:
                            driver.execute_script("""
                            const el = arguments[0];
                            ['keydown','keypress','keyup'].forEach(n=>{
                              el.dispatchEvent(new KeyboardEvent(n, {key:'Enter', code:'Enter', which:13, keyCode:13, bubbles:true}));
                            });
                            """, el)
                        db.append_task_log(task_id, f"Sent #{msg_idx+1} via cookie #{cookie_idx+1}: {message_body[:80]}")
                    except Exception as e:
                        db.append_task_log(task_id, f"Send error: {str(e)[:200]}")

                try:
                    driver.quit()
                except:
                    pass

                # update indices persist
                msg_idx = (msg_idx + 1) % len(messages)
                cookie_idx = (cookie_idx + 1) % len(cookies_list)
                db.update_task_progress(task_id, msg_idx, cookie_idx)

                # delay loop (check stop_event)
                for _ in range(max(1, delay)):
                    if stop_event.is_set():
                        break
                    time.sleep(1)

            except Exception as e:
                db.append_task_log(task_id, f"Loop error: {str(e)[:200]}")
                time.sleep(5)

    finally:
        db.update_task_running(task_id, False)
        try:
            stop_task_thread(task_id)
        except:
            pass

# --- Auth token / cookie helpers (client-side) ---
def set_auth_cookie_and_redirect(token):
    # Use an HTML component to set a cookie in the browser then redirect to URL with token param
    safe_token = urllib.parse.quote(token)
    js = f"""
    <script>
      document.cookie = "ds_auth={safe_token}; path=/; max-age=31536000";
      // redirect to include token param so python side reads it immediately
      const url = new URL(window.location.href);
      url.searchParams.set('token', "{safe_token}");
      window.location.replace(url.toString());
    </script>
    """
    components.html(js, height=10)

def inject_cookie_reader_js():
    # On every load, a tiny script reads ds_auth cookie and, if present & no token query param, redirects to add token.
    js = """
    <script>
      const params = new URLSearchParams(window.location.search);
      if (!params.get('token')) {
        const cookies = document.cookie.split(';').map(c=>c.trim());
        const c = cookies.find(x=>x.startsWith('ds_auth='));
        if (c) {
          const token = c.split('=')[1];
          const url = new URL(window.location.href);
          url.searchParams.set('token', token);
          // replace without adding history entry
          window.location.replace(url.toString());
        }
      }
    </script>
    """
    components.html(js, height=10)

# --- UI Pages ---
def login_page():
    st.markdown("""
    <div class="header card">
      <div class="logo">DS</div>
      <div>
        <h2 style="margin:0;color:var(--accent)">Darkstar E2EE — Multitask</h2>
        <div class="small">Multiple background automations • personal tasks • admin control</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Login", "Sign-up"])
    with tab1:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", key="login_password", type="password")
        if st.button("Login", key="login_btn", use_container_width=True):
            # Admin override
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state.logged_in = True
                st.session_state.user_id = 0
                st.session_state.username = ADMIN_USERNAME
                st.session_state.is_admin = True
                # create token so admin stays logged in on refresh
                token = db.generate_auth_token(0)
                set_auth_cookie_and_redirect(token)
                return

            if username and password:
                user_id = db.verify_user(username, password)
                if user_id:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user_id
                    st.session_state.username = username
                    st.session_state.is_admin = False
                    # generate token and set cookie via JS + redirect
                    token = db.generate_auth_token(user_id)
                    set_auth_cookie_and_redirect(token)
                    return
                else:
                    st.error("Invalid credentials")
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

def new_task_form(user_id):
    st.markdown("<div class='card'><h3>➕ Create New Task</h3></div>", unsafe_allow_html=True)
    with st.form("create_task_form"):
        name = st.text_input("Task name", value=f"task-{str(uuid.uuid4())[:8]}")
        chat_id = st.text_input("Conversation Chat ID", placeholder="e.g., 10000634210631")
        name_prefix = st.text_input("Name prefix (optional)")
        delay = st.number_input("Delay (seconds)", min_value=1, max_value=3600, value=30)
        cookies_type = st.radio("Cookies mode", options=["single", "multiple"], index=0)
        cookies_text = ""
        cookies_file_path = ""
        if cookies_type == "single":
            cookies_text = st.text_area("Paste cookie string (name=value;...)", height=120)
        else:
            uploaded = st.file_uploader("Upload cookies file (one cookie per line)", type=["txt"])
            if uploaded:
                cookies_file_path = db.save_uploaded_cookies_file(uploaded)

        # messages: textarea OR file upload
        messages_text = st.text_area("Messages (one per line)", height=200)
        messages_file_path = None
        uploaded_msgs = st.file_uploader("Or upload messages file (txt, one line = one message)", type=["txt"])
        if uploaded_msgs:
            messages_file_path = db.save_uploaded_messages_file(uploaded_msgs)

        start_immediately = st.checkbox("Start immediately", value=True)
        submitted = st.form_submit_button("Create Task")
        if submitted:
            if cookies_type == "single" and not cookies_text.strip():
                st.error("Provide cookie string for single mode.")
            elif cookies_type == "multiple" and not cookies_file_path:
                st.error("Upload cookie file for multiple mode.")
            else:
                task_id = db.create_task(
                    user_id=user_id,
                    name=name,
                    chat_id=chat_id,
                    name_prefix=name_prefix,
                    delay=delay,
                    cookies_type=cookies_type,
                    cookies=cookies_text.strip(),
                    cookies_file=cookies_file_path,
                    messages=messages_text.strip(),
                    messages_file=messages_file_path
                )
                st.success(f"Task created: {task_id}")
                if start_immediately:
                    db.update_task_running(task_id, True)
                    start_task_thread(task_id)
                st.experimental_rerun() if hasattr(st, "experimental_rerun") else None

def user_dashboard():
    st.markdown("<div class='card'><h3>👤 Your Tasks</h3></div>", unsafe_allow_html=True)
    user_id = st.session_state.user_id
    col1, col2 = st.columns([3,1])
    with col1:
        new_task_form(user_id)
    with col2:
        st.markdown("<div class='card'><h4>Helper</h4><div class='small'>Upload cookie files and message files as plain text. Tasks run in background on the server.</div></div>", unsafe_allow_html=True)

    tasks = db.get_user_tasks(user_id)
    if not tasks:
        st.info("No tasks yet.")
        return

    for t in tasks:
        st.markdown(f"""
        <div class="task-row card">
          <div class="icon">📨</div>
          <div style="flex:1">
            <div style="font-weight:800">{t['name']}</div>
            <div class="small">ID: <span class="kv">{t['id']}</span> • Chat: <span class="kv">{t['chat_id'] or 'NOT SET'}</span></div>
            <div class="small">Messages: {len([m for m in (t.get('messages') or '').splitlines() if m.strip()])} • Running: {"Yes" if t.get('running') else "No"}</div>
          </div>
          <div style="display:flex;gap:8px;">
        """, unsafe_allow_html=True)

        if t['running']:
            if st.button("⏹️ Stop", key=f"stop-{t['id']}"):
                db.update_task_running(t['id'], False)
                stop_task_thread(t['id'])
                st.experimental_rerun() if hasattr(st, "experimental_rerun") else None
        else:
            if st.button("▶️ Start", key=f"start-{t['id']}"):
                db.update_task_running(t['id'], True)
                start_task_thread(t['id'])
                st.experimental_rerun() if hasattr(st, "experimental_rerun") else None

        if st.button("📜 Logs", key=f"logs-{t['id']}"):
            logs = db.get_task_logs(t['id'])
            if logs:
                st.markdown("<div class='card'><div class='console-output'>%s</div></div>" % ("\n".join(logs)), unsafe_allow_html=True)
            else:
                st.info("No logs yet.")

        if st.button("🗑️ Delete", key=f"delete-{t['id']}"):
            db.delete_task(t['id'])
            stop_task_thread(t['id'])
            st.experimental_rerun() if hasattr(st, "experimental_rerun") else None

        st.markdown("</div></div>", unsafe_allow_html=True)

def admin_dashboard():
    st.markdown("<div class='card'><h3 class='admin-badge'>ADMIN PANEL</h3></div>", unsafe_allow_html=True)
    users = db.list_users()
    st.markdown("<div class='card'><h4>Users</h4></div>", unsafe_allow_html=True)
    for u in users:
        st.write(f"{u['id']}: {u['username']}")
    st.markdown("---")
    st.markdown("<div class='card'><h4>All Tasks</h4></div>", unsafe_allow_html=True)
    tasks = db.get_all_tasks()
    if not tasks:
        st.info("No tasks.")
        return
    for t in tasks:
        st.markdown(f"<div class='card'><strong>{t['name']}</strong> (ID: {t['id']}) • Owner: {t['user_id']} • Running: {'Yes' if t['running'] else 'No'}</div>", unsafe_allow_html=True)
        if t['running']:
            if st.button(f"Stop {t['id']}", key=f"admin-stop-{t['id']}"):
                db.update_task_running(t['id'], False)
                stop_task_thread(t['id'])
                st.experimental_rerun() if hasattr(st, "experimental_rerun") else None
        else:
            if st.button(f"Start {t['id']}", key=f"admin-start-{t['id']}"):
                db.update_task_running(t['id'], True)
                start_task_thread(t['id'])
                st.experimental_rerun() if hasattr(st, "experimental_rerun") else None
        if st.button(f"Logs {t['id']}", key=f"admin-logs-{t['id']}"):
            logs = db.get_task_logs(t['id'])
            st.markdown("<div class='card'><div class='console-output'>%s</div></div>" % ("\n".join(logs)), unsafe_allow_html=True)

# --- Resume running tasks on app start ---
def resume_running_tasks_on_start():
    running = db.get_all_running_tasks()
    for t in running:
        start_task_thread(t['id'])

# --- App bootstrap: check cookie token via URL param or cookie ---
def try_restore_session_from_token():
    # If ?token= present in URL, validate and set session state
    params = st.experimental_get_query_params()
    token = None
    if 'token' in params and params['token']:
        token = params['token'][0]
    # else leave and let JS cookie reader handle adding token param
    if token:
        user_id = db.validate_auth_token(token)
        if user_id is not None:
            if user_id == 0:
                # admin
                st.session_state.logged_in = True
                st.session_state.user_id = 0
                st.session_state.username = ADMIN_USERNAME
                st.session_state.is_admin = True
            else:
                st.session_state.logged_in = True
                st.session_state.user_id = user_id
                st.session_state.username = db.get_username(user_id)
                st.session_state.is_admin = False

# inject cookie reader JS (runs on every load)
inject_cookie_reader_js()
# attempt restore from token param if present
try_restore_session_from_token()
# resume tasks
resume_running_tasks_on_start()

# --- Main ---
def main():
    if not st.session_state.logged_in:
        login_page()
        return

    st.markdown(f"""
    <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;">
      <div class="logo">DS</div>
      <div>
        <div style="font-weight:800;font-size:18px">Darkstar E2EE</div>
        <div class="small">Logged in as <span class="kv">{st.session_state.username}</span> {('<span style="color:green'"> (admin)</span>' if st.session_state.is_admin else '')}</div>
      </div>
      <div style="margin-left:auto;">
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("🚪 Logout", use_container_width=True):
        # clear cookie via JS then reload
        js = """
        <script>
          document.cookie = "ds_auth=; path=/; max-age=0";
          window.location.reload();
        </script>
        """
        components.html(js, height=10)
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.is_admin = False
        return

    if st.session_state.is_admin:
        admin_dashboard()
    else:
        user_dashboard()

main()
