import tempfile
import time
import uuid
import secrets
import json
import re
import io
import mimetypes
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal
import random

import requests
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False


st.set_page_config(
    page_title="Trueman",
    page_icon="😄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("😄 Trueman AI Assistant + Communications")


# ---------------- Settings ----------------
USE_SEARCH = False       
USE_CODE_EXEC = False    
DEBUG = True             

APP_URL = "https://50trueman.streamlit.app"

MAX_INPUT_CHARS = 2000
MAX_QUESTIONS_PER_CHAT = 20
MIN_SECONDS_BETWEEN_SENDS = 3
CONTEXT_CHAR_LIMIT = 10000
MAX_RECENT_MESSAGES = 8
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_FILE_CHARS = 12000
SUMMARY_TRIGGER_MESSAGES = 10
SUMMARY_REFRESH_EVERY = 8
FOLLOWUP_COUNT = 3

MAX_ATTEMPTS_PER_MODEL = 3
QUOTA_COOLDOWN_SECONDS = 90
SHARE_TTL_SECONDS = 7 * 24 * 60 * 60

ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"

MODELS = list(
    dict.fromkeys(
        [
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
        ]
    )
)

SUGGESTIONS = [
    "Explain black holes like I'm 10",
    "Help me write a CV that slaps",
    "Teach me 5 Zulu phrases",
    "Is it ever okay to put pineapple on pizza?",
]

LEARNING_MODES = {
    "General": "",
    "Explain simply": (
        "LEARNING MODE: Explain every topic like the user is a smart "
        "beginner. Use simple language, useful analogies, and check "
        "whether the explanation makes sense."
    ),
    "Tutor": (
        "LEARNING MODE: Act as a patient tutor. Break topics into "
        "small steps, explain why each step matters, and ask useful "
        "checkpoint questions when it helps."
    ),
    "Quiz": (
        "LEARNING MODE: When the user asks to learn or practice, quiz "
        "them one question at a time. Give encouraging feedback after "
        "each answer, then ask the next question."
    ),
    "Flashcards": (
        "LEARNING MODE: When explaining a topic, turn the key points "
        "into concise question-and-answer flashcards."
    ),
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".java", ".c",
    ".cpp", ".h", ".sql", ".log",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}

OUT_OF_ENERGY = (
    "Eish! I've talked so much today that all my daily limits are "
    "finished. Give me a little while to recharge, sharp?"
)

SOMETHING_BROKE = (
    "Yoh, something went wrong on my side and it's not the daily "
    "limits. Try again in a bit, sharp?"
)

TOO_MANY_QUESTIONS = (
    "Yoh, even Edison took breaks! I've hit my limit of "
    f"{MAX_QUESTIONS_PER_CHAT} questions for this chat. Hit 'Clear "
    "chat' in the sidebar and we start fresh, sharp?"
)

TOO_LONG = (
    "Yoh, that's not a question, that's a whole novel! Give me the "
    f"short version (max {MAX_INPUT_CHARS} characters) and I'll give "
    "you the good stuff."
)

SLOW_DOWN = (
    "Eish, hang on bra! Even my genius needs "
    f"{MIN_SECONDS_BETWEEN_SENDS} seconds between questions. "
    "Try again now, sharp?"
)

FILE_TOO_LARGE = (
    "Yoh, that file is too heavy for this chat. Keep it under "
    f"{MAX_FILE_BYTES // (1024 * 1024)} MB and we can work with it."
)

UNSUPPORTED_FILE = (
    "Eish, I can't read that file type yet. Try text, Markdown, CSV, "
    "JSON, code, PDF, an image, or a common audio file."
)

RETRYABLE_ERRORS = (
    "503", "unavailable", "overloaded", "deadline", "timeout", "timed out", "internal"
)

RATE_LIMIT_ERRORS = (
    "429", "quota", "rate limit", "resource exhausted", "resource_exhausted"
)


Role = Literal["user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    text: str
    attachment: dict[str, Any] | None = None
    model: str | None = None
    tokens: int = 0
    feedback: int | None = None
    error: bool = False
    retryable: bool = False
    followups: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def chaos_instruction(level: int) -> str:
    if level <= 3:
        return (
            "ENERGY LEVEL: Keep it calm and gentle today. Fewer jokes, "
            "more focus - like a wise uncle sipping tea. Still warm, "
            "just softer."
        )
    if level >= 8:
        return (
            "ENERGY LEVEL: Maximum chaos! Be dramatic, exaggerate "
            "wildly, turn every answer into a performance - full braai "
            "energy, but never mean."
        )
    return (
        "ENERGY LEVEL: Your normal self - playful, warm, energetic, "
        "but sensible when it matters."
    )


def learning_mode_instruction(mode: str) -> str:
    return LEARNING_MODES.get(mode, "")


def truncate_text(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "..."


def build_memory_context(
    profile: dict[str, str],
    facts: list[str],
    summary: str,
) -> str:
    lines = []
    if profile.get("name"):
        lines.append(f"Name: {profile['name']}")
    if profile.get("location"):
        lines.append(f"Location: {profile['location']}")
    if profile.get("interests"):
        lines.append(f"Interests: {profile['interests']}")
    if profile.get("goals"):
        lines.append(f"Goals: {profile['goals']}")
    if facts:
        lines.append("Remembered facts: " + "; ".join(facts[-8:]))
    if summary:
        lines.append(f"Conversation summary: {summary}")

    if not lines:
        return ""

    return truncate_text(" | ".join(lines), 1600)


def get_personality(
    can_search: bool = False,
    chaos: int = 6,
    learning_mode: str = "General",
    memory_context: str = "",
) -> str:
    text = (
        "Your name is Trueman. "
        "WHO YOU ARE: You are a proud Durban boy, born and bred, and a "
        "brilliant mind with the curiosity of Thomas Edison and the "
        "insight of Albert Einstein. You can explain anything, from "
        "science to business to life problems, in a way anyone can "
        "understand. You love to talk, you are energetic and a little "
        "chaotic, but always warm and friendly, like the favourite uncle "
        "or best friend everyone wants at the braai. "
        "LANGUAGE: English is your main language. Sprinkle in light "
        "South African slang here and there (like 'eish', 'sharp', "
        "'yoh', 'lekker', 'howzit'), but not in every sentence. You "
        "understand Zulu fully. If the user writes in Zulu, reply in "
        "Zulu. If they ask you to speak Zulu, do it. Otherwise, drop in "
        "a Zulu word or phrase now and then, like 'sawubona' or 'yebo'. "
        "HOW YOU HELP: Give a real, accurate, useful answer first, then "
        "add your humor. Give practical, thoughtful advice like someone "
        "who truly cares. Explain with simple examples. If you don't "
        "know something, admit it with a funny comment instead of "
        "making things up. "
        "HUMOR: Big energy, playful exaggeration, funny comparisons, "
        "friendly teasing. Be dramatic about small problems. "
        "RULES: Never be mean or joke at the user's expense. When "
