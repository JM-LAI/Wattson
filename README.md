# ⚡ Wattson

macOS menu bar tool that rewrites CX support messages to match the team's brand voice. Select text anywhere, press a hotkey, get a cleaner version back.

Built for CREs, non-native speakers, dyslexic folks, and anyone who wants consistent brand voice without second-guessing every message.

## Install

1. Open **Terminal** (press Cmd+Space, type "Terminal", press Enter)
2. Paste this and press Enter:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/JM-LAI/Wattson/main/install.sh)
```

3. The installer will open the API key page in your browser — copy your key and paste it when prompted
4. It creates a signing certificate (asks for your Mac password once — this makes permissions persist across updates)
5. It builds **Wattson.app** and installs it to `~/Applications`
6. On first launch, macOS will prompt you to allow Accessibility and Input Monitoring — just toggle Wattson ON

That's it. No Python paths to hunt down, no framework binaries to find.

### Update

The installer pulls the latest code automatically:

```bash
cd ~/Wattson && ./install.sh
```

### Upgrading from Brand Voice (old name)

Just run the install command above. The installer automatically:
- Removes old BrandVoice.app
- Migrates your settings and API key
- Removes old LaunchAgent
- Optionally removes the old `~/Brand-Voice-Agent` folder

Only manual step: remove stale "Python" or "BrandVoice" entries from Accessibility/Input Monitoring in System Settings. Wattson only needs "Wattson" in those lists now.

### What You'll Need

- **macOS** (any recent version)
- **Lightning AI API key** (free) — get one at https://lightning.ai/lightning-ai/model-apis?showApiKey=true
- ~2 minutes

> **Important:** You need access to the **`lightning-ai`** org (not `lightningai-engineering`). The correct workspace URL is `https://lightning.ai/lightning-ai/home`. If you get a 403 or "no access" error, check you're in the right org.

### macOS Permissions

The app needs Accessibility and Input Monitoring to capture hotkeys and paste text.

On first launch, macOS should prompt you automatically. If it doesn't:

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Find **Wattson** in the list and toggle it **ON**
3. If it's not there, click **+** and find `Wattson.app` in `~/Applications`
4. Do the same for **Input Monitoring**

## How It Works

1. Select text in any app (Slack, email, Notes, anywhere)
2. Press **Cmd+Ctrl+G** — text is replaced with the rewritten version
3. Press **Cmd+Ctrl+M** to cycle between modes
4. Press **Cmd+Ctrl+Z** to undo the last rewrite

The menu bar shows the active mode: **W** (Brand Voice), **Gram** (Grammar), **Short** (Shorten), **Form** (Formal), **Chill** (Casual).

## Quick Launch Alias

Add this to your `~/.zshrc` for a `wattson` command that kills any running instance and (re)starts the app:

```bash
echo 'alias wattson="pkill -f Wattson 2>/dev/null; sleep 0.5; open ~/Applications/Wattson.app"' >> ~/.zshrc
source ~/.zshrc
```

## Modes

| Mode | What it does |
|---|---|
| **Brand Voice** | Full rewrite — brand voice + grammar + sentiment. Warm, human, technically accurate. |
| **Grammar Only** | Fix grammar, spelling, and text-speak (ur→your, u→you). Preserves tone. |
| **Shorten** | Make it shorter, keep all meaning and technical details. |
| **Formal** | Polish to professional tone. |
| **Casual** | Soften to friendly, approachable tone. |

All modes powered by Gemma 4 31B on Lightning AI (free tier). If a model is down, Wattson automatically falls back to the next available model and lets you know. Switch models from the menu bar.

## Editable Rules

Every mode's prompt is a plain text file you can edit:

**Menu bar → Edit Rules → [mode]** opens the file in your default text editor.

Rules live at `~/Library/Application Support/wattson/rules/`. Changes take effect on the next rewrite — no restart needed. To restore defaults: **Menu bar → Edit Rules → Reset All Rules**.

