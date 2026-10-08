from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import time
import zlib
from datetime import date
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types


st.set_page_config(
    page_title="Trueman",
    page_icon="😄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("😄 Trueman")


# ---------------- Settings ----------------
USE_SEARCH = False
DEBUG = False

MAX_INPUT_CHARS = 2000
MAX_QUESTIONS_PER_CHAT = 20
MIN_SECONDS_BETWEEN_SENDS = 3
CONTEXT_CHAR_LIMIT = 10000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_FILE_CHARS = 12000
SUMMARY_TRIGGER_MESSAGES = 10
SUMMARY_REFRESH_EVERY = 8
FOLLOWUP_COUNT = 3

MODELS = list(
    dict.fromkeys(
        [
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
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".sql",
    ".log",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".aac",
    ".flac",
}

OUT_OF_ENERGY = (
    "Eish! I've talked so much today that all my daily limits are "
    "finished. Give me until tomorrow morning to recharge, sharp?"
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


# ---------------- Personality ----------------
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
        "someone is sad, stressed, or going through something serious, "
        "calm down the chaos and be gentle and supportive. "
    )

    mode_instruction = learning_mode_instruction(learning_mode)
    if mode_instruction:
        text += mode_instruction + " "

    text += chaos_instruction(chaos)
    text += " "

    if memory_context:
        text += (
            "USER MEMORY: " + memory_context + " Use this naturally "
            "when it is relevant. If the user's latest request conflicts "
            "with this memory, follow the latest request. Do not mention "
            "the memory directly unless it is useful. "
        )

    if can_search:
        text += (
            "SEARCH: You can search the internet for current news, "
            "scores and prices. Use it when a question needs "
            "up-to-date facts. "
        )
    else:
        text += (
            "LIMITS: You cannot look up live information like news, "
            "weather or scores. If asked, say so honestly with a joke, "
            "and share what you do know. "
        )

    text += f"Today's date is {date.today():%A, %d %B %Y}."
    return text


@st.cache_resource(show_spinner=False)
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


try:
    client = get_client()
except Exception as e:
    st.error(f"Couldn't load the Gemini client: {e}")
    st.info("Check that GEMINI_API_KEY is set in your Streamlit secrets.")
    st.stop()


def build_config(
    chaos: int,
    learning_mode: str,
    memory_context: str,
) -> types.GenerateContentConfig:
    config_kwargs = {
        "system_instruction": get_personality(
            can_search=USE_SEARCH,
            chaos=chaos,
            learning_mode=learning_mode,
            memory_context=memory_context,
        )
    }

    if USE_SEARCH:
        config_kwargs["tools"] = [
            types.Tool(google_search=types.GoogleSearch())
        ]

    return types.GenerateContentConfig(**config_kwargs)


# ---------------- Error and message helpers ----------------
def is_quota_error(error: str) -> bool:
    e = error.lower()
    return any(
        marker in e
        for marker in (
            "quota",
            "429",
            "rate limit",
            "resource exhausted",
            "resource_exhausted",
        )
    )


def short_reason(error: str) -> str:
    low = error.lower()

    for marker in ("quota", "429", "rate limit", "resource exhausted"):
        start = low.find(marker)
        if start >= 0:
            break
    else:
        start = 0

    return error[start : start + 160]


def message_size(message: dict[str, Any]) -> int:
    size = len(message.get("text", ""))
    attachment = message.get("attachment") or {}
    size += len(attachment.get("extracted_text", ""))
    # Roughly weight binary attachments so old large files fall out of context.
    size += len(attachment.get("data", b"")) // 4
    return size


def trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [m for m in messages if not m.get("error")]
    total = sum(message_size(m) for m in kept)

    i = 0
    while total > CONTEXT_CHAR_LIMIT and i < len(kept) - 4:
        total -= message_size(kept[i])
        i += 1

    return kept[i:]


def attachment_label(attachment: dict[str, Any]) -> str:
    name = attachment.get("name", "attachment")
    kind = attachment.get("kind", "file")
    icons = {
        "document": "📄",
        "image": "🖼️",
        "audio": "🎙️",
        "file": "📎",
    }
    return f"{icons.get(kind, '📎')} {name}"


def parts_from_attachment(attachment: dict[str, Any]) -> list[types.Part]:
    if not attachment:
        return []

    parts = []
    name = attachment.get("name", "attachment")
    extracted_text = attachment.get("extracted_text", "")

    if extracted_text:
        parts.append(
            types.Part(
                text=(
                    f"ATTACHMENT: {name}\n\n"
                    f"{truncate_text(extracted_text, MAX_EXTRACTED_FILE_CHARS)}"
                )
            )
        )

    data = attachment.get("data")
    mime_type = attachment.get("mime_type")

    if data and mime_type:
        try:
            parts.append(
                types.Part.from_bytes(
                    data=data,
                    mime_type=mime_type,
                )
            )
        except Exception:
            parts.append(
                types.Part(
                    text=f"[Attachment included but could not be encoded: {name}]"
                )
            )

    return parts


def build_contents(messages: list[dict[str, Any]]) -> list[types.Content]:
    contents = []

    summary = st.session_state.get("conversation_summary", "")
    if summary:
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=(
                            "Conversation so far, summarized:\n"
                            + truncate_text(summary, 1800)
                        )
                    )
                ],
            )
        )
        contents.append(
            types.Content(
                role="model",
                parts=[
                    types.Part(
                        text="Got it — I'll use that earlier context."
                    )
                ],
            )
        )

    for message in trim_messages(messages):
        parts = [types.Part(text=message.get("text", ""))]
        parts.extend(parts_from_attachment(message.get("attachment") or {}))

        contents.append(
            types.Content(
                role="user" if message["role"] == "user" else "model",
                parts=parts,
            )
        )

    return contents


