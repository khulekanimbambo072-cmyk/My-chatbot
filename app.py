import time
from datetime import date

import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Trueman", page_icon="\U0001F604")

st.title("\U0001F604 Trueman")

# ---------------- Settings ----------------
USE_SEARCH = False          # needs a paid API key to work
DEBUG = False

MAX_INPUT_CHARS = 2000          # guardrail: one message can't be a novel
MAX_QUESTIONS_PER_CHAT = 20     # rate limit per session
MIN_SECONDS_BETWEEN_SENDS = 3   # anti-spam: min gap between messages
CONTEXT_CHAR_LIMIT = 8000       # trim oldest messages beyond this

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

SUGGESTIONS = [
    "Explain black holes like I'm 10",
    "Help me write a CV that slaps",
    "Teach me 5 Zulu phrases",
    "Is it ever okay to put pineapple on pizza?",
]

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
    "Eish, hang on bra! Even my genius needs 3 seconds between "
    "questions. Try again now, sharp?"
)


def chaos_instruction(level):
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


def get_personality(can_search=False, chaos=6):
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
    text += chaos_instruction(chaos)
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


@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


try:
    client = get_client()
except Exception as e:
    st.error(f"Couldn't load the Gemini client: {e}")
    st.info("Check that GEMINI_API_KEY is set in your Streamlit secrets.")
    st.stop()


def build_config(chaos):
    tools = None
    if USE_SEARCH:
        tools = [types.Tool(google_search=types.GoogleSearch())]
    return types.GenerateContentConfig(
        system_instruction=get_personality(USE_SEARCH, chaos),
        tools=tools,
    )


def is_quota_error(err):
    e = err.lower()
    return "quota" in e or "429" in e or "rate limit" in e


def short_reason(err):
    low = err.lower()
    start = low.find("quota")
    if start < 0:
        start = 0
    return err[start:start + 160]


def trim_messages(messages):
    """Drop the oldest messages if the conversation exceeds the
    context limit. Always keeps at least the last 2 exchanges."""
    kept = [m for m in messages if not m.get("error")]
    total = sum(len(m["text"]) for m in kept)
    i = 0
    while total > CONTEXT_CHAR_LIMIT and i < len(kept) - 4:
        total -= len(kept[i]["text"])
        i += 1
    return kept[i:]


def build_contents(messages):
    return [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["text"])],
        )
        for m in trim_messages(messages)
    ]


def stream_trueman(messages, result, chaos):
    """Yield text chunks as they arrive; flip result['ok'] on failure.
    Models that died of quota are remembered and skipped this session."""
    contents = build_contents(messages)
    tried = []
    saw_quota_error = False
    token_baseline = st.session_state.total_tokens
    req_tokens = 0

    for model in MODELS:
        if model in st.session_state.dead_models:
            continue
        for attempt in range(2):
            try:
                stream = client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=build_config(chaos),
                )
                got_text = False
                for chunk in stream:
                    um = getattr(chunk, "usage_metadata", None)
                    if um and um.total_token_count:
                        req_tokens = um.total_token_count
                        st.session_state.total_tokens = (
                            token_baseline + req_tokens
                        )
                    try:
                        t = chunk.text or ""
                    except Exception:
                        t = ""  # chunk with no text part (e.g. safety)
                    if t:
                        got_text = True
                        yield t
                if got_text:
                    result["ok"] = True
                    return
                tried.append(model + ": empty response")
                break
            except Exception as e:
                err = str(e)
                if "503" in err and attempt < 1:
                    time.sleep(3)
                    continue
                if is_quota_error(err):
                    saw_quota_error = True
                    st.session_state.dead_models.add(model)
                tried.append(model + ": " + short_reason(err))
                break
        time.sleep(1)

    result["ok"] = False
    reply = OUT_OF_ENERGY if saw_quota_error else SOMETHING_BROKE
    if DEBUG:
        reply += "\n\n(debug:\n" + "\n".join(tried) + ")"
    yield reply


def run_trueman(chaos):
    result = {"ok": True}
    with st.chat_message("assistant"):
        with st.spinner("Trueman is thinking..."):
            reply = st.write_stream(
                stream_trueman(st.session_state.messages, result, chaos)
            )
    st.session_state.messages.append(
        {"role": "assistant", "text": reply, "error": not result["ok"]}
    )


# ---------------- Session state ----------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "dead_models" not in st.session_state:
    st.session_state.dead_models = set()
if "total_tokens" not in st.session_state:
    st.session_state.total_tokens = 0
if "last_send_time" not in st.session_state:
    st.session_state.last_send_time = 0.0

user_count = sum(1 for m in st.session_state.messages if m["role"] == "user")
questions_left = MAX_QUESTIONS_PER_CHAT - user_count

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("⚙️ Trueman Settings")
    chaos = st.slider(
        "🔥 Chaos level", 1, 10, 6,
        help="1 = calm uncle sipping tea, 10 = full braai energy",
    )
    st.metric("🔢 Tokens used (this session)", st.session_state.total_tokens)
    if questions_left > 0:
        st.caption(f"💬 {questions_left} questions left in this chat")
    else:
        st.warning("Question limit reached for this chat")

    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.dead_models = set()
        st.rerun()

    chat_export = "\n\n".join(
        f"{m['role'].upper()}: {m['text']}"
        for m in st.session_state.messages
    )
    st.download_button(
        "📥 Download chat",
        chat_export or "(Trueman chat - empty)",
        file_name="trueman_chat.txt",
        disabled=not st.session_state.messages,
        use_container_width=True,
    )

# ---------------- Render history ----------------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["text"])

# ---------------- Retry button ----------------
if st.session_state.messages and st.session_state.messages[-1].get("error"):
    if st.button("🔄 Try again"):
        st.session_state.messages.pop()
        run_trueman(chaos)
        st.rerun()

# ---------------- Input ----------------
prompt = st.chat_input("Ask me anything...")

if not st.session_state.messages and not prompt:
    st.caption("No idea where to start? Try one of these, sharp:")
    cols = st.columns(2)
    for col, q in zip(cols, SUGGESTIONS):
        if col.button(q, use_container_width=True):
            prompt = q

if prompt:
    if len(prompt) > MAX_INPUT_CHARS:
        st.warning(TOO_LONG)
        st.stop()
    now = time.time()
    if now - st.session_state.last_send_time < MIN_SECONDS_BETWEEN_SENDS:
        st.warning(SLOW_DOWN)
        st.stop()
    if user_count >= MAX_QUESTIONS_PER_CHAT:
        st.warning(TOO_MANY_QUESTIONS)
        st.stop()

    st.session_state.last_send_time = now
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    run_trueman(chaos)
