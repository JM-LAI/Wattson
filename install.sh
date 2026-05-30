#!/usr/bin/env bash
# Wattson — one-liner installer
# bash <(curl -sSL https://raw.githubusercontent.com/JM-LAI/Wattson/main/install.sh)

set -euo pipefail

CYAN='\033[36m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
WHITE='\033[1;37m'
GREY='\033[90m'
RED='\033[1;31m'
RESET='\033[0m'
LINE="────────────────────────────────────────────────────────────"

REPO_URL="https://github.com/JM-LAI/Wattson.git"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/Wattson}"
KEYCHAIN_ACCOUNT="wattson"
APP_NAME="Wattson"
APP_DEST="${HOME}/Applications/${APP_NAME}.app"
CERT_NAME="Wattson Dev"

# old branding constants for cleanup
OLD_KEYCHAIN_ACCOUNT="brand-voice-agent"
OLD_APP_DEST="${HOME}/Applications/BrandVoice.app"
OLD_INSTALL_DIR="${HOME}/Brand-Voice-Agent"
OLD_PLIST="$HOME/Library/LaunchAgents/com.local.brand-voice-agent.plist"
OLD_APP_SUPPORT="$HOME/Library/Application Support/brand-voice-agent"
NEW_APP_SUPPORT="$HOME/Library/Application Support/wattson"

print_header() {
    printf "\n${CYAN}${LINE}${RESET}\n"
    printf "${WHITE}  ⚡ Wattson — Installer${RESET}\n"
    printf "${CYAN}${LINE}${RESET}\n\n"
}

ok()   { printf "${GREEN}[✓]${RESET} %s\n" "$1"; }
info() { printf "${GREY}    %s${RESET}\n" "$1"; }
warn() { printf "${YELLOW}[!]${RESET} %s\n" "$1"; }
fail() { printf "${RED}[✗]${RESET} %s\n" "$1"; exit 1; }

# -----------------------------------------------------------------------

print_header

# macOS only
[[ "$(uname)" == "Darwin" ]] || fail "This tool is macOS only."
ok "macOS detected"

# -----------------------------------------------------------------------
# Clean up old Brand Voice install
# -----------------------------------------------------------------------
CLEANED=false

# kill old processes
if pgrep -f "BrandVoice" &>/dev/null; then
    pkill -f "BrandVoice" 2>/dev/null || true
    info "Stopped old BrandVoice process"
    CLEANED=true
fi
if pgrep -f "python.*app.main" &>/dev/null; then
    pkill -f "python.*app.main" 2>/dev/null || true
    info "Stopped old Python process"
    CLEANED=true
fi

# remove old LaunchAgent
if [[ -f "$OLD_PLIST" ]]; then
    launchctl unload -w "$OLD_PLIST" 2>/dev/null || true
    rm -f "$OLD_PLIST"
    info "Removed old LaunchAgent"
    CLEANED=true
fi

# remove old BrandVoice.app
if [[ -d "$OLD_APP_DEST" ]]; then
    rm -rf "$OLD_APP_DEST"
    info "Removed old BrandVoice.app"
    CLEANED=true
fi

# migrate state from old brand-voice-agent to wattson
if [[ -d "$OLD_APP_SUPPORT" && ! -d "$NEW_APP_SUPPORT" ]]; then
    mkdir -p "$NEW_APP_SUPPORT"
    cp -R "$OLD_APP_SUPPORT/" "$NEW_APP_SUPPORT/" 2>/dev/null || true
    info "Migrated settings from Brand Voice to Wattson"
    CLEANED=true
fi

# migrate API key from old keychain account
OLD_KEY=$(security find-generic-password -a "$OLD_KEYCHAIN_ACCOUNT" -s "lightning-api-key" -w 2>/dev/null || echo "")
if [[ -n "$OLD_KEY" ]]; then
    NEW_KEY=$(security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "lightning-api-key" -w 2>/dev/null || echo "")
    if [[ -z "$NEW_KEY" ]]; then
        security add-generic-password -a "$KEYCHAIN_ACCOUNT" -s "lightning-api-key" -w "$OLD_KEY" 2>/dev/null || true
        info "Migrated API key to new keychain account"
    fi
    security delete-generic-password -a "$OLD_KEYCHAIN_ACCOUNT" -s "lightning-api-key" 2>/dev/null || true
    CLEANED=true
fi

# remove old repo folder (after migration)
if [[ -d "$OLD_INSTALL_DIR" && "$OLD_INSTALL_DIR" != "$INSTALL_DIR" ]]; then
    info "Old Brand-Voice-Agent folder found at $OLD_INSTALL_DIR"
    printf "    ${YELLOW}Remove it? (y/n): ${RESET}"
    read -r yn
    if [[ "$yn" =~ ^[Yy] ]]; then
        rm -rf "$OLD_INSTALL_DIR"
        info "Removed $OLD_INSTALL_DIR"
    fi
    CLEANED=true
fi

