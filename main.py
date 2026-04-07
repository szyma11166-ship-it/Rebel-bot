"""
REBEL POKEMON MONITOR BOT
Monitoruje rebel.pl/pokemon i wysyła alerty na Telegram
gdy pojawiają się nowe sealed produkty Pokémon TCG.
"""

import requests
from bs4 import BeautifulSoup
import time
import os
import json
import logging
from datetime import datetime
from pathlib import Path

# ── Konfiguracja ──────────────────────────────────────────────────────────────

TOKEN   = "8641671766:AAEfRWe-lHc_8LLTA-rDecW3NjooDmENOl4"
CHAT_ID = "-1003743099672"

SENT_FILE    = "rebel_sent.json"   # Pamięć między restartami
CHECK_EVERY  = 60                  # Sekundy między sprawdzeniami
DEBUG_HTML   = False               # True = zapisuje HTML do pliku (debug)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

URLS_TO_MONITOR = [
    "https://www.rebel.pl/pokemon",
    "https://www.rebel.pl/karty-pokemon",   # fallback - druga możliwa kategoria
]

# ── Filtry sealed produktów ───────────────────────────────────────────────────

# Produkty DOZWOLONE (sealed)
SEALED_KEYWORDS = [
    "booster box", "display", "booster pack", "etb", "elite trainer box",
    "tin", "bundle", "collection box", "blister", "build & battle",
    "premium collection", "ultra premium", "starter deck", "theme deck",
    "zestaw", "karty", "pokemon tcg", "trading card",
]

# Produkty BLOKOWANE (luźne karty, akcesoria niezwiązane)
BLOCKED_KEYWORDS = [
    "single", "pojedyncza", "graded", "psa", "bgs", "cgc",
    "sleeve", "koszulki", "album", "teczka", "folder",
    "playmat", "mata", "dice", "kości", "counter",
    "figurka", "pluszak", "plush", "manga", "book", "książka",
]

