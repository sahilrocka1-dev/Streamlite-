# Developer: Darkstar Boii Sahiil (extended)
# Database layer for multitask Streamlit app.
# - SQLite persistence for users, user_configs, tasks and logs
# - Encryption for cookie strings using Fernet
# - Utilities for saving uploaded cookie files (plain text)
# Make sure cryptography is installed.

import sqlite3
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
import os
import time
import json

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "users.db"
ENCRYPTION_KEY_FILE = BASE_DIR / ".encryption_key"
COOKIE_FILES_DIR = BASE_DIR / "cookies"
if not COOKIE_FILES_DIR.exists():
    COOKIE_FILES_DIR.mkdir(parents=True, exist_ok=True)

# --- encryption setup ---
def get_encryption_key():
    if ENCRYPTION_KEY_FILE.exists():
        return open(ENCRYPTION_KEY_FILE, "rb").read()
    key = Fernet.generate_key()
    with open(ENCRYPTION_KEY_FILE, "wb") as f:
        f.write(key)
    return key

ENCRYPTION_KEY = get_encryption_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

# --- DB initialization ---
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
        cookies_type TEXT, -- 'single' or 'multiple'
        cookies_encrypted TEXT,
        cookies_file TEXT, -- path to uploaded cookies file
        messages TEXT,
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

# --- utilities ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def encrypt_cookies(cookies):
    if not cookies:
        return None
    return cipher_suite.encrypt(cookies.encode()).decode()

def decrypt_cookies(enc):
    if not enc:
        return ""
    try:
        return cipher_suite.decrypt(enc.encode()).decode()
    except:
        return ""

# --- user functions ---
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
    row = c.fetchone()
    conn.close()
    if row and row[1] == hash_password(password):
        return row[0]
    return None

def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username FROM users")
    rows = [{"id": r[0], "username": r[1]} for r in c.fetchall()]
    conn.close()
    return rows

# --- user config helpers (compat with original) ---
def get_user_config(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id, name_prefix, delay, cookies_encrypted, messages, automation_running FROM user_configs WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    if r:
        return {
            "chat_id": r[0] or '',
            "name_prefix": r[1] or '',
            "delay": r[2] or 30,
            "cookies": decrypt_cookies(r[3]),
            "messages": r[4] or '',
            "automation_running": bool(r[5])
        }
    return None

def update_user_config(user_id, chat_id, name_prefix, delay, cookies, messages):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    enc = encrypt_cookies(cookies)
    c.execute("""
      UPDATE user_configs SET chat_id = ?, name_prefix = ?, delay = ?, cookies_encrypted = ?, messages = ?, updated_at = CURRENT_TIMESTAMP
      WHERE user_id = ?
    """, (chat_id, name_prefix, delay, enc, messages, user_id))
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

# --- Task functions (new) ---
def create_task(user_id, name, chat_id, name_prefix, delay, cookies_type, cookies, cookies_file, messages):
    task_id = str(uuid4()) if False else str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    enc = encrypt_cookies(cookies) if cookies else None
    c.execute("""
      INSERT INTO tasks (id, user_id, name, chat_id, name_prefix, delay, cookies_type, cookies_encrypted, cookies_file, messages, running)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (task_id, user_id, name, chat_id, name_prefix, delay, cookies_type, enc, cookies_file, messages))
    conn.commit()
    conn.close()
    return task_id

def get_task(task_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
      SELECT id, user_id, name, chat_id, name_prefix, delay, cookies_type, cookies_encrypted, cookies_file, messages, current_message_index, current_cookie_index, running
      FROM tasks WHERE id = ?
    """, (task_id,))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r[0],
        "user_id": r[1],
        "name": r[2],
        "chat_id": r[3] or '',
        "name_prefix": r[4] or '',
        "delay": r[5] or 30,
        "cookies_type": r[6] or 'single',
        "cookies": decrypt_cookies(r[7]) if r[7] else '',
        "cookies_file": r[8] or '',
        "messages": r[9] or '',
        "current_message_index": r[10] or 0,
        "current_cookie_index": r[11] or 0,
        "running": bool(r[12])
    }

def get_user_tasks(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
      SELECT id, name, chat_id, name_prefix, delay, cookies_type, cookies_encrypted, cookies_file, messages, current_message_index, current_cookie_index, running
      FROM tasks WHERE user_id = ?
      ORDER BY created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "name": r[1],
            "chat_id": r[2] or '',
            "name_prefix": r[3] or '',
            "delay": r[4] or 30,
            "cookies_type": r[5] or 'single',
            "cookies": decrypt_cookies(r[6]) if r[6] else '',
            "cookies_file": r[7] or '',
            "messages": r[8] or '',
            "current_message_index": r[9] or 0,
            "current_cookie_index": r[10] or 0,
            "running": bool(r[11])
        })
    return out

def get_all_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, name, chat_id, delay, running FROM tasks ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    tasks = []
    for r in rows:
        tasks.append({"id": r[0], "user_id": r[1], "name": r[2], "chat_id": r[3], "delay": r[4], "running": bool(r[5])})
    return tasks

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
    c.execute("""
      UPDATE tasks SET current_message_index = ?, current_cookie_index = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
    """, (message_index, cookie_index, task_id))
    conn.commit()
    conn.close()

def get_all_running_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM tasks WHERE running = 1")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return [{"id": tid} for tid in rows]

# --- logging ---
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

# --- cookie file helpers ---
def save_uploaded_cookies_file(uploaded_file):
    # uploaded_file is a streamlike object from Streamlit; we save its bytes and return path
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
    except Exception:
        return []

# --- helper for backwards compatibility with original functions ---
def get_username(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def update_lock_config(user_id, chat_id, locked_group_name, locked_nicknames, cookies=None):
    # keep interface; store in user_configs
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    nick_json = json.dumps(locked_nicknames)
    if cookies is not None:
        enc = encrypt_cookies(cookies)
        c.execute("UPDATE user_configs SET chat_id = ?, locked_group_name = ?, locked_nicknames = ?, cookies_encrypted = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                  (chat_id, locked_group_name, nick_json, enc, user_id))
    else:
        c.execute("UPDATE user_configs SET chat_id = ?, locked_group_name = ?, locked_nicknames = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                  (chat_id, locked_group_name, nick_json, user_id))
    conn.commit()
    conn.close()

def set_lock_enabled(user_id, enabled):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE user_configs SET lock_enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (1 if enabled else 0, user_id))
    conn.commit()
    conn.close()

def get_lock_enabled(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT lock_enabled FROM user_configs WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return bool(r[0]) if r else False

# --- small imports used by main app ---
import uuid as _uuid
def uuid4():
    return _uuid.uuid4()

# End of database.py
