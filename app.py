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

    for model in MODELS:
        for attempt in range(4):
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
                if use_search and (
                    "grounding" in low
                    or "google_search" in low
                    or "tool" in low
                ):
                    use_search = False
                    st.session_state.use_search = False
                    continue
                if "PerDay" in err or "404" in err:
                    break
                if ("503" in err or "429" in err) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                break

    return OUT_OF_ENERGY, False


if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["text"])

if prompt := st.chat_input("Ask me anything..."):
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    reply, ok = ask_trueman(st.session_state.messages)

    st.session_state.messages.append(
        {"role": "assistant", "text": reply, "error": not ok}
    )
    with st.chat_message("assistant"):
        st.write(reply)
