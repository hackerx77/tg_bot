"""Sozlamalar. Hammasi .env faylidan o'qiladi."""
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

BASE = Path(__file__).parent
ENV_FILE = BASE / ".env"
load_dotenv(ENV_FILE)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
try:
    ADMIN_ID = int((os.getenv("ADMIN_ID") or "0").strip())
except ValueError:
    sys.exit("XATO: .env dagi ADMIN_ID faqat raqamdan iborat bo'lishi kerak.")

DAILY_TIME = os.getenv("DAILY_TIME", "08:00").strip()
TZ = os.getenv("TIMEZONE", "Asia/Tashkent").strip()
LOGIN_URL = os.getenv("LOGIN_URL", "https://login.emaktab.uz/").strip()
MAX_ACCOUNTS = int(os.getenv("MAX_ACCOUNTS_PER_USER", "50"))

# Parollarni shifrlash kaliti. Yo'q bo'lsa, birinchi ishga tushishda o'zi yaratiladi.
_key = os.getenv("FERNET_KEY", "").strip()
if not _key:
    _key = Fernet.generate_key().decode()
    with ENV_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\nFERNET_KEY={_key}\n")
FERNET = Fernet(_key.encode())
