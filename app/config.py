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

# old branding constants for migration
OLD_APP_NAME = "brand-voice-agent"
OLD_APP_SUPPORT = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", OLD_APP_NAME
)

DEFAULT_MODEL = "lightning-ai/gemma-4-31B-it"

# display name -> model ID, ordered by preference for fallback
MODELS = {
    "Gemma 4 31B": "lightning-ai/gemma-4-31B-it",
    "DeepSeek V4 Pro": "lightning-ai/deepseek-v4-pro",
    "DeepSeek V3.1": "lightning-ai/DeepSeek-V3.1",
    "Llama 3.3 70B": "lightning-ai/llama-3.3-70b",
    "Nemotron 3 Super": "lightning-ai/nvidia-nemotron-3-super-120b-a12b",
    "Kimi K2.5": "lightning-ai/kimi-k2.5",
    "GLM-5": "lightning-ai/glm-5",
}

# fallback order when a model times out — tries these in sequence
FALLBACK_MODELS = [
    "lightning-ai/deepseek-v4-pro",
    "lightning-ai/kimi-k2.5",
    "lightning-ai/nvidia-nemotron-3-super-120b-a12b",
    "lightning-ai/glm-5",
    "lightning-ai/gemma-4-31B-it",
    "lightning-ai/DeepSeek-V3.1",
    "lightning-ai/llama-3.3-70b",
]

MODES = ["Brand Voice", "Grammar Only", "Shorten", "Formal", "Casual"]

# map mode name to rules filename (no extension)
MODE_TO_FILENAME = {
    "Brand Voice": "brand-voice",
    "Grammar Only": "grammar",
    "Shorten": "shorten",
    "Formal": "formal",
    "Casual": "casual",
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
PROMPT_VERSION = 4

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
}
