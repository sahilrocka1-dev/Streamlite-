# Developer: Darkstar Boii Sahiil (Modified DB)
# - SQLite storage for users, tasks, logs
# - Encryption via Fernet for cookies and auth tokens
# - Helpers to save uploaded cookie/message files

import sqlite3
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
import os
import time
import uuid
import json

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "users.db"
ENCRYPTION_KEY_FILE = BASE_DIR / ".encryption_key"
COOKIE_FILES_DIR = BASE_DIR / "cookies"
MESSAGES_FILES_DIR = BASE_DIR / "messages"
if not COOKIE_FILES_DIR.exists():
    COOKIE_FILES_DIR.mkdir(parents=True, exist_ok=True)
if not MESSAGES_FILES_DIR.exists():
    MESSAGES_FILES_DIR.mkdir(parents=True, exist_ok=True)

def get_encryption_key():
    if ENCRYPTION_KEY_FILE.exists():
        return open(ENCRYPTION_KEY_FILE, "rb").read()
    key = Fernet.generate_key()
    open(ENCRYPTION_KEY_FILE, "wb").write(key)
    return key

ENCRYPTION_KEY = get_encryption_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS user_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        chat_id TEXT,
        name_prefix TEXT,
        delay INTEGER DEFAULT 30,
        cookies_encrypted TEXT,
        messages TEXT,
        automation_running INTEGER DEFAULT 0,
        locked_group_name TEXT,
        locked_nicknames TEXT,
        lock_enabled INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        chat_id TEXT,
        name_prefix TEXT,
        delay INTEGER DEFAULT 30,
        cookies_type TEXT,
        cookies_encrypted TEXT,
        cookies_file TEXT,
        messages TEXT,
        messages_file TEXT,
        current_message_index INTEGER DEFAULT 0,
        current_cookie_index INTEGER DEFAULT 0,
        running INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS task_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def encrypt(s):
    if not s:
        return None
    return cipher_suite.encrypt(s.encode()).decode()

def decrypt(s):
    if not s:
        return ""
    try:
        return cipher_suite.decrypt(s.encode()).decode()
    except:
        return ""

# --- User functions ---
def create_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        ph = hash_password(password)
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, ph))
        user_id = c.lastrowid
        c.execute("INSERT INTO user_configs (user_id, chat_id, name_prefix, delay, messages) VALUES (?, ?, ?, ?, ?)",
                  (user_id, '', '', 30, ''))
        conn.commit()
        conn.close()
        return True, "Account created"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Username exists"
    except Exception as e:
        conn.close()
        return False, str(e)

def verify_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    r = c.fetchone()
    conn.close()
    if r and r[1] == hash_password(password):
        return r[0]
    return None