if [[ "$CLEANED" == "true" ]]; then
    ok "Old Brand Voice install cleaned up"
    info "You can remove stale 'Python' / 'BrandVoice' entries from Accessibility/Input Monitoring"
fi

# -----------------------------------------------------------------------
# Also kill any running Wattson for clean rebuild
# -----------------------------------------------------------------------
pkill -f "Wattson.app" 2>/dev/null || true

# -----------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------

# homebrew
if ! command -v brew &>/dev/null; then
    warn "Homebrew not found — installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
ok "Homebrew available"

# python 3.11+
PYTHON_BIN=""
for py in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$py" &>/dev/null; then
        ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON_BIN="$py"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    warn "Python 3.11+ not found — installing via Homebrew..."
    brew install python@3.12
    PYTHON_BIN="python3.12"
fi
ok "Python: $($PYTHON_BIN --version)"

# clone or update repo
if [[ -d "$INSTALL_DIR/.git" ]]; then
    ok "Repo already cloned at ${INSTALL_DIR}"
    info "Pulling latest..."
    git -C "$INSTALL_DIR" reset --hard HEAD 2>/dev/null || true
    git -C "$INSTALL_DIR" clean -fd 2>/dev/null || true
    if ! git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null; then
        info "Syncing to latest remote..."
        git -C "$INSTALL_DIR" fetch origin main 2>/dev/null
        git -C "$INSTALL_DIR" reset --hard origin/main 2>/dev/null
    fi
    ok "Up to date"
elif [[ -f "$INSTALL_DIR/app/main.py" ]]; then
    ok "Project found at ${INSTALL_DIR} (not a git repo, skipping pull)"
else
    info "Cloning repo to ${INSTALL_DIR}..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned to ${INSTALL_DIR}"
fi

cd "$INSTALL_DIR"

# virtual environment + deps
if [[ ! -d ".venv" ]]; then
    info "Creating virtual environment..."
    "$PYTHON_BIN" -m venv --copies .venv
fi
info "Installing dependencies..."
.venv/bin/pip install --quiet --upgrade pip 2>/dev/null
.venv/bin/pip install --quiet -r requirements.txt 2>/dev/null
ok "Dependencies installed"

# -----------------------------------------------------------------------
# API key
# -----------------------------------------------------------------------
printf "\n${CYAN}${LINE}${RESET}\n"
printf "${WHITE}  Lightning AI API Key${RESET}\n"
printf "${CYAN}${LINE}${RESET}\n\n"

existing_key=$(security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "lightning-api-key" -w 2>/dev/null || echo "")
if [[ -n "$existing_key" ]]; then
    ok "API key already in Keychain"
    printf "    ${GREY}Replace it? (y/n): ${RESET}"
    read -r yn
    if [[ ! "$yn" =~ ^[Yy] ]]; then
        info "Keeping existing key"
    else
        existing_key=""
    fi
fi

if [[ -z "$existing_key" ]]; then
    printf "${WHITE}  You need a free Lightning AI API key to continue.${RESET}\n\n"
    printf "${GREY}  Steps:${RESET}\n"
    printf "${GREY}    1. Go to: ${WHITE}https://lightning.ai/lightning-ai/model-apis?showApiKey=true${RESET}\n"
    printf "${GREY}    2. Sign up or log in (free)${RESET}\n"
    printf "${GREY}    3. Click \"Create API Key\"${RESET}\n"
    printf "${GREY}    4. Copy the key (starts with sk-lit-...)${RESET}\n\n"

    open "https://lightning.ai/lightning-ai/model-apis?showApiKey=true" 2>/dev/null || true

    printf "${YELLOW}I've opened the page in your browser.${RESET}\n"
    printf "${YELLOW}Once you have the key, paste it here and press Enter.${RESET}\n\n"
    printf "${WHITE}API key: ${RESET}"
    read -rs api_key
    echo ""

    if [[ -n "$api_key" ]]; then
        security delete-generic-password -a "$KEYCHAIN_ACCOUNT" -s "lightning-api-key" 2>/dev/null || true
        security add-generic-password -a "$KEYCHAIN_ACCOUNT" -s "lightning-api-key" -w "$api_key"
        ok "API key stored in Keychain"
    else
        warn "No key entered — you can add it later from the menu bar (Settings → API Key)"
    fi
fi

# -----------------------------------------------------------------------
# Self-signed certificate for stable TCC permissions across updates
# -----------------------------------------------------------------------
printf "\n${CYAN}${LINE}${RESET}\n"
printf "${WHITE}  Code Signing Certificate${RESET}\n"
printf "${CYAN}${LINE}${RESET}\n\n"

if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CERT_NAME"; then
    ok "Signing certificate already exists"
    # ensure partition list is set (fixes keychain popup loop for existing certs)
    info "Verifying codesign access..."
    if ! codesign --force --sign "$CERT_NAME" /dev/null 2>/dev/null; then
        printf "    ${YELLOW}Enter your Mac login password to fix keychain access:${RESET} "
        read -rs kc_pass
        echo ""
        security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
          -k "$kc_pass" ~/Library/Keychains/login.keychain-db 2>/dev/null && \
          ok "Keychain access fixed" || \
          warn "Could not update keychain — you may see a prompt during signing"
    fi
