"""Telegram bot: admin tasdiqlagan foydalanuvchilar uchun emaktab akkauntlariga kirib-chiqish.

Oqim: /start -> admin'ga so'rov -> admin tasdiqlaydi -> klientga namuna ->
klient akkauntlarni yuboradi -> "Boshlansinmi?" tugmasi -> kirib-chiqish (istagancha takrorlash mumkin).
"""
import asyncio
import datetime as dt
import html
import logging
import sys
from functools import wraps
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

import checker
import config
import db

log = logging.getLogger("bot")

RUN_LOCK = asyncio.Lock()   # bir vaqtda faqat bitta brauzer ishlaydi (navbat)
RUNNING = set()             # hozir tekshiruvi ketayotgan foydalanuvchilar

TEMPLATE = (
    "Akkauntlaringizni quyidagi namunadek, <b>har qatorda bittadan</b>, "
    "<code>login:parol</code> shaklida yozib shu chatga yuboring:\n\n"
    "<pre>login1:parol1\nlogin2:parol2\nlogin3:parol3</pre>\n"
    "Bir nechta qatorni bitta xabarda yuborsangiz bo'ladi. "
    "Xavfsizlik uchun yuborgan xabaringiz o'chiriladi."
)
WELCOME = "✅ <b>Sizga ruxsat berildi!</b>\n\n" + TEMPLATE

HELP = (
    "<b>Buyruqlar</b>\n"
    "/add - akkaunt qo'shish (namuna)\n"
    "/list - akkauntlarim va oxirgi natija\n"
    "/remove <code>login</code> - o'chirish (yoki <code>/remove all</code>)\n"
    "/run - kirib-chiqishni boshlash\n"
    "/auto <code>on|off</code> - kunlik avtomatik tekshiruv\n"
    "/status - holat"
)
ADMIN_HELP = (
    "\n\n<b>Admin</b>\n"
    "/requests - kutilayotgan so'rovlar\n"
    "/grant <code>ID [ism]</code> - qo'lda ruxsat berish\n"
    "/revoke <code>ID</code> - ruxsatni olish (akkauntlari ham o'chadi)\n"
    "/users - foydalanuvchilar"
)


