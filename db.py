"""SQLite baza. Parollar Fernet bilan shifrlangan holda saqlanadi."""
import datetime as dt
import logging
import sqlite3
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from cryptography.fernet import InvalidToken

import config

log = logging.getLogger("db")
DB_PATH = config.BASE / "bot.db"


def now_str():
    return dt.datetime.now(ZoneInfo(config.TZ)).strftime("%d.%m %H:%M")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS allowed_users(
                tg_id INTEGER PRIMARY KEY,
                name TEXT,
                auto INTEGER NOT NULL DEFAULT 1,
                added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                login TEXT NOT NULL,
                password_enc TEXT NOT NULL,
                last_ok INTEGER,
                last_note TEXT,
                last_run TEXT,
                UNIQUE(tg_id, login)
            );
            CREATE TABLE IF NOT EXISTS requests(
                tg_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                status TEXT NOT NULL,
                created_at TEXT
            );
            """
        )
        if config.ADMIN_ID:
            c.execute(
                "INSERT OR IGNORE INTO allowed_users(tg_id, name, added_at) VALUES(?,?,?)",
                (config.ADMIN_ID, "admin", now_str()),
            )


# ---------- foydalanuvchilar ----------
def is_allowed(tg_id):
    if tg_id == config.ADMIN_ID:
        return True
    with conn() as c:
        return c.execute("SELECT 1 FROM allowed_users WHERE tg_id=?", (tg_id,)).fetchone() is not None


def add_user(tg_id, name=""):
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO allowed_users(tg_id, name, added_at) VALUES(?,?,?)",
            (tg_id, name, now_str()),
        )


def remove_user(tg_id):
    """Foydalanuvchi va uning barcha akkauntlari (parollari) o'chiriladi."""
    if tg_id == config.ADMIN_ID:
        return False
    with conn() as c:
        c.execute("DELETE FROM accounts WHERE tg_id=?", (tg_id,))
        c.execute("DELETE FROM requests WHERE tg_id=?", (tg_id,))
        cur = c.execute("DELETE FROM allowed_users WHERE tg_id=?", (tg_id,))
        return cur.rowcount > 0


def list_users():
    with conn() as c:
        return c.execute(
            """SELECT u.tg_id, u.name, u.auto,
                      (SELECT COUNT(*) FROM accounts a WHERE a.tg_id=u.tg_id) AS n
               FROM allowed_users u ORDER BY u.added_at"""
        ).fetchall()


def get_auto(tg_id):
    with conn() as c:
        r = c.execute("SELECT auto FROM allowed_users WHERE tg_id=?", (tg_id,)).fetchone()
        return bool(r["auto"]) if r else False


def set_auto(tg_id, value):
    with conn() as c:
        c.execute("UPDATE allowed_users SET auto=? WHERE tg_id=?", (1 if value else 0, tg_id))


def users_with_auto():
    with conn() as c:
        rows = c.execute(
            """SELECT u.tg_id FROM allowed_users u
               WHERE u.auto=1 AND EXISTS(SELECT 1 FROM accounts a WHERE a.tg_id=u.tg_id)"""
        ).fetchall()
        return [r["tg_id"] for r in rows]


# ---------- ruxsat so'rovlari ----------
def get_request(tg_id):
    with conn() as c:
        return c.execute("SELECT * FROM requests WHERE tg_id=?", (tg_id,)).fetchone()


def create_request(tg_id, name, username):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO requests(tg_id, name, username, status, created_at) VALUES(?,?,?,?,?)",
            (tg_id, name, username, "pending", now_str()),
        )


def set_request_status(tg_id, status):
    with conn() as c:
        c.execute("UPDATE requests SET status=? WHERE tg_id=?", (status, tg_id))


def pending_requests():
    with conn() as c:
        return c.execute("SELECT * FROM requests WHERE status='pending' ORDER BY created_at").fetchall()


# ---------- akkauntlar ----------
def count_accounts(tg_id):
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM accounts WHERE tg_id=?", (tg_id,)).fetchone()[0]


def has_account(tg_id, login):
    with conn() as c:
        return c.execute("SELECT 1 FROM accounts WHERE tg_id=? AND login=?", (tg_id, login)).fetchone() is not None


def add_account(tg_id, login, password):
    enc = config.FERNET.encrypt(password.encode()).decode()
    with conn() as c:
        c.execute(
            """INSERT INTO accounts(tg_id, login, password_enc) VALUES(?,?,?)
               ON CONFLICT(tg_id, login) DO UPDATE SET password_enc=excluded.password_enc""",
            (tg_id, login, enc),
        )


def remove_accounts(tg_id, logins=None):
    with conn() as c:
        if logins is None:
            cur = c.execute("DELETE FROM accounts WHERE tg_id=?", (tg_id,))
        else:
            n = 0
            for lg in logins:
                n += c.execute("DELETE FROM accounts WHERE tg_id=? AND login=?", (tg_id, lg)).rowcount
            return n
        return cur.rowcount


def list_accounts(tg_id):
    with conn() as c:
        return c.execute(
            "SELECT login, last_ok, last_note, last_run FROM accounts WHERE tg_id=? ORDER BY id",
            (tg_id,),
        ).fetchall()


def get_accounts(tg_id):
    """[(login, parol)] - parollar shifrdan ochilgan holda. Faqat tekshiruv uchun."""
    out = []
    with conn() as c:
        rows = c.execute("SELECT login, password_enc FROM accounts WHERE tg_id=? ORDER BY id", (tg_id,)).fetchall()
    for r in rows:
        try:
            out.append((r["login"], config.FERNET.decrypt(r["password_enc"].encode()).decode()))
        except InvalidToken:
            log.error("Parolni shifrdan ochib bo'lmadi (FERNET_KEY o'zgargan?): %s", r["login"])
    return out


def set_status(tg_id, login, ok, note):
    with conn() as c:
        c.execute(
            "UPDATE accounts SET last_ok=?, last_note=?, last_run=? WHERE tg_id=? AND login=?",
            (1 if ok else 0, note, now_str(), tg_id, login),
        )