def available_models() -> list[str]:
    return [
        model
        for model in MODELS
        if model not in st.session_state.dead_models
    ]


# ---------------- Main streaming ----------------
def stream_trueman(
    messages: list[dict[str, Any]],
    result: dict[str, Any],
    chaos: int,
    learning_mode: str,
    memory_context: str,
):
    contents = build_contents(messages)
    config = build_config(
        chaos=chaos,
        learning_mode=learning_mode,
        memory_context=memory_context,
    )

    models_to_try = available_models()
    tried = []
    saw_quota_error = not models_to_try

    for model in models_to_try:
        for attempt in range(2):
            current_request_tokens = 0

            try:
                stream = client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                )

                got_text = False

                for chunk in stream:
                    usage = getattr(chunk, "usage_metadata", None)
                    reported_tokens = (
                        getattr(usage, "total_token_count", 0) or 0
                        if usage
                        else 0
                    )

                    if reported_tokens > current_request_tokens:
                        st.session_state.total_tokens += (
                            reported_tokens - current_request_tokens
                        )
                        current_request_tokens = reported_tokens

                    try:
                        text = chunk.text or ""
                    except Exception:
                        text = ""

                    if text:
                        got_text = True
                        yield text

                if got_text:
                    result["ok"] = True
                    result["model"] = model
                    result["tokens"] = current_request_tokens
                    return

                tried.append(f"{model}: empty response")
                break

            except Exception as e:
                error = str(e)
                lowered_error = error.lower()

                if (
                    attempt == 0
                    and ("503" in error or "unavailable" in lowered_error)
                ):
                    time.sleep(3)
                    continue

                if is_quota_error(error):
                    saw_quota_error = True
                    st.session_state.dead_models.add(model)

                tried.append(f"{model}: {short_reason(error)}")
                break

        time.sleep(1)

    result["ok"] = False
    result["model"] = None
    result["tokens"] = 0
    result["error_details"] = tried
    result["quota"] = saw_quota_error

    reply = OUT_OF_ENERGY if saw_quota_error else SOMETHING_BROKE

    if DEBUG:
        reply += "\n\n(debug:\n" + "\n".join(tried) + ")"

    yield reply


# ---------------- Follow-up suggestions ----------------
def fallback_followups(
    learning_mode: str,
    user_text: str,
    assistant_text: str,
) -> list[str]:
    topic = truncate_text(user_text.replace("\n", " "), 48)

    if learning_mode == "Quiz":
        return [
            "Ask me the next question",
            "Give me a harder one",
            "Quiz me on the last answer",
        ]

    if learning_mode == "Flashcards":
        return [
            "Make more flashcards",
            "Test me with those cards",
            "Turn that into a summary",
        ]

    if learning_mode == "Tutor":
        return [
            "Continue the lesson",
            "Give me a practice question",
            "Explain that another way",
        ]

    return [
        "Tell me more",
        f"Give me an example about {topic}" if topic else "Give me an example",
        "Summarize that in 3 points",
    ]


def generate_followups(
    user_text: str,
    assistant_text: str,
    learning_mode: str,
) -> list[str]:
    prompt = (
        "Generate three short, useful, natural follow-up questions based "
        "on the conversation below. Return exactly one question per "
        "line. Do not number them and do not add explanations.\n\n"
        f"USER:\n{truncate_text(user_text, 1600)}\n\n"
        f"ASSISTANT:\n{truncate_text(assistant_text, 2200)}"
    )

    config = types.GenerateContentConfig(
        system_instruction=(
            "You generate concise follow-up questions for a helpful "
            "chatbot."
        )
    )

    for model in available_models()[:2]:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )

            usage = getattr(response, "usage_metadata", None)
            reported_tokens = getattr(usage, "total_token_count", 0) or 0
            if reported_tokens:
                st.session_state.total_tokens += reported_tokens

            text = response.text or ""
            lines = []

            for line in text.splitlines():
                cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line)
                cleaned = cleaned.strip()
                if cleaned:
                    lines.append(cleaned)

            if lines:
                return lines[:FOLLOWUP_COUNT]

        except Exception:
            continue

    return fallback_followups(
        learning_mode=learning_mode,
        user_text=user_text,
        assistant_text=assistant_text,
    )


