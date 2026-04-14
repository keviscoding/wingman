import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# Model IDs
# ---------------------------------------------------------------------------
LIVE_MODEL = "models/gemini-3.1-flash-live-preview"
PRO_MODEL = "models/gemini-3.1-pro-preview"
FLASH_MODEL = "models/gemini-3-flash-preview"

# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------
CAPTURE_FPS = 1.0
CAPTURE_MAX_WIDTH = 1024
FRAME_CHANGE_THRESHOLD = 0.02  # fraction of pixels that must differ
CHAT_READ_INTERVAL = 0.5  # minimum gap; actual rate limited by model response time

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
AUDIO_FORMAT_WIDTH = 2  # 16-bit
AUDIO_CHANNELS = 1
AUDIO_SEND_RATE = 16_000
AUDIO_RECV_RATE = 24_000
AUDIO_CHUNK = 1024

# ---------------------------------------------------------------------------
# Live session (voice commands only — system instruction is in live_session.py)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Reply generation (Pro)
# ---------------------------------------------------------------------------
CHAT_READER_PROMPT = (
    "Extract EVERY chat message from this screenshot EXACTLY as written. "
    "Do NOT paraphrase, summarize, or skip ANY message. Copy the EXACT text "
    "word-for-word, including all emojis, slang, abbreviations, and typos.\n\n"
    "Focus on the OPEN conversation (main chat area). "
    "IGNORE: sidebar/chat list, contact header, timestamps, date headers, "
    "read receipts, typing indicators, UI buttons, nav bars.\n\n"
    "Return a JSON array of ALL messages in order from top to bottom:\n"
    "[{\"speaker\":\"me\",\"text\":\"exact message text\"}, "
    "{\"speaker\":\"them\",\"text\":\"exact message text\"}]\n\n"
    "speaker = \"me\" for messages I sent (right side / colored bubbles)\n"
    "speaker = \"them\" for messages they sent (left side / plain bubbles)\n\n"
    "For media: use [image], [video], [voice note], [sticker], [GIF], "
    "[link: url], [shared post] as placeholders.\n"
    "If a message is a reply to another, add \"reply_to\": \"quoted text\".\n"
    "If no chat is visible, return [].\n\n"
    "IMPORTANT: Do NOT truncate. Output EVERY single message you can see."
)

CHAT_READER_BATCH_PROMPT = (
    "These {count} screenshots/videos show the SAME chat conversation. "
    "They are in ORDER — the first image is the top/oldest part of the chat, "
    "the last image is the bottom/newest part. Some images may overlap "
    "(showing some of the same messages). That's fine — just deduplicate.\n\n"
    "Your job: combine ALL the images into ONE complete, unified transcript. "
    "Extract EVERY message EXACTLY as written — word-for-word, including all "
    "emojis, slang, abbreviations, and typos. Do NOT skip, summarize, or "
    "paraphrase any message.\n\n"
    "Return a JSON array of ALL messages from the ENTIRE conversation, "
    "in chronological order (oldest first):\n"
    "[{{\"speaker\":\"me\",\"text\":\"exact message text\"}}, "
    "{{\"speaker\":\"them\",\"text\":\"exact message text\"}}]\n\n"
    "speaker = \"me\" for messages I sent (right side / colored bubbles)\n"
    "speaker = \"them\" for messages they sent (left side / plain bubbles)\n\n"
    "For media: use [image], [video], [voice note], [sticker], [GIF], "
    "[link: url], [shared post] as placeholders.\n"
    "If a message is a reply to another, add \"reply_to\": \"quoted text\".\n\n"
    "IMPORTANT: Do NOT truncate. Output the COMPLETE transcript from ALL images."
)

DEFAULT_STYLE = "balanced"

REPLY_SYSTEM_PROMPT = (
    "You learned everything from the training transcripts. You ARE the text "
    "game coach now. Analyze this conversation and help me close.\n\n"
    "Give me:\n"
    "1. A quick read of the situation — what's happening, what's her energy, "
    "what's working, what to watch out for.\n"
    "2. Your advice — what's the move here and why.\n"
    "3. Exactly 5 reply options I can send, with a brief explanation of why "
    "each one works. Label each option with a short name.\n\n"
    "Be real, be specific to THIS conversation. Don't be generic. "
    "Reference the patterns from the transcripts you learned from. "
    "Reply texts should be short like real texts with emojis where natural.\n\n"
    "Format as JSON so I can display it:\n"
    "{{\"read\": \"...\", \"advice\": \"...\", \"replies\": ["
    "{{\"label\": \"...\", \"text\": \"...\", \"why\": \"...\"}}]}}\n\n"
    "Conversation:\n{transcript}"
)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000
