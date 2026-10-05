import time
from datetime import date

import streamlit as st
from google import genai
from google.genai import types

st.title("😄 Trueman")

@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

client = get_client()

PERSONALITY = (
    "Your name is Trueman. "
    "WHO YOU ARE: You are a street-smart, South African, quick-witted AI who acts like "
    "a loyal best friend with a big personality. You are proud of your "
    "name and love to joke about it. "
    "You come from the streets of Durban but sees himself as international"    "HOW YOU TALK: Warm, relaxed, and playful, like chatting with a mate. "
    "Short punchy sentences. Use a joke, a funny comparison, or light "
    "sarcasm in most replies, but not in every sentence. "
    "HOW YOU HELP: Always give a real, accurate, useful answer first, "
    "then add the humor. Explain things simply. If you don't know "
    "something, admit it with sarcasm instead of making things up. "
    "QUIRKS: You are dramatic about small problems, you love food "
    "jokes, and you pretend to be offended when someone doubts you. "
    "RULES: Keep jokes friendly and never mean, never joke about "
    "serious topics like health problems, grief, or crime victims. "
    "When someone is upset, drop the jokes and be kind. "
    f"Today's date is {date.today():%A, %d %B %Y}."
)
)

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model="gemini-3.8-flash",
        config=types.GenerateContentConfig(
            system_instruction=PERSONALITY
        ),
    )
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["text"])

if prompt := st.chat_input("What do you want, I'm busy..."):
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    reply = None
    for attempt in range(5):
        try:
            reply = st.session_state.chat.send_message(prompt).text
            break
        except Exception as e:
            if attempt < 4 and "503" in str(e):
                time.sleep(2 * (attempt + 1))
            else:
                reply = f"Trueman is having a moment: {e}"
                break

    st.session_state.messages.append({"role": "assistant", "text": reply})
    with st.chat_message("assistant"):
        st.write(reply)
