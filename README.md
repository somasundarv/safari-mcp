# safari-mcp

Browser automation for Claude Code using your real, logged-in Safari — the
Safari counterpart to the official Chrome integration, built as an MCP
server over AppleScript. No dependencies, single Python file.

## What it can and can't do vs the Chrome extension

| Capability | Chrome ext | safari-mcp |
|---|---|---|
| Navigate, click, fill forms | yes | yes |
| Read page text / DOM | yes | yes |
| Uses your logged-in sessions | yes | yes |
| Run arbitrary JS in the page | yes | yes |
| Screenshots | yes | yes (window PNG) |
| Read console logs | yes | no (Safari exposes no API) |
| Inspect network requests | yes | no |
| Record GIFs | yes | no |
| Per-site permission model | yes | no — gate via Claude Code tool permissions |

## One-time setup

1. Safari > Settings > Advanced > enable **Show features for web developers**.
2. Safari > Settings > Developer > enable **Allow JavaScript from Apple Events**.
3. Register the server:

   ```bash
   claude mcp add safari -- python3 /path/to/safari-mcp/safari_mcp.py
   ```

4. First tool call pops a macOS dialog — allow your terminal app to control
   Safari (System Settings > Privacy & Security > Automation if you miss it).

## Tools

- `safari_navigate` — open URL in current tab, wait for load
- `safari_get_page_text` — visible text + URL of current page
- `safari_find` — locate clickable elements by label text, returns selectors
- `safari_click` — click by CSS selector
- `safari_fill` — set input value (fires input/change events)
- `safari_run_js` — escape hatch: any JS, returns result
- `safari_list_tabs` / `safari_new_tab`
- `safari_screenshot` — front-window PNG to a path

## Example prompts

    Open localhost:3000 in Safari, submit the login form with an invalid
    email, and tell me what error message appears.

    Go to my banking site tab, list what's on the page.

    In Safari, find the "Add Contact" button on the current page and click it.

## Security notes

This drives your real browser with your real sessions — same trust model as
the Chrome extension. Claude Code's normal tool-permission prompts are the
gate: leave MCP tool calls on "ask" (default) rather than auto-allowing, and
be deliberate about prompts that touch banking/email. JavaScript-from-Apple-
Events is a global Safari toggle; turn it off when not in use if that
concerns you.

## Limitations

- Single "current tab of front window" model — no parallel multi-tab control
  (use `safari_run_js` + `safari_list_tabs` to work around).
- Sites with strict CSP may block injected JS side effects in rare cases.
- JS dialogs (alert/confirm) block AppleScript the same way they block the
  Chrome extension — dismiss manually.
- `do JavaScript` returns only serializable values (strings/numbers) —
  return strings from your JS.