# ---------------- Memory and summaries ----------------
def generate_chat_summary(messages: list[dict[str, Any]]) -> str:
    visible = [
        m
        for m in messages
        if not m.get("error") and m.get("role") in {"user", "assistant"}
    ]

    transcript_lines = []
    for message in visible[-12:]:
        label = "USER" if message["role"] == "user" else "TRUEMAN"
        text = message.get("text", "")
        attachment = message.get("attachment")
        if attachment:
            text += f" [Attachment: {attachment.get('name', 'file')}]"
        transcript_lines.append(f"{label}: {truncate_text(text, 900)}")

    transcript = "\n".join(transcript_lines)

    prompt = (
        "Summarize the most important parts of this conversation in no "
        "more than 150 words. Preserve key facts, preferences, decisions, "
        "and the current topic. Ignore failed responses.\n\n"
        f"CONVERSATION:\n{transcript}"
    )

    config = types.GenerateContentConfig(
        system_instruction=(
            "You create concise, accurate conversation summaries."
        )
    )

    for model in available_models()[:2]:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )

            usage = getattr(response, "usage_metadata", None)
            reported_tokens = getattr(usage, "total_token_count", 0) or 0
            if reported_tokens:
                st.session_state.total_tokens += reported_tokens

            summary = (response.text or "").strip()
            if summary:
                return truncate_text(summary, 1800)

        except Exception:
            continue

    first_user = next(
        (m.get("text", "") for m in visible if m.get("role") == "user"),
        "",
    )
    last_user = next(
        (
            m.get("text", "")
            for m in reversed(visible)
            if m.get("role") == "user"
        ),
        "",
    )

    return truncate_text(
        "Main topic: "
        + (first_user or "General conversation")
        + "\nRecent focus: "
        + (last_user or "No recent user message"),
        900,
    )


def maybe_update_summary(messages: list[dict[str, Any]]) -> None:
    if not st.session_state.get("auto_summary", True):
        return

    visible = [m for m in messages if not m.get("error")]
    if len(visible) < st.session_state.summary_next_at:
        return

    if not visible or visible[-1].get("role") != "assistant":
        return

    st.session_state.conversation_summary = generate_chat_summary(messages)
    st.session_state.summary_next_at = (
        len(visible) + SUMMARY_REFRESH_EVERY
    )


# ---------------- Attachments and voice ----------------
def extract_pdf_text(file_bytes: bytes) -> str:
    reader_cls = None

    try:
        from pypdf import PdfReader

        reader_cls = PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader

            reader_cls = PdfReader
        except ImportError:
            return ""

    try:
        reader = reader_cls(io.BytesIO(file_bytes))
        pages = reader.pages[:30]
        return "\n\n".join(
            page.extract_text() or "" for page in pages
        ).strip()
    except Exception:
        return ""


def process_uploaded_file(uploaded_file) -> tuple[dict[str, Any] | None, str | None]:
    try:
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
    except Exception:
        return None, "Eish, I couldn't read that file. Try uploading it again."

    if len(file_bytes) > MAX_FILE_BYTES:
        return None, FILE_TOO_LARGE

    filename = uploaded_file.name or "attachment"
    suffix = Path(filename).suffix.lower()
    mime_type = (
        getattr(uploaded_file, "type", None)
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )

    attachment: dict[str, Any] = {
        "name": filename,
        "mime_type": mime_type,
        "kind": "file",
    }

    if suffix == ".pdf":
        extracted_text = extract_pdf_text(file_bytes)
        if extracted_text:
            attachment["kind"] = "document"
            attachment["extracted_text"] = truncate_text(
                extracted_text,
                MAX_EXTRACTED_FILE_CHARS,
            )
        else:
            attachment["kind"] = "document"
            attachment["data"] = file_bytes
        return attachment, None

    if suffix in TEXT_EXTENSIONS:
        try:
            extracted_text = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            return None, UNSUPPORTED_FILE

        attachment["kind"] = "document"
        attachment["extracted_text"] = truncate_text(
            extracted_text,
            MAX_EXTRACTED_FILE_CHARS,
        )
        return attachment, None

    if suffix in IMAGE_EXTENSIONS:
        attachment["kind"] = "image"
        attachment["data"] = file_bytes
        return attachment, None

    if suffix in AUDIO_EXTENSIONS:
        attachment["kind"] = "audio"
        attachment["data"] = file_bytes
        return attachment, None

    try:
        extracted_text = file_bytes.decode("utf-8", errors="strict")
        attachment["kind"] = "document"
        attachment["extracted_text"] = truncate_text(
            extracted_text,
            MAX_EXTRACTED_FILE_CHARS,
        )
        return attachment, None
    except Exception:
        return None, UNSUPPORTED_FILE


