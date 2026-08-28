#!/usr/bin/env python3
"""
safari-mcp: drive the real, logged-in Safari from Claude Code via AppleScript.

A minimal MCP stdio server (newline-delimited JSON-RPC, no dependencies).
Register with:

    claude mcp add safari -- python3 /path/to/safari-mcp/safari_mcp.py

Requirements (one-time, see README):
  * Safari > Settings > Advanced > "Show features for web developers"
  * Safari > Settings > Developer > "Allow JavaScript from Apple Events"
  * First tool call triggers a macOS prompt: allow your terminal to control Safari.
"""
import json
import subprocess
import sys
import time

PROTOCOL_VERSION = "2024-11-05"
MAX_TEXT = 50_000  # truncate page text so one call can't flood the context


# ------------------------- AppleScript plumbing -----------------------------

def osascript(script, *args, timeout=30):
    """Run AppleScript with argv passing (avoids all quote-escaping bugs)."""
    cmd = ["osascript", "-e", script]
    if args:
        cmd.append("--")
        cmd.extend(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")
    return proc.stdout.rstrip("\n")


ENSURE_WINDOW = '''
tell application "Safari"
    activate
    if (count of windows) = 0 then make new document
end tell
'''

RUN_JS = '''
on run argv
    tell application "Safari"
        if (count of windows) = 0 then make new document
        do JavaScript (item 1 of argv) in current tab of front window
    end tell
end run
'''


def run_js(js, timeout=30):
    return osascript(RUN_JS, js, timeout=timeout)


def wait_for_load(timeout_s=20):
    """Poll document.readyState until the page settles."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if run_js("document.readyState", timeout=10) in ("interactive", "complete"):
                return True
        except RuntimeError:
            pass  # page mid-navigation; JS context not ready yet
        time.sleep(0.5)
    return False


# ------------------------------- tools --------------------------------------

def t_navigate(url):
    osascript(ENSURE_WINDOW)
    osascript('''
on run argv
    tell application "Safari" to set URL of current tab of front window to (item 1 of argv)
end run''', url)
    loaded = wait_for_load()
    title = run_js("document.title") if loaded else "(still loading)"
    return f"Navigated to {url}\nLoaded: {loaded}\nTitle: {title}"


def t_get_page_text():
    text = run_js("document.body ? document.body.innerText : ''")
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f"\n...[truncated, {len(text)} chars total]"
    url = run_js("location.href")
    return f"URL: {url}\n\n{text}"


def t_run_js(code):
    out = run_js(code)
    return out if out else "(no return value)"


def t_click(selector):
    js = (
        "(() => { const el = document.querySelector(" + json.dumps(selector) + ");"
        "if (!el) return 'NOT_FOUND';"
        "el.scrollIntoView({block:'center'}); el.click();"
        "return 'clicked: ' + (el.innerText || el.value || el.tagName).slice(0,80); })()"
    )
    out = run_js(js)
    if out == "NOT_FOUND":
        raise RuntimeError(f"no element matches selector: {selector}")
    return out


def t_fill(selector, value):
    js = (
        "(() => { const el = document.querySelector(" + json.dumps(selector) + ");"
        "if (!el) return 'NOT_FOUND';"
        "el.focus(); el.value = " + json.dumps(value) + ";"
        "el.dispatchEvent(new Event('input', {bubbles:true}));"
        "el.dispatchEvent(new Event('change', {bubbles:true}));"
        "return 'filled ' + el.tagName + (el.name ? '[name=' + el.name + ']' : ''); })()"
    )
    out = run_js(js)
    if out == "NOT_FOUND":
        raise RuntimeError(f"no element matches selector: {selector}")
    return out


def t_find(query):
    js = (
        "(() => { const q = " + json.dumps(query.lower()) + "; const out = [];"
        "for (const el of document.querySelectorAll('a,button,input,select,textarea,[role=button]')) {"
        "  const label = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim();"
        "  if (label.toLowerCase().includes(q)) {"
        "    let sel = el.tagName.toLowerCase();"
        "    if (el.id) sel += '#' + el.id;"
        "    else if (el.name) sel += '[name=\"' + el.name + '\"]';"
        "    out.push(sel + '  ->  ' + label.slice(0,60));"
        "    if (out.length >= 20) break; } }"
        "return out.length ? out.join('\\n') : 'no interactive elements match'; })()"
    )
    return run_js(js)


def t_list_tabs():
    return osascript('''
tell application "Safari"
    set out to ""
    set wi to 0
    repeat with w in windows
        set wi to wi + 1
        set ti to 0
        repeat with t in tabs of w
            set ti to ti + 1
            set out to out & "w" & wi & ".t" & ti & "  " & (URL of t) & "  " & (name of t) & linefeed
        end repeat
    end repeat
    return out
end tell''')


def t_new_tab(url):
    osascript(ENSURE_WINDOW)
    osascript('''
on run argv
    tell application "Safari"
        tell front window
            set current tab to (make new tab with properties {URL:(item 1 of argv)})
        end tell
    end tell
end run''', url)
    wait_for_load()
    return f"Opened new tab: {url}"


def t_screenshot(path):
    # AppleScript window id of Safari's front window is its CGWindowID,
    # which `screencapture -l` accepts.
    win_id = osascript('tell application "Safari" to id of front window')
    subprocess.run(["screencapture", "-o", "-l", win_id, path], check=True, timeout=15)
    return f"Screenshot of Safari front window saved to {path}"


TOOLS = [
    {"name": "safari_navigate",
     "description": "Open a URL in Safari's current tab (front window) and wait for the page to load. Uses your real logged-in Safari session.",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
     "fn": lambda a: t_navigate(a["url"])},

    {"name": "safari_get_page_text",
     "description": "Return the visible text (innerText) and URL of the current Safari page. Truncated at 50k chars.",
     "inputSchema": {"type": "object", "properties": {}},
     "fn": lambda a: t_get_page_text()},

    {"name": "safari_run_js",
     "description": "Run JavaScript in the current Safari tab and return its result. Use for anything the other tools don't cover (reading attributes, scrolling, complex interactions).",
     "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
     "fn": lambda a: t_run_js(a["code"])},

    {"name": "safari_click",
     "description": "Click the first element matching a CSS selector in the current Safari tab.",
     "inputSchema": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]},
     "fn": lambda a: t_click(a["selector"])},

    {"name": "safari_fill",
     "description": "Set the value of an input/textarea matching a CSS selector and fire input/change events.",
     "inputSchema": {"type": "object",
                     "properties": {"selector": {"type": "string"}, "value": {"type": "string"}},
                     "required": ["selector", "value"]},
     "fn": lambda a: t_fill(a["selector"], a["value"])},

    {"name": "safari_find",
     "description": "Find interactive elements (links, buttons, inputs) whose label contains the query text. Returns up to 20 'selector -> label' lines. Use this to discover selectors before clicking.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
     "fn": lambda a: t_find(a["query"])},

    {"name": "safari_list_tabs",
     "description": "List all open Safari tabs across windows with their URLs and titles.",
     "inputSchema": {"type": "object", "properties": {}},
     "fn": lambda a: t_list_tabs()},

    {"name": "safari_new_tab",
     "description": "Open a URL in a new Safari tab and make it the current tab.",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
     "fn": lambda a: t_new_tab(a["url"])},

    {"name": "safari_screenshot",
     "description": "Capture Safari's front window to a PNG file at the given absolute path.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
     "fn": lambda a: t_screenshot(a["path"])},
]

TOOL_MAP = {t["name"]: t for t in TOOLS}


# --------------------------- MCP stdio loop ---------------------------------

def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, id_ = req.get("method"), req.get("id")

        if method == "initialize":
            reply(id_, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "safari-mcp", "version": "0.1.0"},
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            reply(id_, {"tools": [
                {k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS
            ]})
        elif method == "tools/call":
            name = req["params"]["name"]
            args = req["params"].get("arguments") or {}
            tool = TOOL_MAP.get(name)
            if tool is None:
                reply(id_, error={"code": -32602, "message": f"unknown tool: {name}"})
                continue
            try:
                out = tool["fn"](args)
                reply(id_, {"content": [{"type": "text", "text": out}]})
            except Exception as e:
                reply(id_, {"content": [{"type": "text", "text": f"Error: {e}"}],
                            "isError": True})
        elif id_ is not None:
            reply(id_, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
