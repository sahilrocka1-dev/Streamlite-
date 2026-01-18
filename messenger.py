#!/usr/bin/env python3
"""
Adapted FacebookMessenger for programmatic use (importable by Streamlit).
Minimal changes from original script: no interactive prompts, logging callback support,
and a stop_event to gracefully stop the sending loop from the UI.
"""
import os
import time
import sys
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime

class FacebookMessenger:
    def __init__(self,
                 firefox_binary=None,
                 geckodriver_path=None,
                 headless=True,
                 speed_seconds=10,
                 log_callback=None):
        """
        log_callback: function(str) -> None. Called for logging messages to UI.
        """
        self.driver = None
        self.wait = None
        self.firefox_binary = firefox_binary
        self.geckodriver_path = geckodriver_path
        self.haters_name = ""
        self.messages = []
        self.speed_seconds = speed_seconds
        self.target_uid = ""
        self.headless = headless
        self.log = log_callback if log_callback else lambda s: None

    def find_firefox_binary(self):
        possible_paths = [
            '/usr/bin/firefox',
            '/usr/local/bin/firefox',
            '/data/data/com.termux/files/usr/bin/firefox',
            '/data/data/com.termux/files/usr/lib/firefox/firefox',
            os.path.expanduser('~/firefox/firefox'),
            'firefox'
        ]
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return None

    def find_geckodriver(self):
        possible_paths = [
            '/usr/bin/geckodriver',
            '/usr/local/bin/geckodriver',
            '/data/data/com.termux/files/usr/bin/geckodriver',
            os.path.expanduser('~/geckodriver'),
            'geckodriver'
        ]
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return None

    def load_messages_from_text(self, text):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        self.messages = lines
        return len(self.messages) > 0

    def load_messages_from_fileobj(self, fileobj):
        try:
            content = fileobj.read().decode('utf-8')
        except Exception:
            fileobj.seek(0)
            content = fileobj.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
        return self.load_messages_from_text(content)

    def setup_driver(self):
        try:
            self.log("Initializing browser setup ...")
            if not self.firefox_binary:
                self.firefox_binary = self.find_firefox_binary()
            if not self.geckodriver_path:
                self.geckodriver_path = self.find_geckodriver()

            if not self.firefox_binary:
                self.log("Firefox binary not found.")
                return False, "Firefox binary not found"
            if not self.geckodriver_path:
                self.log("geckodriver not found.")
                return False, "geckodriver not found"

            options = Options()
            if self.headless:
                options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')

            # small perf prefs (optional)
            options.set_preference('browser.cache.disk.enable', False)
            options.set_preference('browser.cache.memory.enable', True)
            options.binary_location = self.firefox_binary

            service = Service(executable_path=self.geckodriver_path)
            self.driver = webdriver.Firefox(service=service, options=options)
            self.driver.set_page_load_timeout(120)
            self.driver.set_script_timeout(60)
            self.wait = WebDriverWait(self.driver, 30)
            self.log("Browser setup completed.")
            return True, ""
        except Exception as e:
            self.log(f"Setup failed: {e}")
            return False, str(e)

    def parse_cookies(self, cookie_string):
        cookies = []
        for pair in cookie_string.split(';'):
            pair = pair.strip()
            if '=' in pair:
                name, value = pair.split('=', 1)
                cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': '.facebook.com',
                    'path': '/',
                    'secure': True
                })
        return cookies

    def login_with_cookies(self, cookie_string, max_retries=3):
        retry_count = 0
        cookies = self.parse_cookies(cookie_string)
        while retry_count < max_retries:
            try:
                self.log(f"Authenticating with Facebook (Attempt {retry_count+1}/{max_retries})...")
                try:
                    self.driver.get("https://www.facebook.com")
                    time.sleep(3)
                except Exception as e:
                    self.log(f"Network issue while loading facebook.com: {e}")
                    retry_count += 1
                    time.sleep(5)
                    continue

                for cookie in cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception:
                        pass

                self.driver.refresh()
                time.sleep(4)

                # quick indicators
                indicators = [
                    "//a[@aria-label='Messenger']",
                    "//div[@role='navigation']",
                    "//a[contains(@href, '/messages')]"
                ]
                for indicator in indicators:
                    try:
                        elements = self.driver.find_elements(By.XPATH, indicator)
                        if elements:
                            self.log("Login seems successful (indicator found).")
                            return True
                    except Exception:
                        continue

                retry_count += 1
                self.log("Login verification failed, retrying...")
                time.sleep(5)
            except Exception as e:
                self.log(f"Login attempt failed: {e}")
                retry_count += 1
                time.sleep(5)
        return False

    def open_conversation(self, target_uid, max_retries=3):
        for attempt in range(max_retries):
            try:
                self.log(f"Opening conversation for UID {target_uid} (Attempt {attempt+1}/{max_retries})...")
                self.driver.get(f"https://www.facebook.com/messages/e2ee/t/{target_uid}")
                time.sleep(5)
                self.log("Conversation opened.")
                return True
            except Exception as e:
                self.log(f"Error opening conversation: {e}")
                time.sleep(3)
        return False

    def send_single_message(self, message, max_attempts=3):
        for attempt in range(max_attempts):
            try:
                full_message = f"{self.haters_name} {message}" if self.haters_name else message
                selectors = [
                    "//div[@aria-label='Message'][@contenteditable='true']",
                    "//div[@role='textbox'][@contenteditable='true']",
                    "//div[@data-lexical-editor='true']",
                    "//div[contains(@class, 'notranslate')][@contenteditable='true']",
                ]
                message_box = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.XPATH, selector)
                        if elements and elements[0].is_displayed():
                            message_box = elements[0]
                            break
                    except Exception:
                        continue

                if not message_box:
                    js_script = """
                    var editables = document.querySelectorAll('[contenteditable="true"]');
                    for (var i = 0; i < editables.length; i++) {
                        var elem = editables[i];
                        if (elem.offsetParent !== null && 
                            (elem.getAttribute('role') === 'textbox' || 
                             elem.getAttribute('aria-label') === 'Message')) {
                            return elem;
                        }
                    }
                    return null;
                    """
                    message_box = self.driver.execute_script(js_script)

                if not message_box:
                    time.sleep(1)
                    continue

                try:
                    message_box.click()
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].focus(); arguments[0].click();", message_box)
                    except Exception:
                        pass

                time.sleep(0.3)

                # clear and set
                self.driver.execute_script("""
                    var elem = arguments[0];
                    elem.focus();
                    elem.innerHTML = '';
                    elem.textContent = '';
                """, message_box)
                time.sleep(0.2)

                escaped_msg = (full_message
                    .replace('\\', '\\\\')
                    .replace("'", "\\'")
                    .replace('"', '\\"')
                    .replace('\n', '\\n')
                    .replace('\r', '\\r')
                    .replace('\t', '\\t'))

                js_code = f"""
                var elem = arguments[0];
                var text = '{escaped_msg}';
                elem.textContent = text;
                elem.dispatchEvent(new Event('input', {{ bubbles: true, cancelable: true }}));
                elem.dispatchEvent(new Event('change', {{ bubbles: true, cancelable: true }}));
                var range = document.createRange();
                var sel = window.getSelection();
                range.selectNodeContents(elem);
                range.collapse(false);
                sel.removeAllRanges();
                sel.addRange(range);
                return elem.textContent.length;
                """
                self.driver.execute_script(js_code, message_box)
                time.sleep(0.3)

                sent = False
                try:
                    actions = ActionChains(self.driver)
                    actions.send_keys(Keys.RETURN).perform()
                    sent = True
                except Exception:
                    pass

                if not sent:
                    send_selectors = [
                        "//div[@aria-label='Send']",
                        "//div[@aria-label='Press enter to send']",
                        "//button[contains(@aria-label, 'Send')]",
                    ]
                    for selector in send_selectors:
                        try:
                            send_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                            send_btn.click()
                            sent = True
                            break
                        except Exception:
                            continue

                if not sent:
                    try:
                        js_send = """
                        var elem = arguments[0];
                        var enterEvent = new KeyboardEvent('keydown', {
                            key: 'Enter',
                            code: 'Enter',
                            keyCode: 13,
                            which: 13,
                            bubbles: true,
                            cancelable: true
                        });
                        elem.dispatchEvent(enterEvent);
                        """
                        self.driver.execute_script(js_send, message_box)
                        sent = True
                    except Exception:
                        pass

                if sent:
                    return True
                else:
                    time.sleep(1)
            except Exception as e:
                time.sleep(1)
                continue
        return False

    def start_sending(self, stop_event=None):
        """
        Blocking send loop. Use stop_event (threading.Event) to stop externally.
        Returns dict summary.
        """
        if not self.messages:
            self.log("No messages loaded.")
            return {"sent": 0, "failed": 0}

        message_index = 0
        message_count = 0
        sent_count = 0
        failed_count = 0
        consecutive_failures = 0
        max_consecutive_failures = 5

        while not (stop_event and stop_event.is_set()):
            try:
                message = self.messages[message_index]
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message_count += 1
                self.log(f"[{current_time}] Sending message #{message_count}: {message[:60]}...")
                success = self.send_single_message(message)
                if success:
                    sent_count += 1
                    consecutive_failures = 0
                    self.log(f"[{current_time}] Message #{message_count} SENT")
                else:
                    failed_count += 1
                    consecutive_failures += 1
                    self.log(f"[{current_time}] Message #{message_count} FAILED")
                    if consecutive_failures >= max_consecutive_failures:
                        self.log("Too many consecutive failures, refreshing page and pausing 5s...")
                        try:
                            self.driver.refresh()
                            time.sleep(5)
                            consecutive_failures = 0
                        except Exception:
                            pass

                # wait with stop checks
                for _ in range(self.speed_seconds):
                    if stop_event and stop_event.is_set():
                        break
                    time.sleep(1)

                message_index = (message_index + 1) % len(self.messages)

            except Exception as e:
                self.log(f"Unexpected error in send loop: {e}")
                time.sleep(5)
                continue

        self.log("Sending stopped by user." if (stop_event and stop_event.is_set()) else "Sending finished.")
        return {"sent": sent_count, "failed": failed_count, "total_attempts": message_count}

    def quit(self):
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
                self.log("Browser closed.")
        except Exception:
            pass
