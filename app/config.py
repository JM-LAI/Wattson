import os

APP_NAME = "wattson"
APP_SUPPORT = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", APP_NAME
)
STATE_PATH = os.path.join(APP_SUPPORT, "state.json")
RULES_DIR = os.path.join(APP_SUPPORT, "rules")
LOG_PATH = os.path.join(
    os.path.expanduser("~"), "Library", "Logs", f"{APP_NAME}.log"
)

CHAT_API_URL = "https://lightning.ai/api/v1/chat/completions"

KEYCHAIN_ACCOUNT = APP_NAME
KEYCHAIN_API_KEY_SERVICE = "lightning-api-key"
KEYCHAIN_CONFLUENCE_TOKEN_SERVICE = "confluence-api-token"

# old branding constants for migration
OLD_APP_NAME = "brand-voice-agent"
OLD_APP_SUPPORT = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", OLD_APP_NAME
)

# Gemma 4 31B is the recommended default — fast and reliable
DEFAULT_MODEL = "lightning-ai/gemma-4-31B-it"

# RCA generation is a big task — use a capable model + long timeout
RCA_MODEL = "lightning-ai/deepseek-v4-pro"
RCA_TIMEOUT = 120

# curated capable set — display name -> model ID. all six verified live against
# the Lightning AI /models endpoint and a real completion (Jun 2026).
MODELS = {
    "Gemma 4 31B (Recommended)": "lightning-ai/gemma-4-31B-it",
    "GPT-OSS 120B": "lightning-ai/gpt-oss-120b",
    "DeepSeek V4 Pro": "lightning-ai/deepseek-v4-pro",
    "Nemotron Super 120B": "lightning-ai/nemotron-3-super-120b-a12b",
    "Nemotron Ultra 550B": "lightning-ai/nemotron-3-ultra-550b-a55b",
    "MiniMax M2.5": "lightning-ai/minimax-m2.5",
}

# fallback order when a model times out — tries these in sequence
FALLBACK_MODELS = [
    "lightning-ai/gemma-4-31B-it",
    "lightning-ai/gpt-oss-120b",
    "lightning-ai/deepseek-v4-pro",
    "lightning-ai/nemotron-3-super-120b-a12b",
    "lightning-ai/nemotron-3-ultra-550b-a55b",
    "lightning-ai/minimax-m2.5",
]

MODES = ["Brand Voice", "Grammar Only", "Shorten", "Formal", "Casual", "Custom Voice"]

# map mode name to rules filename (no extension)
MODE_TO_FILENAME = {
    "Brand Voice": "brand-voice",
    "Grammar Only": "grammar",
    "Shorten": "shorten",
    "Formal": "formal",
    "Casual": "casual",
    "Custom Voice": "custom-voice",
}

DEFAULT_HOTKEY_REWRITE = "<cmd>+<ctrl>+g"
DEFAULT_HOTKEY_CYCLE = "<cmd>+<ctrl>+m"
DEFAULT_HOTKEY_UNDO = "<cmd>+<ctrl>+z"

MAX_HISTORY = 20

SOUND_PATH = "/System/Library/Sounds/Pop.aiff"

LAUNCHAGENT_LABEL = f"com.local.{APP_NAME}"
LAUNCHAGENT_PATH = os.path.join(
    os.path.expanduser("~"), "Library", "LaunchAgents",
    f"{LAUNCHAGENT_LABEL}.plist",
)

# bump this when default prompts change — triggers auto-regeneration of rules files
PROMPT_VERSION = 8

DEFAULT_STATE = {
    "enabled": True,
    "mode": "Brand Voice",
    "model": DEFAULT_MODEL,
    "hotkey_rewrite": DEFAULT_HOTKEY_REWRITE,
    "hotkey_cycle": DEFAULT_HOTKEY_CYCLE,
    "hotkey_undo": DEFAULT_HOTKEY_UNDO,
    "preview": False,
    "sound": True,
    "auto_start": False,
    "history": [],
    "prompt_version": 0,
    "input_monitoring_prompted": False,
    "confluence_base_url": "",
    "confluence_email": "",
}
