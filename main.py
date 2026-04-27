import requests
from bs4 import BeautifulSoup
import time
import json
import logging
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

# ── Konfiguracja ──────────────────────────────────────────────────────────────

TOKEN   = "8641671766:AAEfRWe-lHc_8LLTA-rDecW3NjooDmENOl4"
CHAT_ID = "-1003743099672"

SENT_FILE        = "rebel_sent.json"
SUMMARY_FILE     = "rebel_summary.json"
CHECK_EVERY      = 20
SUMMARY_HOUR     = 18
DEBUG_HTML       = False

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
    "https://www.rebel.pl/karty-pokemon",
]

# ── Sygnały niedostępności ────────────────────────────────────────────────────

UNAVAILABLE_SIGNALS = [
    "niedostępny", "produkt niedostępny", "wyprzedany",
    "brak w magazynie", "obecnie niedostępny", "out of stock",
    "unavailable", "sold out",
]

# Teksty obecne TYLKO gdy produkt dostępny (kup / dodaj do koszyka)
AVAILABLE_SIGNALS = [
    "dodaj do koszyka", "kup teraz", "add to cart", "buy now",
    "zamów", "do koszyka",
]

# ── Filtry sealed produktów ───────────────────────────────────────────────────

SEALED_KEYWORDS = [
    "booster box", "display", "booster pack", "etb", "elite trainer box",
    "tin", "bundle", "collection box", "blister", "build & battle",
    "premium collection", "ultra premium", "starter deck", "theme deck",
    "zestaw", "karty", "pokemon tcg", "trading card",
]

BLOCKED_KEYWORDS = [
    "single", "pojedyncza", "graded", "psa", "bgs", "cgc",
    "sleeve", "koszulki", "album", "teczka", "folder",
    "playmat", "mata", "dice", "kości", "counter",
    "figurka", "pluszak", "plush", "manga", "book", "książka",
]

PREORDER_KEYWORDS = [
    "przedsprzedaż", "preorder", "pre-order",
    "zapowiedź", "wkrótce",
    "dostępny od", "premiera",
    "planowana premiera",
    "wysyłka od", "wysyłka w",
]

# ── Kategorie do podsumowania ─────────────────────────────────────────────────

CATEGORIES = [
    ("📦 Booster Boxy / Display",    ["booster box", "display"]),
    ("🎁 Elite Trainer Boxy / Tiny", ["etb", "elite trainer box", "tin"]),
    ("🎴 Blistry / Pack",            ["blister", "booster pack", "build & battle"]),
    ("💎 Kolekcje Premium",          ["premium collection", "ultra premium", "collection box", "bundle"]),
    ("🃏 Decki / Startery",          ["starter deck", "theme deck"]),
    ("🔮 Inne Sealed",               []),
]

def categorize(name: str, full_text: str) -> str:
    combined = (name + " " + full_text).lower()
    for label, keywords in CATEGORIES:
        if not keywords:
            return label
        if any(kw in combined for kw in keywords):
            return label
    return "🔮 Inne Sealed"

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

# ── Deduplicacja ──────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Klucz deduplicacji — lowercase, bez białych znaków."""
    return " ".join(name.lower().split())

def canonical_url(url: str) -> str:
    """Usuwa parametry query i fragment z URL."""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

# ── Pamięć (JSON) ─────────────────────────────────────────────────────────────

def load_sent() -> dict:
    """
    Zwraca dict:
      {
        "urls":  [...],   # kanoniczne URL-e (legacy + nowe)
        "names": [...],   # znormalizowane nazwy produktów
      }
    """
    try:
        raw = json.loads(Path(SENT_FILE).read_text(encoding="utf-8"))
        # Obsługa starego formatu (lista URL-i)
        if isinstance(raw, list):
            return {"urls": raw, "names": []}
        return {
            "urls":  raw.get("urls", []),
            "names": raw.get("names", []),
        }
    except Exception:
        return {"urls": [], "names": []}

