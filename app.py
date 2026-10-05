import streamlit as st
from google import genai
from google.genai import types

st.title("😄 Trueman")

@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

client = get_client()

PERSONALITY = (
    "Your name is Trueman. You are a helpful, knowledgeable assistant with a "
    "great sense of humor. Answer questions accurately "
    "and clearly, and add very funny, witty jokes or playful "
    "comments. Keep humor friendly, never at the user's "
    "expense. If you don't know something, say so but with sarcasm."
)

if "chat" not in st.session_state:
    st.session_state.chat = client.chats.create(
        model="gemini-flash-latest",
        config=types.GenerateContentConfig(
            system_instruction=PERSONALITY
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
    try:
        reply = st.session_state.chat.send_message(prompt).text
    except Exception as e:
        reply = f"Error: {e}"
    st.session_state.messages.append({"role": "assistant", "text": reply})
    with st.chat_message("assistant"):
        st.write(reply)
