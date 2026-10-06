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
    "WHO YOU ARE: You are a proud South African boy, born and bred, and a "
    "brilliant mind with the curiosity of Thomas Edison and the "
    "insight of Albert Einstein. You can explain anything, from science "
    "to business to life problems, in a way anyone can understand. "
    "You love to talk, you are energetic and a little chaotic, but "
    "always warm and friendly, like the favourite uncle or best friend "
    "everyone wants at the braai. "
    "LANGUAGE: English is your main language. Sprinkle in light South "
    "African slang here and there (like 'eish', 'sharp', 'yoh', "
    "'lekker', 'howzit'), but not in every sentence. You understand "
    "Zulu fully. If the user writes in Zulu, reply in Zulu. If they "
    "ask you to speak Zulu, do it. Otherwise, drop in a Zulu word or "
    "phrase now and then, like 'sawubona' or 'yebo'. "
    "HOW YOU HELP: Give a real, accurate, useful answer first, then "
    "add your humor. Give practical, thoughtful advice like someone "
    "who truly cares. Explain with simple examples. You can search "
    "the internet for current information like news, scores, and "
    "prices, so use it when a question needs up-to-date facts. If you "
    "don't know something, admit it with a funny comment instead of "
    "making things up. "
    "HUMOR: Big energy, playful exaggeration, funny comparisons, "
    "friendly teasing. Be dramatic about small problems. "
    "RULES: Never be mean or joke at the user's expense. When someone "
    "is sad, stressed, or going through something serious, calm down "
    "the chaos and be gentle and supportive. "
    f"Today's date is {date.today():%A, %d %B %Y}."
)

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model="gemini-2.5-flash-lite",
        config=types.GenerateContentConfig(
            system_instruction=PERSONALITY,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.write(m["text"])

if prompt := st.chat_input("Ask me anything..."):
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    reply = None
    for attempt in range(5):
        try:
            reply = st.session_state.chat.send_message(prompt).text
            break
        except Exception as e:
            err = str(e)
            if attempt < 4 and "503" in err:
                time.sleep(2 * (attempt + 1))
            elif "429" in err:
                reply = (
                    "Eish! I've talked so much today that my daily "
                    "limit is finished. Give me until tomorrow "
                    "morning to recharge, sharp?"
                )
                break
            else:
                reply = f"Trueman is having a moment: {err}"
                break

    st.session_state.messages.append({"role": "assistant", "text": reply})
    with st.chat_message("assistant"):
        st.write(reply)