def kb(*rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


def kb_ask_run():
    return kb([("✅ Ha, boshlansin", "run:yes"), ("❌ Hozir emas", "run:no")])


def kb_after():
    return kb([("🔁 Yana tekshirish", "run:yes")], [("➕ Akkaunt qo'shish", "add:help")])


# ---------- ruxsat nazorati ----------
def request_kb(uid):
    return kb([("✅ Ruxsat berish", f"req:approve:{uid}"), ("❌ Rad etish", f"req:reject:{uid}")])


async def notify_admin(bot, uid, name, username):
    text = (
        "🔔 <b>Yangi so'rov</b>\n\n"
        f"Ism: {html.escape(name)}\n"
        f"Username: {('@' + html.escape(username)) if username else '-'}\n"
        f"ID: <code>{uid}</code>\n\nRuxsat berasizmi?"
    )
    try:
        await bot.send_message(config.ADMIN_ID, text, parse_mode=ParseMode.HTML, reply_markup=request_kb(uid))
    except Exception:
        log.exception("Adminga so'rov yuborilmadi (admin botga /start bosganmi?)")


async def ensure_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user, msg = update.effective_user, update.effective_message
    if user is None or msg is None:
        return False
    if db.is_allowed(user.id):
        return True
    req = db.get_request(user.id)
    if req is None or req["status"] == "approved":     # approved bo'lsa-yu ruxsati olingan bo'lsa - qayta so'raydi
        db.create_request(user.id, user.full_name or "", user.username or "")
        await msg.reply_text("📨 So'rovingiz adminga yuborildi. Tasdiqlansa, sizga xabar keladi. Iltimos, kuting.")
        await notify_admin(context.bot, user.id, user.full_name or "", user.username or "")
    elif req["status"] == "pending":
        await msg.reply_text("⏳ So'rovingiz admin ko'rib chiqishini kutmoqda.")
    else:
        await msg.reply_text("⛔ Afsuski, so'rovingiz rad etilgan.")
    return False


def allowed(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await ensure_access(update, context):
            return
        return await func(update, context)
    return wrapper


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or user.id != config.ADMIN_ID:
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Bu buyruq faqat admin uchun.")
            return
        return await func(update, context)
    return wrapper


async def on_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin 'Ruxsat berish / Rad etish' tugmasini bosganda."""
    q = update.callback_query
    if q.from_user.id != config.ADMIN_ID:
        await q.answer("Faqat admin bosa oladi.", show_alert=True)
        return
    await q.answer()
    _, action, sid = q.data.split(":")
    uid = int(sid)
    req = db.get_request(uid)
    name = (req["name"] if req else "") or str(uid)

    if action == "approve":
        db.add_user(uid, name)
        db.set_request_status(uid, "approved")
        await q.edit_message_text(f"✅ {name} ({uid}) ga ruxsat berildi.")
        try:
            await context.bot.send_message(uid, WELCOME, parse_mode=ParseMode.HTML)
        except Exception:
            await context.bot.send_message(config.ADMIN_ID, f"⚠️ {uid} ga xabar yetmadi (botni bloklagan bo'lishi mumkin).")
    else:
        db.set_request_status(uid, "rejected")
        await q.edit_message_text(f"❌ {name} ({uid}) so'rovi rad etildi.")
        try:
            await context.bot.send_message(uid, "⛔ Afsuski, so'rovingiz rad etildi.")
        except Exception:
            pass


# ---------- yordamchilar ----------
def parse_line(line):
    """Faqat 'login:parol' formati (tasodifiy matn akkaunt bo'lib qolmasligi uchun)."""
    if ":" not in line:
        return None
    login, pwd = line.split(":", 1)
    login, pwd = login.strip(), pwd.strip()
    if not login or not pwd or any(ch.isspace() for ch in login):
        return None
    return login, pwd


async def send_long(bot, chat_id, text, reply_markup=None):
    while text:
        chunk, text = text[:3800], text[3800:]
        if text:                                  # qatorni o'rtasidan kesmaslik
            cut = chunk.rfind("\n")
            if cut > 0:
                text = chunk[cut + 1:] + text
                chunk = chunk[:cut]
        await bot.send_message(chat_id, chunk, reply_markup=None if text else reply_markup)


async def try_delete(update: Update):
    try:
        await update.message.delete()
        return True
    except Exception:
        await update.effective_chat.send_message(
            "⚠️ Parol yozilgan xabarni o'zingiz o'chirib tashlang (menda o'chirish huquqi bo'lmadi)."
        )
        return False


# ---------- umumiy buyruqlar ----------
@allowed
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = HELP + (ADMIN_HELP if uid == config.ADMIN_ID else "")
    if db.count_accounts(uid) == 0:
        text += "\n\n" + TEMPLATE
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_after())


@allowed
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    auto = "yoqilgan ✅" if db.get_auto(uid) else "o'chirilgan ⏸"
    await update.message.reply_text(
        f"Akkauntlar: {db.count_accounts(uid)} / {config.MAX_ACCOUNTS}\n"
        f"Kunlik avtomatik tekshiruv: {auto}\n"
        f"Vaqti: har kuni {config.DAILY_TIME} ({config.TZ})"
    )


@allowed
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.list_accounts(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Hali akkaunt yo'q. /add buyrug'i bilan qo'shing.")
        return
    lines = []
    for i, r in enumerate(rows, 1):
        if r["last_ok"] is None:
            mark = "▫️ hali tekshirilmagan"
        elif r["last_ok"]:
            mark = f"✅ {r['last_run']}"
        else:
            mark = f"❌ {r['last_run']}"
        lines.append(f"{i}. {r['login']} - {mark}")
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))


# ---------- akkaunt qo'shish ----------
async def process_add(update: Update, text: str):
    uid = update.effective_user.id
    added, updated, bad, full = 0, 0, 0, False
    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = parse_line(line)
        if not parsed:
            bad += 1
            continue
        login, pwd = parsed
        exists = db.has_account(uid, login)
        if not exists and db.count_accounts(uid) >= config.MAX_ACCOUNTS:
            full = True
            break
        db.add_account(uid, login, pwd)
        if exists:
            updated += 1
        else:
            added += 1

    parts = []
    if added:
        parts.append(f"✅ Qo'shildi: {added}")
    if updated:
        parts.append(f"🔄 Paroli yangilandi: {updated}")
    if bad:
        parts.append(f"⚠️ O'qib bo'lmagan qator: {bad} (format: login:parol)")
    if full:
        parts.append(f"⛔ Limitga yetdingiz ({config.MAX_ACCOUNTS} ta).")
    total = db.count_accounts(uid)
    parts.append(f"\nJami akkaunt: {total}")
    if total:
        parts.append("\nHar bir akkauntga kirib-chiqishni boshlaymizmi?")
        await update.effective_chat.send_message("\n".join(parts), reply_markup=kb_ask_run())
    else:
        await update.effective_chat.send_message("\n".join(parts) + "\n\n" + "Format: login:parol")


@allowed
async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = (update.message.text or "").split(None, 1)
    if len(parts) > 1:                           # /add login:parol  (bir xabarda)
        await try_delete(update)
        await process_add(update, parts[1])
        return
    await update.message.reply_text(TEMPLATE, parse_mode=ParseMode.HTML)


@allowed
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not any(parse_line(l) for l in text.splitlines()):
        await update.message.reply_text("Tushunmadim 🤔\n\n" + TEMPLATE, parse_mode=ParseMode.HTML)
        return
    await try_delete(update)
    await process_add(update, text)


@allowed
async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Ishlatish: /remove login  yoki  /remove all")
        return
    if len(context.args) == 1 and context.args[0].lower() == "all":
        n = db.remove_accounts(uid, None)
    else:
        n = db.remove_accounts(uid, context.args)
    await update.message.reply_text(f"🗑 O'chirildi: {n} ta akkaunt.")


# ---------- tekshiruv ----------
async def run_for_user(bot, uid, accounts, progress_msg=None):
    total = len(accounts)

    async def on_progress(i, total_, login, ok, note):
        db.set_status(uid, login, ok, note)
        if progress_msg and (i % 3 == 0 or i == total_):
            try:
                await progress_msg.edit_text(f"⏳ {i}/{total_} tekshirildi...")
            except Exception:
                pass

    try:
        results = await checker.run_batch(accounts, on_progress)
    except Exception:
        log.exception("Tekshiruv ishlamadi (uid=%s)", uid)
        await bot.send_message(uid, "❌ Brauzer ishga tushmadi. Bot egasiga xabar bering.", reply_markup=kb_after())
        if uid != config.ADMIN_ID:
            try:
                await bot.send_message(config.ADMIN_ID, f"⚠️ {uid} uchun tekshiruv ishlamadi. bot.log ni ko'ring.")
            except Exception:
                pass
        return

    bad = [(l, n) for l, ok, n in results if not ok]
    text = f"📊 Natija: {total - len(bad)}/{total} muvaffaqiyatli"
    if bad:
        text += "\n\n❌ Kira olmaganlar:\n" + "\n".join(f"• {l} - {n}" for l, n in bad)
    await send_long(bot, uid, text, reply_markup=kb_after())


async def begin_run(bot, uid, from_daily=False):
    accounts = db.get_accounts(uid)
    if not accounts:
        if not from_daily:
            await bot.send_message(uid, "Hali akkaunt yo'q.\n\n" + TEMPLATE, parse_mode=ParseMode.HTML)
        return
    if uid in RUNNING:
        if not from_daily:
            await bot.send_message(uid, "⏳ Tekshiruv hozir davom etmoqda, tugashini kuting.")
        return

    RUNNING.add(uid)
    try:
        queued = RUN_LOCK.locked()
        progress = await bot.send_message(
            uid, "⏳ Navbatda kutilmoqda..." if queued else f"⏳ Boshlandi: {len(accounts)} ta akkaunt..."
        )
        async with RUN_LOCK:
            if queued:
                try:
                    await progress.edit_text(f"⏳ Boshlandi: {len(accounts)} ta akkaunt...")
                except Exception:
                    pass
            await run_for_user(bot, uid, accounts, progress)
    finally:
        RUNNING.discard(uid)


@allowed
async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await begin_run(context.bot, update.effective_user.id)


async def on_user_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not db.is_allowed(uid):
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return
    await q.answer()
    if q.data == "run:no":
        await q.edit_message_reply_markup(reply_markup=kb([("▶️ Boshlash", "run:yes")]))
    elif q.data == "add:help":
        await context.bot.send_message(uid, TEMPLATE, parse_mode=ParseMode.HTML)
    elif q.data == "run:yes":
        try:
            await q.edit_message_reply_markup(reply_markup=None)   # ikki marta bosilmasligi uchun
        except Exception:
            pass
        await begin_run(context.bot, uid)


@allowed
async def auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0].lower() if context.args else ""
    if arg not in ("on", "off"):
        await update.message.reply_text("Ishlatish: /auto on  yoki  /auto off")
        return
    db.set_auto(update.effective_user.id, arg == "on")
    await update.message.reply_text("✅ Kunlik tekshiruv yoqildi." if arg == "on" else "⏸ Kunlik tekshiruv o'chirildi.")


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    log.info("Kunlik tekshiruv boshlandi")
    for uid in db.users_with_auto():
        try:
            await begin_run(context.bot, uid, from_daily=True)
        except Exception:
            log.exception("Kunlik tekshiruvda xato (uid=%s)", uid)
    log.info("Kunlik tekshiruv tugadi")


