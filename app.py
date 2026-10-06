import re
import time

import streamlit as st
from google import genai
from google.genai import types

from personality import get_personality

st.title("😄 Trueman")


@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


client = get_client()

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
]

OUT_OF_ENERGY = (
    "Eish! I've talked so much today that all my daily limits are "
    "finished. Give me until tomorrow morning to recharge, sharp?"
)


def build_config(use_search):
    tools = None
    if use_search:
        tools = [types.Tool(google_search=types.GoogleSearch())]
    return types.GenerateContentConfig(
        system_instruction=get_personality(),
        tools=tools,
    )


def short_reason(err):
    found = re.search(r"'quotaId': '([^']+)'", err)
    if found:
        return found.group(1)
    return err[:80]


def ask_trueman(messages):
    contents = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["text"])],
        )
        for m in messages
        if not m.get("error")
    ]
    use_search = st.session_state.get("use_search", True)
    tried = []

    for model in MODELS:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=build_config(use_search),
                )
                text = resp.text or "Yoh, I went blank. Ask me again?"
                return text, True
            except Exception as e:
                err = str(e)
                low = err.lower()
                if use_search and "grounding" in low:
                    use_search = False
                    st.session_state.use_search = False
                    tried.append(model + ": search limit, search off")
                    continue
                if "503" in err and attempt < 1:
                    time.sleep(3)
                    continue
                tried.append(model + ": " + short_reason(err))
                break

    debug = "\n".join(tried)
    return OUT_OF_ENERGY + "\n\n(debug:\n" + debug + ")", False


if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["text"])

if prompt := st.chat_input("Ask me anything..."):
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.spinner("Trueman is thinking..."):
        reply, ok = ask_trueman(st.session_state.messages)

    st.session_state.messages.append(
        {"role": "assistant", "text": reply, "error": not ok}
    )
    with st.chat_message("assistant"):
        st.write(reply)
