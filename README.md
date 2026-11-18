# Emaktab Telegram boti

Oqim: klient `/start` bosadi → adminga so'rov keladi → admin tasdiqlaydi → klientga namuna yuboriladi →
klient akkauntlarni yuboradi → bot "Boshlansinmi?" deb so'raydi → "Ha" bosilsa hamma akkauntga kirib-chiqadi.
Ruxsatdan keyin klient istagancha takrorlashi mumkin.

## 1. Bot ochish (Telegram'da)
1. **@BotFather** → `/newbot` → nom va username bering (oxiri `bot` bilan tugasin).
2. BotFather bergan **TOKEN** ni nusxalang.
3. **@userinfobot** ga `/start` yozing → u sizning **ID** raqamingizni aytadi.
4. **Muhim:** o'zingiz ochgan botga kirib bir marta `/start` bosing. Aks holda bot sizga so'rovlarni yubora olmaydi.

## 2. Kompyuterda o'rnatish
Papkani VS Code'da oching (File → Open Folder), terminalda:

```
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`.env.example` dan nusxa olib nomini **`.env`** qiling va to'ldiring:

```
BOT_TOKEN=BotFather bergan token
ADMIN_ID=sizning ID raqamingiz
```

## 3. Ishga tushirish
```
python bot.py
```
Terminalda "Bot ishga tushdi" chiqsa tayyor.
**Bot faqat `bot.py` ishlab turganda ishlaydi.** Terminal yopilsa yoki kompyuter uyquga ketsa, bot to'xtaydi.
Doim ishlashi uchun VPS yoki doim yoniq kompyuter kerak.

## 4. Foydalanish
**Klient:**
1. Botga `/start` yozadi → "So'rovingiz adminga yuborildi".
2. Siz ruxsat bergach, unga namuna keladi:
   ```
   login1:parol1
   login2:parol2
   ```
3. U to'ldirib yuboradi (xabari avtomatik o'chiriladi).
4. Bot: "Kirib-chiqishni boshlaymizmi?" → **Ha, boshlansin** tugmasi.
5. Natija: `Natija: 27/29` va kira olmaganlar sabablari. Pastda **Yana tekshirish** tugmasi, istagancha bosish mumkin.

Boshqa buyruqlar: `/add`, `/list`, `/remove login`, `/remove all`, `/run`, `/auto on|off`, `/status`.

**Admin (siz):**
- So'rov kelganda **Ruxsat berish / Rad etish** tugmalari chiqadi.
- `/requests` - kutilayotgan so'rovlar, `/users` - ro'yxat
- `/grant ID ism` - qo'lda ruxsat, `/revoke ID` - ruxsatni olish (akkauntlari ham o'chadi)

Kunlik avtomatik tekshiruv vaqti: `.env` dagi `DAILY_TIME` (standart 08:00, Toshkent vaqti).
Bir vaqtda bitta tekshiruv ishlaydi, qolganlar navbatda kutadi.

## Xavfsizlik
- Parollar bazada **shifrlangan** (`FERNET_KEY`, `.env` ichida o'zi yaratiladi). **`.env` ni zaxiralab qo'ying va hech kimga bermang**: kalit yo'qolsa, parollarni ochib bo'lmaydi.
- Parol yozilgan xabar bot tomonidan o'chiriladi, parollar hech qayerda ko'rsatilmaydi va logga yozilmaydi.
- Har kim faqat o'z akkauntlarini ko'radi.
- Token tarqalsa, BotFather'da `/revoke` qilib yangisini oling.
- Odamlar faqat **o'zlarining** akkauntlarini qo'shsin va sayt qoidalariga rioya qilinsin.

## Muammo bo'lsa
- `bot.log` faylida xatolar bor.
- "Kira olmaganlar" ro'yxatidagi sabab matniga qarang.