# ---------- admin ----------
@admin_only
async def requests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.pending_requests()
    if not rows:
        await update.message.reply_text("Kutilayotgan so'rov yo'q.")
        return
    for r in rows:
        await notify_admin(context.bot, r["tg_id"], r["name"] or "", r["username"] or "")


@admin_only
async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Ishlatish: /grant 123456789 Ism")
        return
    uid = int(context.args[0])
    db.add_user(uid, " ".join(context.args[1:])[:40])
    db.set_request_status(uid, "approved")
    await update.message.reply_text(f"✅ {uid} ga ruxsat berildi.")
    try:
        await context.bot.send_message(uid, WELCOME, parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text("(Foydalanuvchi botni hali /start qilmagan, xabar yetmadi.)")


@admin_only
async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Ishlatish: /revoke 123456789")
        return
    ok = db.remove_user(int(context.args[0]))
    await update.message.reply_text("🗑 Ruxsat olindi, akkauntlari o'chirildi." if ok else "Bunday foydalanuvchi yo'q.")


@admin_only
async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.list_users()
    lines = [f"{r['tg_id']} - {r['name'] or '-'} - akkaunt: {r['n']} - auto: {'on' if r['auto'] else 'off'}" for r in rows]
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines) or "Bo'sh.")


@allowed
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Buyruqlar ro'yxati: /start")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Kutilmagan xato", exc_info=context.error)
    try:
        await context.bot.send_message(config.ADMIN_ID, f"⚠️ Bot xatosi: {type(context.error).__name__}")
    except Exception:
        pass