def get_username(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username FROM users")
    rows = [{"id": r[0], "username": r[1]} for r in c.fetchall()]
    conn.close()
    return rows

# --- user config compatibility ---
def get_user_config(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id, name_prefix, delay, cookies_encrypted, messages, automation_running FROM user_configs WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    if r:
        return {"chat_id": r[0] or '', "name_prefix": r[1] or '', "delay": r[2] or 30, "cookies": decrypt(r[3]) if r[3] else '', "messages": r[4] or '', "automation_running": bool(r[5])}
    return None

def update_user_config(user_id, chat_id, name_prefix, delay, cookies, messages):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    enc = encrypt(cookies)
    c.execute("UPDATE user_configs SET chat_id = ?, name_prefix = ?, delay = ?, cookies_encrypted = ?, messages = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
              (chat_id, name_prefix, delay, enc, messages, user_id))
    conn.commit()
    conn.close()

def set_automation_running(user_id, is_running):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE user_configs SET automation_running = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (1 if is_running else 0, user_id))
    conn.commit()
    conn.close()

def get_automation_running(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT automation_running FROM user_configs WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return bool(r[0]) if r else False

# --- Tasks ---
def create_task(user_id, name, chat_id, name_prefix, delay, cookies_type, cookies, cookies_file, messages, messages_file=None):
    task_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    enc = encrypt(cookies) if cookies else None
    c.execute("""INSERT INTO tasks (id, user_id, name, chat_id, name_prefix, delay, cookies_type, cookies_encrypted, cookies_file, messages, messages_file, running)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
              (task_id, user_id, name, chat_id, name_prefix, delay, cookies_type, enc, cookies_file, messages, messages_file))
    conn.commit()
    conn.close()
    return task_id

def get_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, user_id, name, chat_id, name_prefix, delay, cookies_type, cookies_encrypted, cookies_file, messages, messages_file, current_message_index, current_cookie_index, running
                 FROM tasks WHERE id = ?""", (task_id,))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {"id": r[0], "user_id": r[1], "name": r[2], "chat_id": r[3] or '', "name_prefix": r[4] or '', "delay": r[5] or 30, "cookies_type": r[6] or 'single', "cookies": decrypt(r[7]) if r[7] else '', "cookies_file": r[8] or '', "messages": r[9] or '', "messages_file": r[10] or '', "current_message_index": r[11] or 0, "current_cookie_index": r[12] or 0, "running": bool(r[13])}

def get_user_tasks(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, name, chat_id, name_prefix, delay, cookies_type, cookies_encrypted, cookies_file, messages, messages_file, current_message_index, current_cookie_index, running
                 FROM tasks WHERE user_id = ? ORDER BY created_at DESC""", (user_id,))
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({"id": r[0], "name": r[1], "chat_id": r[2] or '', "name_prefix": r[3] or '', "delay": r[4] or 30, "cookies_type": r[5] or 'single', "cookies": decrypt(r[6]) if r[6] else '', "cookies_file": r[7] or '', "messages": r[8] or '', "messages_file": r[9] or '', "current_message_index": r[10] or 0, "current_cookie_index": r[11] or 0, "running": bool(r[12])})
    return out

def get_all_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, name, chat_id, delay, running FROM tasks ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "user_id": r[1], "name": r[2], "chat_id": r[3], "delay": r[4], "running": bool(r[5])} for r in rows]

def delete_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    c.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
    conn.commit()
    conn.close()

def update_task_running(task_id, running):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET running = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (1 if running else 0, task_id))
    conn.commit()
    conn.close()

def update_task_progress(task_id, message_index, cookie_index):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET current_message_index = ?, current_cookie_index = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (message_index, cookie_index, task_id))
    conn.commit()
    conn.close()

def get_all_running_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM tasks WHERE running = 1")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return [{"id": tid} for tid in rows]

# --- Logs ---
def append_task_log(task_id, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO task_logs (task_id, message) VALUES (?, ?)", (task_id, message))
    conn.commit()
    conn.close()

def get_task_logs(task_id, limit=200):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT ts, message FROM task_logs WHERE task_id = ? ORDER BY id DESC LIMIT ?", (task_id, limit))
    rows = c.fetchall()
    conn.close()
    return [f"[{r[0]}] {r[1]}" for r in reversed(rows)]

# --- File helpers ---
def save_uploaded_cookies_file(uploaded_file):
    name = f"cookies_{int(time.time())}_{uploaded_file.name}"
    dest = COOKIE_FILES_DIR / name
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(dest)

def read_cookies_file_lines(path):
    try:
        p = Path(path)
        if not p.exists():
            return []
        lines = [ln.strip() for ln in p.read_text(encoding='utf-8', errors='ignore').splitlines() if ln.strip()]
        return lines
    except:
        return []

def save_uploaded_messages_file(uploaded_file):
    name = f"messages_{int(time.time())}_{uploaded_file.name}"
    dest = MESSAGES_FILES_DIR / name
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(dest)

def read_messages_file_lines(path):
    try:
        p = Path(path)
        if not p.exists():
            return []
        lines = [ln.strip() for ln in p.read_text(encoding='utf-8', errors='ignore').splitlines() if ln.strip()]
        return lines
    except:
        return []

# --- Auth token helpers (Fernet) ---
def generate_auth_token(user_id):
    # token contains: json with user_id and timestamp
    payload = json.dumps({"user_id": user_id, "ts": int(time.time())})
    return cipher_suite.encrypt(payload.encode()).decode()

def validate_auth_token(token):
    try:
        raw = cipher_suite.decrypt(urllib_unquote(token).encode()).decode()
        data = json.loads(raw)
        user_id = data.get("user_id")
        # optional: check timestamp expiry here
        return user_id
    except Exception:
        # try direct decrypt (if not url-quoted)
        try:
            raw = cipher_suite.decrypt(token.encode()).decode()
            data = json.loads(raw)
            return data.get("user_id")
        except:
            return None

def urllib_unquote(s):
    try:
        from urllib.parse import unquote
        return unquote(s)
    except:
        return s

# End of database.py