# Słowa preorder
PREORDER_KEYWORDS = [
    "przedsprzedaż", "preorder", "pre-order", "zapowiedź",
    "wkrótce", "dostępny od", "premiera",
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("rebel_bot.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ── Pamięć (JSON) ─────────────────────────────────────────────────────────────

def load_sent() -> set:
    try:
        data = json.loads(Path(SENT_FILE).read_text(encoding="utf-8"))
        return set(data)
    except Exception:
        return set()

def save_sent(sent: set):
    Path(SENT_FILE).write_text(
        json.dumps(list(sent), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg: str):
    if not TOKEN:
        log.warning("Brak TELEGRAM_TOKEN — wiadomość nie wysłana.")
        return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        if not r.ok:
            log.error(f"Telegram błąd: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.error(f"Telegram wyjątek: {e}")

def format_msg(name: str, price: str, link: str, preorder: bool, source_url: str) -> str:
    status = "🟣 <b>PRZEDPREMIERA</b>" if preorder else "🟢 <b>DOSTĘPNE TERAZ</b>"
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"<b>🔥 NOWY PRODUKT — REBEL.PL 🔥</b>\n\n"
        f"{status}\n\n"
        f"📦 <b>{name}</b>\n\n"
        f"💰 <b>{price}</b>\n\n"
        f"👉 <a href=\"{link}\">Zobacz produkt</a>\n\n"
        f"<i>🕐 {ts}</i>"
    )

# ── Filtry ────────────────────────────────────────────────────────────────────

def is_sealed(name: str, full_text: str) -> bool:
    """Zwraca True jeśli produkt wygląda na sealed Pokémon TCG."""
    combined = (name + " " + full_text).lower()

    # Blokuj jeśli zawiera zakazane słowa
    if any(kw in combined for kw in BLOCKED_KEYWORDS):
        return False

    # Przepuść jeśli zawiera sealed keyword
    if any(kw in combined for kw in SEALED_KEYWORDS):
        return True

    # Jeśli brak wyraźnego sygnału — blokuj (lepiej pominąć niż spamować)
    return False

def is_preorder(full_text: str) -> bool:
    t = full_text.lower()
    return any(kw in t for kw in PREORDER_KEYWORDS)

# ── Parsowanie ────────────────────────────────────────────────────────────────

def extract_products(html: str, base_url: str) -> list[dict]:
    """
    Próbuje kilku kombinacji selektorów CSS.
    Rebel.pl może używać różnych klas — logujemy co znaleziono.
    """
    soup = BeautifulSoup(html, "html.parser")
    products = []

    # Selektory do wypróbowania (od najbardziej do najmniej specyficznych)
    PRODUCT_SELECTORS = [
        ".product-box",
        ".product-item",
        ".product",
        "article.product",
        "[class*='product-card']",
        "[class*='product_box']",
        ".offer",
    ]

    NAME_SELECTORS   = [".product-name", ".name", "h2", "h3", ".title", "[class*='name']"]
    PRICE_SELECTORS  = [".price", ".product-price", "[class*='price']", ".amount"]
    LINK_SELECTORS   = ["a[href]"]

    container = None
    used_selector = None

    for sel in PRODUCT_SELECTORS:
        found = soup.select(sel)
        if found:
            container = found
            used_selector = sel
            log.info(f"Znaleziono {len(found)} produktów używając: '{sel}'")
            break

    if not container:
        log.warning("Nie znaleziono żadnych produktów! Sprawdź selektory lub HTML.")
        if DEBUG_HTML:
            Path("rebel_debug.html").write_text(html, encoding="utf-8")
            log.info("HTML zapisany do rebel_debug.html")
        return []

    for p in container:
        try:
            # Nazwa
            name = None
            for sel in NAME_SELECTORS:
                el = p.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break
            if not name:
                continue

            # Cena
            price = "brak ceny"
            for sel in PRICE_SELECTORS:
                el = p.select_one(sel)
                if el and el.get_text(strip=True):
                    price = el.get_text(strip=True)
                    break

            # Link
            a = p.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            if href.startswith("http"):
                link = href
            else:
                from urllib.parse import urljoin
                link = urljoin(base_url, href)

            full_text = p.get_text(" ", strip=True)

            products.append({
                "name": name,
                "price": price,
                "link": link,
                "full_text": full_text,
            })

        except Exception as e:
            log.debug(f"Błąd parsowania produktu: {e}")
            continue

    return products

# ── Główna logika ─────────────────────────────────────────────────────────────

def check_rebel(sent: set) -> int:
    new_count = 0

    for url in URLS_TO_MONITOR:
        log.info(f"Sprawdzam: {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                log.warning("Rate limit (429) — czekam 5 minut.")
                time.sleep(300)
                return new_count
            if not r.ok:
                log.warning(f"HTTP {r.status_code} dla {url}")
                continue

            products = extract_products(r.text, url)
            log.info(f"Znaleziono produktów do oceny: {len(products)}")

            for p in products:
                link = p["link"]

                if link in sent:
                    continue

                if not is_sealed(p["name"], p["full_text"]):
                    log.debug(f"POMINIĘTO (nie sealed): {p['name']}")
                    continue

                preorder = is_preorder(p["full_text"])
                msg = format_msg(p["name"], p["price"], link, preorder, url)

                send_telegram(msg)
                sent.add(link)
                new_count += 1

                log.info(f"✅ Wysłano: {p['name']} | {p['price']}")
                time.sleep(1)  # Krótka pauza między wiadomościami

        except requests.exceptions.RequestException as e:
            log.error(f"Błąd sieci dla {url}: {e}")

    return new_count

# ── Start ─────────────────────────────────────────────────────────────────────

def main():
    log.info("🚀 REBEL POKEMON BOT START")
    log.info(f"Sprawdzanie co {CHECK_EVERY}s | Monitored: {URLS_TO_MONITOR}")

    if not TOKEN:
        log.warning("⚠️  TELEGRAM_TOKEN nie ustawiony! Ustaw zmienną środowiskową.")

    sent = load_sent()
    log.info(f"Wczytano {len(sent)} znanych produktów z {SENT_FILE}")

    errors = 0

    while True:
        try:
            new = check_rebel(sent)
            save_sent(sent)
            if new:
                log.info(f"🎯 Wysłano {new} nowych alertów.")
            else:
                log.info("Brak nowych produktów.")
            errors = 0

        except Exception as e:
            errors += 1
            wait = min(60 * errors, 600)  # Exponential backoff max 10min
            log.error(f"Błąd #{errors}: {e} — czekam {wait}s")
            time.sleep(wait)
            continue

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()