def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(), logging.FileHandler(config.BASE / "bot.log", encoding="utf-8")],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)   # token logga tushmasligi uchun

    if not config.BOT_TOKEN or not config.ADMIN_ID:
        sys.exit("XATO: .env faylida BOT_TOKEN va ADMIN_ID to'ldirilishi kerak.")
    try:
        hh, mm = map(int, config.DAILY_TIME.split(":"))
        tz = ZoneInfo(config.TZ)
    except Exception:
        sys.exit("XATO: DAILY_TIME (masalan 08:00) yoki TIMEZONE noto'g'ri.")

    db.init()
    app = Application.builder().token(config.BOT_TOKEN).build()
    if app.job_queue is None:
        sys.exit("XATO: python -m pip install -r requirements.txt ni qayta ishga tushiring (job-queue kerak).")

    app.add_handler(CallbackQueryHandler(on_request, pattern=r"^req:(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(on_user_button, pattern=r"^(run:yes|run:no|add:help)$"))
    for name, fn in [("start", start), ("help", start), ("status", status), ("list", list_cmd),
                     ("add", add_cmd), ("remove", remove_cmd), ("run", run_cmd), ("auto", auto_cmd),
                     ("requests", requests_cmd), ("grant", grant), ("revoke", revoke), ("users", users_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.ALL, unknown))
    app.add_error_handler(on_error)

    app.job_queue.run_daily(daily_job, time=dt.time(hh, mm, tzinfo=tz), name="daily")
    log.info("Bot ishga tushdi. Kunlik tekshiruv: %s (%s)", config.DAILY_TIME, config.TZ)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
