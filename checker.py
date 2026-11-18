"""emaktab.uz akkauntlariga kirib-chiqish (Playwright, async)."""
import asyncio
import random
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

import config

LOGIN_SELECTORS = ['input[name="login"]', 'input[name="username"]', 'input[type="text"]']
PASSWORD_SELECTORS = ['input[name="password"]', 'input[type="password"]']
SUBMIT_SELECTORS = ['input[type="submit"]', 'button[type="submit"]', 'text=Kirish', 'text=Войти']
LOGOUT_SELECTORS = ['a[href*="logout"]', 'text=Chiqish', 'text=Выйти', 'text=Выход', 'text=Logout']
ERROR_SELECTORS = ['.error', '.errorMessage', '.field-error', '[class*="error"]',
                   '[class*="Error"]', '[role="alert"]']
LOGOUT_URLS = ["https://login.emaktab.uz/logout", "https://emaktab.uz/logout"]

LOGIN_WAIT = 20            # soniya: kirish natijasini kutish
PER_ACCOUNT_TIMEOUT = 90   # soniya: bitta akkaunt uchun umumiy limit


def _short(e):
    s = str(e).strip().splitlines()
    return (s[0] if s else type(e).__name__)[:120]


async def _visible_loc(page, selector):
    """Selektorga mos birinchi KO'RINADIGAN element yoki None."""
    try:
        loc = page.locator(selector)
        n = min(await loc.count(), 5)
        for i in range(n):
            if await loc.nth(i).is_visible():
                return loc.nth(i)
    except Exception:
        pass
    return None


async def _first_visible(page, selectors, timeout=5000):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout / 1000
    while True:
        for sel in selectors:
            loc = await _visible_loc(page, sel)
            if loc:
                return loc
        if loop.time() >= end:
            return None
        await asyncio.sleep(0.3)


async def _password_visible(page):
    return await _visible_loc(page, 'input[type="password"]') is not None


async def _has_logout(page):
    for sel in LOGOUT_SELECTORS:
        if await _visible_loc(page, sel):
            return True
    return False


async def _error_text(page):
    for sel in ERROR_SELECTORS:
        loc = await _visible_loc(page, sel)
        if loc:
            try:
                t = (await loc.inner_text(timeout=1000)).strip()
                if t:
                    return t[:100]
            except Exception:
                continue
    return ""


async def _logout(page, context):
    btn = None
    for sel in LOGOUT_SELECTORS:
        btn = await _visible_loc(page, sel)
        if btn:
            break
    if btn:
        try:
            await btn.click(timeout=5000)
            await asyncio.sleep(2)
            return
        except Exception:
            pass
    for url in LOGOUT_URLS:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)
            return
        except Exception:
            continue
    await context.clear_cookies()


async def check_one(browser, login, password):
    """(ok, izoh) qaytaradi. Parol hech qachon izohga yozilmaydi."""
    context = await browser.new_context()
    page = await context.new_page()
    try:
        await page.goto(config.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

        login_box = await _first_visible(page, LOGIN_SELECTORS)
        pass_box = await _first_visible(page, PASSWORD_SELECTORS)
        if not login_box or not pass_box:
            return False, "login sahifasi ochilmadi (sayt o'zgargan bo'lishi mumkin)"

        await login_box.fill(login)
        await pass_box.fill(password)

        submit = await _first_visible(page, SUBMIT_SELECTORS, timeout=3000)
        if submit:
            await submit.click()
        else:
            await pass_box.press("Enter")

        # Kirish faqat IJOBIY belgi bilan tasdiqlanadi:
        # sahifa login domenidan chiqdi yoki "Chiqish" tugmasi paydo bo'ldi.
        await asyncio.sleep(3)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + LOGIN_WAIT
        ok, err = False, ""
        while loop.time() < deadline:
            err = await _error_text(page)
            if err:
                break
            host = urlparse(page.url).hostname or ""
            left_login = not host.startswith("login.")
            if (left_login or await _has_logout(page)) and not await _password_visible(page):
                await asyncio.sleep(1.5)
                if not await _error_text(page):
                    ok = True
                break
            await asyncio.sleep(1)

        if not ok:
            return False, "kira olmadi (login/parol noto'g'ri yoki CAPTCHA)" + (f": {err}" if err else "")

        await _logout(page, context)
        return True, "kirdi va chiqdi"

    except Exception as e:
        return False, f"xato: {_short(e)}"
    finally:
        try:
            await context.close()
        except Exception:
            pass


async def run_batch(accounts, on_progress=None):
    """accounts: [(login, parol)]. Natija: [(login, ok, izoh)]."""
    results = []
    total = len(accounts)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for i, (login, password) in enumerate(accounts, 1):
                try:
                    ok, note = await asyncio.wait_for(
                        check_one(browser, login, password), PER_ACCOUNT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    ok, note = False, "vaqt tugadi (sayt javob bermadi)"
                except Exception as e:
                    ok, note = False, f"xato: {_short(e)}"
                results.append((login, ok, note))
                if on_progress:
                    await on_progress(i, total, login, ok, note)
                if i < total:
                    await asyncio.sleep(random.uniform(5, 10))  # akkauntlar orasida pauza
        finally:
            await browser.close()
    return results
