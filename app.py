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
SHARE_TTL_SECONDS = 7 * 24 *