## Features

- **Auto-failover** — if a model is down, Wattson tries the next one and tells you which it used
- **Preview before paste** — review and edit the rewrite before it replaces your text
- **Undo** — Cmd+Ctrl+Z pastes back the original
- **Notifications** — success shows word count, failures show the error
- **Rewrite history** — last 20 rewrites accessible from the menu bar
- **Sound feedback** — optional system sound on completion
- **Hotkey recorder** — set custom hotkeys from the menu, no manual typing
- **Auto-start at login** — runs in the background via LaunchAgent
- **Connection test** — verify API connectivity from settings
- **First-run onboarding** — guided setup for new users
- **Dark mode** — preview window adapts to system appearance
- **CLI mode** — for scripts and automation (see below)

## CLI Mode

```bash
cd ~/Wattson
.venv/bin/python -m app.main --text "hi we see ur issue and are looking into it"

# use a specific mode
.venv/bin/python -m app.main --text "your message" --mode "Grammar Only"

# show all options
.venv/bin/python -m app.main --help
```

## Troubleshooting

### Hotkey not working
- Open System Settings → Privacy & Security → Accessibility — toggle **Wattson** ON
- Do the same for **Input Monitoring**
- If Wattson isn't listed, click + and find it in `~/Applications`
- Try **Menu bar → Settings → Fix Permissions**

### Menu bar icon disappeared
```bash
open ~/Applications/Wattson.app
```

### API errors
- Menu bar → Settings → Test Connection
- Check your API key: Menu bar → Settings → API Key
- Check logs: Menu bar → Settings → Open Logs

### Logs
```bash
tail -f ~/Library/Logs/wattson.log
```

## Uninstall

### 1. Stop the app
Click the menu bar icon → **Quit**, or:
```bash
pkill -f Wattson
```

### 2. Remove auto-start
```bash
launchctl unload -w ~/Library/LaunchAgents/com.local.wattson.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.local.wattson.plist
```

### 3. Remove the app
```bash
rm -rf ~/Applications/Wattson.app
```

### 4. Remove app data
```bash
rm -rf ~/Library/Application\ Support/wattson
rm -f ~/Library/Logs/wattson.log
rm -f ~/Library/Logs/wattson.stdout.log
rm -f ~/Library/Logs/wattson.stderr.log
```

### 5. Remove API key from Keychain
```bash
security delete-generic-password -s "lightning-api-key" -a "wattson" 2>/dev/null
```

### 6. Remove signing certificate
```bash
security delete-certificate -c "Wattson Dev"
```

### 7. Remove the repo
```bash
rm -rf ~/Wattson
```

### 8. Remove macOS permissions
System Settings → Privacy & Security → Accessibility / Input Monitoring — remove the Wattson entry.

## File Locations

| What | Where |
|---|---|
| App bundle | `~/Applications/Wattson.app` |
| Source code | `~/Wattson/app/` |
| Rules files | `~/Library/Application Support/wattson/rules/` |
| State/config | `~/Library/Application Support/wattson/state.json` |
| Logs | `~/Library/Logs/wattson.log` |
| LaunchAgent | `~/Library/LaunchAgents/com.local.wattson.plist` |
| API key | macOS Keychain (service: `lightning-api-key`) |

## Architecture

```
app/
  main.py       — entry point (GUI or CLI)
  tray.py       — rumps menu bar app, mode display, spinner
  ui.py         — hotkey recorder, preview window, notifications, onboarding
  hotkeys.py    — pynput global hotkey listener (daemon thread)
  clipboard.py  — Quartz CGEvent clipboard simulation
  llm.py        — Lightning AI chat completions client with auto-failover
  prompts.py    — load/save editable rules from disk
  settings.py   — state.json + macOS Keychain
  config.py     — constants, model list, defaults
```

Powered by Lightning AI's hosted models (Gemma 4 31B default). No local model needed.