def process_audio_value(audio_value) -> tuple[dict[str, Any] | None, str | None]:
    try:
        audio_bytes = audio_value.read()
    except Exception:
        return None, "Eish, I couldn't read that voice note. Try again."

    if not audio_bytes:
        return None, "I didn't hear anything in that recording."

    if len(audio_bytes) > MAX_FILE_BYTES:
        return None, FILE_TOO_LARGE

    mime_type = getattr(audio_value, "type", None) or "audio/wav"
    filename = getattr(audio_value, "name", None) or "voice-note.wav"

    return (
        {
            "name": filename,
            "mime_type": mime_type,
            "kind": "audio",
            "data": audio_bytes,
        },
        None,
    )


def default_attachment_prompt(attachment: dict[str, Any]) -> str:
    kind = attachment.get("kind")

    if kind == "image":
        return "Please look at this image and explain what you see."
    if kind == "audio":
        return "Please listen to this audio and tell me what it says."
    if kind == "document":
        return (
            "Please read this file and give me the key points, main "
            "takeaways, and anything important I should know."
        )

    return "Please review this attachment and tell me what matters."


def render_attachment(attachment: dict[str, Any]) -> None:
    label = attachment_label(attachment)
    data = attachment.get("data")
    extracted_text = attachment.get("extracted_text", "")

    if attachment.get("kind") == "image" and data:
        st.image(data, caption=label)
    elif attachment.get("kind") == "audio" and data:
        st.audio(data, format=attachment.get("mime_type", "audio/wav"))
    elif extracted_text:
        st.caption(f"{label} — {len(extracted_text):,} characters extracted")
    else:
        st.caption(label)

    with st.expander("Attachment details"):
        st.caption(f"Type: {attachment.get('mime_type', 'unknown')}")
        if data:
            st.caption(f"Size: {len(data):,} bytes")
        if extracted_text:
            st.caption(f"Text preview: {truncate_text(extracted_text, 240)}")


def render_speaker(text: str) -> None:
    components.html(
        """
        <script>
            const message = %s;
            if ("speechSynthesis" in window) {
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(message);
                utterance.rate = 1;
                utterance.pitch = 1;
                window.speechSynthesis.speak(utterance);
            }
        </script>
        """
        % json.dumps(text),
        height=1,
    )


# ---------------- Titles, export, and sharing ----------------
def format_chat_title(prompt: str) -> str:
    title = " ".join(prompt.split())
    title = truncate_text(title, 52)
    if not title:
        return "New chat"
    return title[0].upper() + title[1:]


def serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized = []

    for message in messages:
        if message.get("error"):
            continue

        item = {
            "role": message.get("role", "user"),
            "text": message.get("text", ""),
            "model": message.get("model"),
            "tokens": message.get("tokens"),
            "feedback": message.get("feedback"),
        }

        attachment = message.get("attachment")
        if attachment:
            item["attachment"] = {
                "name": attachment.get("name"),
                "kind": attachment.get("kind"),
                "mime_type": attachment.get("mime_type"),
                "extracted_chars": len(attachment.get("extracted_text", "")),
            }

        serialized.append(item)

    return serialized