def save_sent(sent: dict):
    Path(SENT_FILE).write_text(
        json.dumps(sent, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def is_already_sent(sent: dict, name: str, url: str) -> bool:
    """Zwraca True jeśli produkt był już wysłany — sprawdza nazwę ORAZ URL."""
    if normalize_name(name) in sent["names"]:
        return True
    if canonical_url(url) in sent["urls"]:
        return True
    return False

def mark_sent(sent: dict, name: str, url: str):
    sent["names"].append(normalize_name(name))
    sent["urls"].append(canonical_url(url))

def load_summary_state() -> dict:
    try:
        return json.loads(Path(SUMMARY_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {"last_summary_date": None, "pending": []}

def save_summary_state(state: dict):
    Path(SUMMARY_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg: str):
    if not TOKEN:
        log.warning("Brak TOKEN — wiadomość nie wysłana.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not r.ok:
            log.error(f"Telegram błąd: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.error(f"Telegram wyjątek: {e}")

def format_alert(name: str, price: str, link: str, preorder: bool) -> str:
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

def format_daily_summary(pending: list, day_str: str) -> str:
    if not pending:
        return (
            f"<b>📊 PODSUMOWANIE DNIA — {day_str}</b>\n\n"
            f"rebel.pl/pokemon\n\n"
            f"Brak nowych sealed produktów dzisiaj. 😴"
        )

    grouped: dict[str, list] = {}
    for p in pending:
        cat = p.get("category", "🔮 Inne Sealed")
        grouped.setdefault(cat, []).append(p)

    lines = [
        f"<b>📊 PODSUMOWANIE DNIA — {day_str}</b>\n",
        f"rebel.pl/pokemon\n",
        f"<b>Łącznie nowych produktów: {len(pending)}</b>\n",
    ]

    for label, _ in CATEGORIES:
        items = grouped.get(label)
        if not items:
            continue
        lines.append(f"\n{label}")
        for p in items:
            pre_tag = " 🟣" if p.get("preorder") else ""
            lines.append(
                f"• <a href=\"{p['link']}\">{p['name']}</a>"
                f" — {p['price']}{pre_tag}"
            )

    ts = datetime.now().strftime("%H:%M")
    lines.append(f"\n<i>🕐 Raport wygenerowany o {ts}</i>")
    return "\n".join(lines)

# ── Filtry ────────────────────────────────────────────────────────────────────

def is_sealed(name: str, full_text: str) -> bool:
    combined = (name + " " + full_text).lower()
    if any(kw in combined for kw in BLOCKED_KEYWORDS):
        return False
    return any(kw in combined for kw in SEALED_KEYWORDS)

def is_preorder(full_text: str) -> bool:
    return any(kw in full_text.lower() for kw in PREORDER_KEYWORDS)

def check_availability(full_text: str) -> bool:
    t = full_text.lower()

    # jeśli wyraźnie niedostępny → NIE
    if any(s in t for s in UNAVAILABLE_SIGNALS):
        return False

    # jeśli jest koszyk → TAK
    if any(s in t for s in AVAILABLE_SIGNALS):
        return True

    # brak sygnału → traktuj jako potencjalnie dostępny
    return True
    
# ── Parsowanie ────────────────────────────────────────────────────────────────

def extract_products(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    PRODUCT_SELECTORS = [
        ".product-box", ".product-item", ".product",
        "article.product", "[class*='product-card']",
        "[class*='product_box']", ".offer",
    ]
    NAME_SELECTORS  = [".product-name", ".name", "h2", "h3", ".title", "[class*='name']"]
    PRICE_SELECTORS = [".price", ".product-price", "[class*='price']", ".amount"]

    container = None
    for sel in PRODUCT_SELECTORS:
        found = soup.select(sel)
        if found:
            container = found
            log.info(f"Znaleziono {len(found)} produktów używając: '{sel}'")
            break

    if not container:
        log.warning("Nie znaleziono żadnych produktów!")
        if DEBUG_HTML:
            Path("rebel_debug.html").write_text(html, encoding="utf-8")
        return []

    products = []
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
            link = href if href.startswith("http") else urljoin(base_url, href)

            full_text = p.get_text(" ", strip=True)
            available = check_availability(full_text)

            products.append({
                "name":      name,
                "price":     price,
                "link":      link,
                "full_text": full_text,
                "available": available,
            })

        except Exception as e:
            log.debug(f"Błąd parsowania produktu: {e}")

    return products

# ── Główna logika ─────────────────────────────────────────────────────────────

def check_rebel(sent: dict, summary_state: dict) -> int:
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
                if is_already_sent(sent, p["name"], p["link"]):
                    continue

                if not is_sealed(p["name"], p["full_text"]):
                    continue

                preorder = is_preorder(p["full_text"])

                # 🔥 KLUCZOWA ZMIANA:

                # przepuszczamy preorder nawet bez dostępności

                if not preorder and not p["available"]:

                    log.info(f"POMINIĘTO (niedostępny i nie preorder): {p['name']}")

                    mark_sent(sent, p["name"], p["link"])

                    continue

                category = categorize(p["name"], p["full_text"])

                msg = format_alert(p["name"], p["price"], p["link"], preorder)

                send_telegram(msg)

                mark_sent(sent, p["name"], p["link"])

                new_count += 1

                summary_state["pending"].append({

                    "name":     p["name"],

                    "price":    p["price"],

                    "link":     p["link"],

                    "category": category,

                    "preorder": preorder,

                })

                log.info(f"✅ Wysłano: {p['name']} | {p['price']} | {category}")

                time.sleep(1)

        except requests.exceptions.RequestException as e:

            log.error(f"Błąd sieci dla {url}: {e}")

    return new_count


def maybe_send_summary(summary_state: dict):
    now = datetime.now()
    today_str = date.today().isoformat()

    if now.hour != SUMMARY_HOUR:
        return
    if summary_state.get("last_summary_date") == today_str:
        return

    day_display = date.today().strftime("%d.%m.%Y")
    msg = format_daily_summary(summary_state["pending"], day_display)
    send_telegram(msg)
    log.info(f"📊 Wysłano podsumowanie ({len(summary_state['pending'])} produktów).")

    summary_state["last_summary_date"] = today_str
    summary_state["pending"] = []


# ── Start ─────────────────────────────────────────────────────────────────────

def main():
    log.info("🚀 REBEL POKEMON BOT START")
    log.info(f"Sprawdzanie co {CHECK_EVERY}s | Podsumowanie o {SUMMARY_HOUR}:00")

    sent          = load_sent()
    summary_state = load_summary_state()
    log.info(
        f"Wczytano {len(sent['names'])} znanych nazw, "
        f"{len(sent['urls'])} URL-i | "
        f"{len(summary_state['pending'])} w kolejce podsumowania"
    )

    errors = 0
    while True:
        try:
            new = check_rebel(sent, summary_state)
            save_sent(sent)
            save_summary_state(summary_state)

            maybe_send_summary(summary_state)
            save_summary_state(summary_state)

            log.info(f"🎯 {new} nowych alertów." if new else "Brak nowych produktów.")
            errors = 0

        except Exception as e:
            errors += 1
            wait = min(60 * errors, 600)
            log.error(f"Błąd #{errors}: {e} — czekam {wait}s")
            time.sleep(wait)
            continue

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()