else
    info "Creating self-signed certificate (one-time setup)..."
    info "This ensures permissions persist across app updates."

    openssl req -x509 -newkey rsa:2048 -days 3650 \
      -keyout /tmp/wattson.key -out /tmp/wattson.crt -nodes \
      -subj "/CN=${CERT_NAME}" \
      -addext "keyUsage=critical,digitalSignature" \
      -addext "extendedKeyUsage=codeSigning" 2>/dev/null

    openssl pkcs12 -export -legacy \
      -in /tmp/wattson.crt -inkey /tmp/wattson.key \
      -out /tmp/wattson.p12 -password pass:wattson 2>/dev/null

    # import with -A flag so all apps (including codesign) can use without prompting
    security import /tmp/wattson.p12 -k ~/Library/Keychains/login.keychain-db \
      -P wattson -A 2>/dev/null

    # set partition list so codesign never triggers a keychain dialog
    printf "\n${YELLOW}  Enter your Mac login password to authorize code signing:${RESET}\n"
    printf "${GREY}  (This prevents repeated keychain popups)${RESET}\n"
    printf "${WHITE}  Password: ${RESET}"
    read -rs kc_pass
    echo ""
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
      -k "$kc_pass" ~/Library/Keychains/login.keychain-db 2>/dev/null || \
      warn "Could not set partition list — you may see a keychain prompt when signing"

    # trust it for code signing
    security find-certificate -c "$CERT_NAME" -p ~/Library/Keychains/login.keychain-db > /tmp/wattson_cert.pem
    sudo security add-trusted-cert -d -r trustRoot -k ~/Library/Keychains/login.keychain-db /tmp/wattson_cert.pem 2>/dev/null

    rm -f /tmp/wattson.key /tmp/wattson.crt /tmp/wattson.p12 /tmp/wattson_cert.pem
    ok "Certificate created and trusted (no keychain prompts on future signs)"
fi

# -----------------------------------------------------------------------
# Build the .app bundle with PyInstaller
# -----------------------------------------------------------------------
printf "\n${CYAN}${LINE}${RESET}\n"
printf "${WHITE}  Building Wattson.app${RESET}\n"
printf "${CYAN}${LINE}${RESET}\n\n"

info "This takes about 15-30 seconds..."
rm -rf build dist 2>/dev/null || true
.venv/bin/pyinstaller wattson.spec --distpath dist --workpath build --clean -y 2>&1 | tail -3
ok "App built"

# sign with our cert
info "Signing with ${CERT_NAME}..."
codesign --force --deep --sign "$CERT_NAME" dist/${APP_NAME}.app 2>/dev/null
ok "Signed"

# install to ~/Applications
mkdir -p "$HOME/Applications"
if [[ -d "$APP_DEST" ]]; then
    info "Removing old Wattson.app..."
    rm -rf "$APP_DEST"
fi
cp -R "dist/${APP_NAME}.app" "$APP_DEST"
ok "Installed to ${APP_DEST}"

# register with LaunchServices
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DEST" 2>/dev/null || true
ok "Registered with macOS"

# install LaunchAgent for auto-start
PLIST_PATH="$HOME/Library/LaunchAgents/com.local.wattson.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.wattson</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>${APP_DEST}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/wattson.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/wattson.stderr.log</string>
</dict>
</plist>
PLIST
launchctl load -w "$PLIST_PATH" 2>/dev/null || true
ok "Auto-start at login enabled"

# -----------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------
printf "\n${CYAN}${LINE}${RESET}\n"
printf "${GREEN}  ⚡ Wattson is ready!${RESET}\n"
printf "${CYAN}${LINE}${RESET}\n\n"

printf "${YELLOW}Launch Wattson now?${RESET} (y/n): "
read -r yn
if [[ "$yn" =~ ^[Yy] ]]; then
    open "$APP_DEST"
    printf "\n"
    ok "Running! Look for W in your menu bar."
    info "The app will prompt for Accessibility permissions on first launch."
fi

printf "\n${GREY}  Quick reference:${RESET}\n"
printf "${GREY}    Cmd+Ctrl+G    Rewrite selected text${RESET}\n"
printf "${GREY}    Cmd+Ctrl+M    Cycle modes${RESET}\n"
printf "${GREY}    Cmd+Ctrl+Z    Undo last rewrite${RESET}\n"
printf "${GREY}    Menu bar      Settings, models, rules, history${RESET}\n\n"
printf "${GREY}  To update later:${RESET}\n"
printf "${GREY}    cd ~/Wattson && ./install.sh${RESET}\n\n"
printf "${GREY}  To uninstall:${RESET}\n"
printf "${GREY}    rm -rf ~/Applications/Wattson.app ~/Wattson${RESET}\n"
printf "${GREY}    security delete-certificate -c \"Wattson Dev\"${RESET}\n\n"