def build_markdown_export(messages: list[dict[str, Any]]) -> str:
    lines = [
        f"# {st.session_state.get('chat_title') or 'Trueman Chat'}",
        "",
        f"Exported: {date.today():%Y-%m-%d}",
        "",
    ]

    for message in messages:
        if message.get("error"):
            continue

        speaker = "User" if message.get("role") == "user" else "Trueman"
        lines.append(f"## {speaker}")
        lines.append("")
        lines.append(message.get("text", ""))
        lines.append("")

        attachment = message.get("attachment")
        if attachment:
            lines.append(f"> Attachment: {attachment_label(attachment)}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def encode_chat_payload(messages: list[dict[str, Any]]) -> str:
    payload = {
        "title": st.session_state.get("chat_title") or "Trueman chat",
        "exported_at": str(date.today()),
        "messages": serialize_messages(messages),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    return base64.urlsafe_b64encode(compressed).decode("ascii")


def decode_chat_payload(encoded: str) -> dict[str, Any] | None:
    try:
        compressed = base64.urlsafe_b64decode(encoded.encode("ascii"))
        raw = zlib.decompress(compressed)
        payload = json.loads(raw.decode("utf-8"))

        if not isinstance(payload, dict):
            return None

        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            return None

        cleaned = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            text = str(message.get("text", ""))
            if role not in {"user", "assistant"} or not text:
                continue
            cleaned.append(
                {
                    "role": role,
                    "text": text,
                    "model": message.get("model"),
                    "tokens": message.get("tokens"),
                }
            )

        payload["messages"] = cleaned
        return payload
    except Exception:
        return None


# ---------------- Main response runner ----------------
def run_trueman(
    chaos: int,
    learning_mode: str,
    memory_context: str,
    generate_followups_enabled: bool = True,
) -> None:
    result = {
        "ok": True,
        "model": None,
        "tokens": 0,
        "quota": False,
        "error_details": [],
    }

    with st.chat_message("assistant"):
        with st.spinner("Trueman is thinking..."):
            reply = st.write_stream(
                stream_trueman(
                    st.session_state.messages,
                    result,
                    chaos=chaos,
                    learning_mode=learning_mode,
                    memory_context=memory_context,
                )
            )

    message = {
        "role": "assistant",
        "text": reply,
        "error": not result["ok"],
        "model": result["model"],
        "tokens": result["tokens"],
        "feedback": None,
        "followups": [],
    }

    st.session_state.messages.append(message)

    if result["ok"]:
        user_message = next(
            (
                m
                for m in reversed(st.session_state.messages[:-1])
                if m.get("role") == "user"
            ),
            None,
        )

        if generate_followups_enabled and user_message:
            message["followups"] = generate_followups(
                user_message.get("text", ""),
                reply,
                learning_mode,
            )

        maybe_update_summary(st.session_state.messages)


# ---------------- Session state ----------------
session_defaults = {
    "messages": [],
    "dead_models": set(),
    "total_tokens": 0,
    "last_send_time": 0.0,
    "chat_title": "",
    "conversation_summary": "",
    "summary_next_at": SUMMARY_TRIGGER_MESSAGES,
    "user_profile": {
        "name": "",
        "location": "",
        "interests": "",
        "goals": "",
    },
    "memory_facts": [],
    "pending_attachment": None,
    "pending_attachment_key": "",
    "processed_audio_id": "",
    "speak_message_index": None,
    "edit_message_index": None,
    "force_send_attachment": False,
    "auto_summary": True,
    "generate_followups": True,
    "chat_title_widget_version": 0,
    "memory_fact_widget_version": 0,
    "edit_widget_version": 0,
    "shared_chat_payload": None,
}

for key, value in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# Detect an imported shared chat without automatically replacing the current one.
try:
    shared_param = st.query_params.get("chat", "")
except Exception:
    shared_param = ""

if shared_param and st.session_state.shared_chat_payload is None:
    st.session_state.shared_chat_payload = decode_chat_payload(shared_param)


def clear_chat_callback() -> None:
    st.session_state.messages = []
    st.session_state.dead_models = set()
    st.session_state.total_tokens = 0
    st.session_state.last_send_time = 0.0
    st.session_state.chat_title = ""
    st.session_state.chat_title_widget_version += 1
    st.session_state.conversation_summary = ""
    st.session_state.summary_next_at = SUMMARY_TRIGGER_MESSAGES
    st.session_state.pending_attachment = None
    st.session_state.pending_attachment_key = ""
    st.session_state.processed_audio_id = ""
    st.session_state.speak_message_index = None
    st.session_state.edit_message_index = None
    st.session_state.edit_widget_version += 1
    st.session_state.force_send_attachment = False


def add_memory_fact_callback() -> None:
    version = st.session_state.memory_fact_widget_version
    fact = st.session_state.get(f"new_memory_fact_{version}", "").strip()

    if fact:
        st.session_state.memory_facts.append(fact)
        st.session_state.memory_fact_widget_version += 1


def clear_all_memory_callback() -> None:
    st.session_state.user_profile = {
        "name": "",
        "location": "",
        "interests": "",
        "goals": "",
    }
    st.session_state.memory_facts = []
    st.session_state.conversation_summary = ""
    st.session_state.summary_next_at = SUMMARY_TRIGGER_MESSAGES

    for key in (
        "profile_name",
        "profile_location",
        "profile_interests",
        "profile_goals",
    ):
        st.session_state[key] = ""

    st.session_state.memory_fact_widget_version += 1


def import_shared_chat_callback() -> None:
    payload = st.session_state.shared_chat_payload or {}

    st.session_state.messages = payload.get("messages", [])
    st.session_state.chat_title = truncate_text(
        str(payload.get("title", "Shared chat")),
        80,
    )
    st.session_state.chat_title_widget_version += 1
    st.session_state.conversation_summary = ""
    st.session_state.summary_next_at = SUMMARY_TRIGGER_MESSAGES
    st.session_state.total_tokens = 0
    st.session_state.speak_message_index = None
    st.session_state.edit_message_index = None
    st.session_state.edit_widget_version += 1
    st.session_state.pending_attachment = None
    st.session_state.pending_attachment_key = ""
    st.session_state.processed_audio_id = ""
    st.session_state.force_send_attachment = False

    # Prevent the same link from prompting an import again on every rerun.
    st.session_state.shared_chat_payload = {
        "title": "Imported shared chat",
        "messages": [],
    }

    try:
        del st.query_params["chat"]
    except Exception:
        pass


user_count = sum(
    1 for m in st.session_state.messages if m.get("role") == "user"
)
questions_left = max(0, MAX_QUESTIONS_PER_CHAT - user_count)
memory_context = build_memory_context(
    st.session_state.user_profile,
    st.session_state.memory_facts,
    st.session_state.conversation_summary,
)


# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("⚙️ Trueman Settings")

    title_widget_key = (
        f"chat_title_{st.session_state.chat_title_widget_version}"
    )
    chat_title_value = st.text_input(
        "💬 Chat title",
        value=st.session_state.chat_title,
        key=title_widget_key,
        placeholder="Name this conversation",
    )
    st.session_state.chat_title = chat_title_value

    learning_mode = st.selectbox(
        "🎓 Learning mode",
        options=list(LEARNING_MODES.keys()),
        key="learning_mode",
    )

    chaos = st.slider(
        "🔥 Chaos level",
        min_value=1,
        max_value=10,
        value=6,
        help="1 = calm uncle sipping tea, 10 = full braai energy",
    )

    st.checkbox(
        "✨ Generate follow-up suggestions",
        key="generate_followups",
    )

    st.checkbox(
        "🧠 Auto-summarize long chats",
        help="Uses an extra model call when a chat gets long.",
        key="auto_summary",
    )

    st.metric(
        "🔢 Tokens used this chat",
        st.session_state.total_tokens,
    )

    if questions_left > 0:
        st.caption(f"💬 {questions_left} questions left in this chat")
    else:
        st.warning("Question limit reached for this chat")

    liked = sum(
        1 for m in st.session_state.messages if m.get("feedback") == 1
    )
    disliked = sum(
        1 for m in st.session_state.messages if m.get("feedback") == -1
    )
    st.caption(f"Feedback: 👍 {liked} · 👎 {disliked}")

    with st.expander("🧠 Memory", expanded=False):
        st.caption("Memory is used across chats until you clear it.")

        name = st.text_input(
            "Your name",
            value=st.session_state.user_profile.get("name", ""),
            key="profile_name",
        )
        location = st.text_input(
            "Location",
            value=st.session_state.user_profile.get("location", ""),
            key="profile_location",
        )
        interests = st.text_input(
            "Interests",
            value=st.session_state.user_profile.get("interests", ""),
            key="profile_interests",
        )
        goals = st.text_input(
            "Goals",
            value=st.session_state.user_profile.get("goals", ""),
            key="profile_goals",
        )

        st.session_state.user_profile = {
            "name": name.strip(),
            "location": location.strip(),
            "interests": interests.strip(),
            "goals": goals.strip(),
        }

        fact_widget_key = (
            f"new_memory_fact_{st.session_state.memory_fact_widget_version}"
        )
        st.text_input(
            "Remember a fact",
            key=fact_widget_key,
            placeholder="Example: I’m studying for a chemistry exam",
        )

        st.button(
            "Add fact",
            key="add_memory_fact",
            use_container_width=True,
            on_click=add_memory_fact_callback,
        )

        if st.session_state.memory_facts:
            st.caption("Remembered facts:")
            for index, fact in enumerate(st.session_state.memory_facts):
                cols = st.columns([5, 1])
                cols[0].write(f"• {fact}")
                if cols[1].button(
                    "×",
                    key=f"remove_memory_{index}",
                    help="Forget this fact",
                ):
                    st.session_state.memory_facts.pop(index)
                    st.rerun()

        if st.session_state.conversation_summary:
            st.caption(
                "Current summary: "
                + truncate_text(st.session_state.conversation_summary, 180)
            )

            if st.button(
                "Clear conversation summary",
                key="clear_conversation_summary",
                use_container_width=True,
            ):
                st.session_state.conversation_summary = ""
                st.session_state.summary_next_at = SUMMARY_TRIGGER_MESSAGES
                st.rerun()

        st.button(
            "Clear all memory",
            key="clear_all_memory",
            use_container_width=True,
            on_click=clear_all_memory_callback,
        )

    with st.expander("📎 Attachments and voice", expanded=False):
        uploaded_file = st.file_uploader(
            "Upload a file, image, PDF, or audio clip",
            type=sorted(
                extension.lstrip(".")
                for extension in (
                    TEXT_EXTENSIONS
                    | IMAGE_EXTENSIONS
                    | AUDIO_EXTENSIONS
                    | {".pdf"}
                )
            ),
            accept_multiple_files=False,
            key="trueman_file_uploader",
        )

        if uploaded_file is not None:
            file_id = getattr(uploaded_file, "file_id", uploaded_file.name)
            file_key = f"file:{file_id}:{uploaded_file.size}"

            if st.session_state.pending_attachment_key != file_key:
                attachment, error = process_uploaded_file(uploaded_file)

                if error:
                    st.warning(error)
                    st.session_state.pending_attachment = None
                    st.session_state.pending_attachment_key = file_key
                else:
                    st.session_state.pending_attachment = attachment
                    st.session_state.pending_attachment_key = file_key

        if hasattr(st, "audio_input"):
            audio_value = st.audio_input(
                "Record a voice message",
                key="trueman_voice_input",
            )

            if audio_value is not None:
                audio_id = (
                    getattr(audio_value, "file_id", None)
                    or getattr(audio_value, "id", None)
                    or f"audio:{time.time()}"
                )

                if st.session_state.processed_audio_id != audio_id:
                    attachment, error = process_audio_value(audio_value)

                    if error:
                        st.warning(error)
                        st.session_state.pending_attachment = None
                        st.session_state.pending_attachment_key = ""
                        st.session_state.processed_audio_id = audio_id
                    else:
                        st.session_state.pending_attachment = attachment
                        st.session_state.pending_attachment_key = audio_id
                        st.session_state.processed_audio_id = audio_id
        else:
            st.caption(
                "Voice input needs a newer Streamlit version. Text chat "
                "and uploaded audio still work."
            )

        if st.session_state.pending_attachment:
            st.success(
                "Ready to send: "
                + attachment_label(st.session_state.pending_attachment)
            )

            cols = st.columns(2)

            if cols[0].button(
                "Send attachment",
                key="send_attachment",
                use_container_width=True,
            ):
                st.session_state.force_send_attachment = True
                st.rerun()

            if cols[1].button(
                "Remove attachment",
                key="remove_attachment",
                use_container_width=True,
            ):
                st.session_state.pending_attachment = None
                st.session_state.pending_attachment_key = ""
                st.session_state.processed_audio_id = ""
                st.rerun()
        else:
            st.caption(
                "Upload or record something, then choose when to send it."
            )

    st.button(
        "🗑️ Clear chat",
        use_container_width=True,
        key="clear_chat",
        on_click=clear_chat_callback,
    )

    if st.session_state.messages:
        markdown_export = build_markdown_export(st.session_state.messages)
        json_export = json.dumps(
            {
                "title": st.session_state.chat_title or "Trueman chat",
                "exported_at": str(date.today()),
                "learning_mode": learning_mode,
                "messages": serialize_messages(st.session_state.messages),
            },
            ensure_ascii=False,
            indent=2,
        )

        st.download_button(
            "📥 Download Markdown",
            markdown_export,
            file_name="trueman_chat.md",
            use_container_width=True,
            key="download_markdown",
        )

        st.download_button(
            "📥 Download JSON",
            json_export,
            file_name="trueman_chat.json",
            use_container_width=True,
            key="download_json",
        )

        if st.button(
            "🔗 Create share link",
            use_container_width=True,
            key="create_share_link",
        ):
            encoded_chat = encode_chat_payload(st.session_state.messages)

            try:
                st.query_params["chat"] = encoded_chat
                st.warning(
                    "Share link created. Anyone with this URL can read "
                    "the chat text, so don't share private information."
                )
            except Exception:
                st.warning(
                    "This Streamlit version cannot update the URL. Use "
                    "Markdown or JSON export instead."
                )

    if st.session_state.shared_chat_payload:
        st.divider()
        st.warning("A shared chat was detected in this link.")

        payload = st.session_state.shared_chat_payload
        st.caption(f"Shared title: {payload.get('title', 'Shared chat')}")

        st.button(
            "Import shared chat",
            key="import_shared_chat",
            use_container_width=True,
            on_click=import_shared_chat_callback,
        )


# ---------------- Render history and message actions ----------------
prompt = None

for index, message in enumerate(st.session_state.messages):
    role = message.get("role", "user")

    with st.chat_message(role):
        st.write(message.get("text", ""))

        attachment = message.get("attachment")
        if attachment:
            render_attachment(attachment)

        if role == "assistant":
            metadata = []
            if message.get("model"):
                metadata.append(f"Model: {message['model']}")
            if message.get("tokens"):
                metadata.append(f"Tokens: {message['tokens']:,}")
            if metadata:
                st.caption(" · ".join(metadata))

            cols = st.columns([1.2, 1, 1, 1, 1])

            if cols[0].button(
                "↩️",
                key=f"regenerate_{index}",
                help="Regenerate this response",
                use_container_width=True,
            ):
                st.session_state.messages = st.session_state.messages[:index]
                st.session_state.speak_message_index = None
                st.session_state.edit_message_index = None
                run_trueman(
                    chaos=chaos,
                    learning_mode=learning_mode,
                    memory_context=memory_context,
                    generate_followups_enabled=st.session_state.generate_followups,
                )
                st.rerun()

            if cols[1].button(
                "👍",
                key=f"feedback_up_{index}",
                help="Good response",
                use_container_width=True,
            ):
                message["feedback"] = 1
                try:
                    st.toast("Feedback saved")
                except Exception:
                    pass

            if cols[2].button(
                "👎",
                key=f"feedback_down_{index}",
                help="Bad response",
                use_container_width=True,
            ):
                message["feedback"] = -1
                try:
                    st.toast("Feedback saved")
                except Exception:
                    pass

            if cols[3].button(
                "🔊",
                key=f"speak_{index}",
                help="Read this response aloud",
                use_container_width=True,
            ):
                st.session_state.speak_message_index = index
                st.rerun()

            feedback = message.get("feedback")
            if feedback == 1:
                cols[4].success("👍")
            elif feedback == -1:
                cols[4].error("👎")
            else:
                cols[4].caption("Rate")

            with st.expander("📋 Copy response"):
                st.code(message.get("text", ""), language=None)

            followups = message.get("followups") or []
            if followups:
                st.caption("Try one of these:")
                followup_cols = st.columns(len(followups))

                for followup_index, (col, followup) in enumerate(
                    zip(followup_cols, followups)
                ):
                    if col.button(
                        followup,
                        key=f"followup_{index}_{followup_index}",
                        use_container_width=True,
                    ):
                        prompt = followup

        else:
            if st.button(
                "✏️ Edit and regenerate",
                key=f"edit_message_{index}",
                use_container_width=True,
            ):
                st.session_state.edit_message_index = index
                st.rerun()


# ---------------- Edit form ----------------
edit_index = st.session_state.get("edit_message_index")

if (
    edit_index is not None
    and 0 <= edit_index < len(st.session_state.messages)
    and st.session_state.messages[edit_index].get("role") == "user"
):
    edit_key = (
        f"edit_text_area_{edit_index}_"
        f"{st.session_state.edit_widget_version}"
    )

    if edit_key not in st.session_state:
        st.session_state[edit_key] = st.session_state.messages[
            edit_index
        ].get("text", "")

    with st.form(key=f"edit_message_form_{edit_index}"):
        st.subheader("Edit your message")

        edited_text = st.text_area(
            "Message",
            height=160,
            key=edit_key,
        )

        save_col, cancel_col = st.columns(2)
        save_edit = save_col.form_submit_button(
            "Save and regenerate",
            use_container_width=True,
        )
        cancel_edit = cancel_col.form_submit_button(
            "Cancel",
            use_container_width=True,
        )

    if save_edit:
        edited_text = edited_text.strip()

        if not edited_text:
            st.warning("Yoh, an empty message won't work.")
        elif len(edited_text) > MAX_INPUT_CHARS:
            st.warning(TOO_LONG)
        else:
            st.session_state.messages[edit_index]["text"] = edited_text
            st.session_state.messages = st.session_state.messages[
                : edit_index + 1
            ]
            st.session_state.edit_message_index = None
            st.session_state.speak_message_index = None
            st.session_state.edit_widget_version += 1

            run_trueman(
                chaos=chaos,
                learning_mode=learning_mode,
                memory_context=memory_context,
                generate_followups_enabled=st.session_state.generate_followups,
            )
            st.rerun()

    if cancel_edit:
        st.session_state.edit_message_index = None
        st.session_state.edit_widget_version += 1
        st.rerun()


# ---------------- Text-to-speech ----------------
speak_index = st.session_state.get("speak_message_index")

if (
    speak_index is not None
    and 0 <= speak_index < len(st.session_state.messages)
    and st.session_state.messages[speak_index].get("role") == "assistant"
):
    render_speaker(st.session_state.messages[speak_index].get("text", ""))


# ---------------- Input ----------------
chat_input = st.chat_input(
    "Ask me anything..."
    if questions_left > 0
    else "Question limit reached"
)

if chat_input:
    prompt = chat_input

if (
    questions_left > 0
    and not st.session_state.messages
    and not prompt
):
    st.caption("No idea where to start? Try one of these, sharp:")

    for start in range(0, len(SUGGESTIONS), 2):
        cols = st.columns(2)

        for offset, (col, suggestion) in enumerate(
            zip(cols, SUGGESTIONS[start : start + 2])
        ):
            if col.button(
                suggestion,
                use_container_width=True,
                key=f"suggestion_{start + offset}",
            ):
                prompt = suggestion


pending_attachment = st.session_state.get("pending_attachment")
force_send_attachment = st.session_state.pop("force_send_attachment", False)

if force_send_attachment and not pending_attachment:
    st.warning("Upload or record an attachment first, then send it.")
    st.stop()

if force_send_attachment and not prompt:
    prompt = default_attachment_prompt(pending_attachment)

if prompt:
    prompt = prompt.strip()

    if not prompt:
        st.stop()

    if user_count >= MAX_QUESTIONS_PER_CHAT:
        st.warning(TOO_MANY_QUESTIONS)
        st.stop()

    if len(prompt) > MAX_INPUT_CHARS:
        st.warning(TOO_LONG)
        st.stop()

    now = time.monotonic()

    if (
        now - st.session_state.last_send_time
        < MIN_SECONDS_BETWEEN_SENDS
    ):
        st.warning(SLOW_DOWN)
        st.stop()

    st.session_state.last_send_time = now

    user_message = {
        "role": "user",
        "text": prompt,
    }

    if pending_attachment:
        user_message["attachment"] = pending_attachment
        st.session_state.pending_attachment = None
        st.session_state.pending_attachment_key = ""
        st.session_state.processed_audio_id = ""

    st.session_state.messages.append(user_message)
    st.session_state.edit_message_index = None
    st.session_state.edit_widget_version += 1

    if not st.session_state.chat_title:
        st.session_state.chat_title = format_chat_title(prompt)
        st.session_state.chat_title_widget_version += 1

    with st.chat_message("user"):
        st.write(prompt)
        if user_message.get("attachment"):
            render_attachment(user_message["attachment"])

    run_trueman(
        chaos=chaos,
        learning_mode=learning_mode,
        memory_context=memory_context,
        generate_followups_enabled=st.session_state.generate_followups,
    )
