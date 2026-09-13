import os
import time
import json
import logging
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

# ── Konfiguracja Telegrama & Aplikacji ───────────────────────────────────────

TOKEN   = "8641671766:AAEfRWe-lHc_8LLTA-rDecW3NjooDmENOl4"
CHAT_ID = "-1003743099672"

SENT_FILE = "tcg_sent.json"
SUMMARY_FILE = "tcg_summary.json"
CHECK_EVERY = 300       # 5 minut (300 sekund)
SUMMARY_HOUR = 18       # Godzina wysyłki podsumowania
MAX_HISTORY_SIZE = 5000 # Maksymalna liczba pamiętanych alertów (ochrona RAM)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Definicja Sklepów TCG ─────────────────────────────────────────────────────

@dataclass
class StoreConfig:
    name: str
    urls: list[str]
    item_selector: str
    name_selectors: list[str]
    price_selectors: list[str]
    link_selectors: list[str]

STORES = [
    StoreConfig(
        name="Rebel",
        urls=["https://www.rebel.pl/pokemon", "https://www.rebel.pl/karty-pokemon"],
        item_selector=".product-box, .product-item, .productCard",
        name_selectors=[".product-name", ".name", "h2", "h3", ".title"],
        price_selectors=[".price", ".product-price", ".amount"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="StrefaGier",
        urls=["https://strefagier.com.pl/pl/c/Pokemon-TCG/83"],
        item_selector=".product, .product-main",
        name_selectors=[".product-name", ".product__name", "span.name"],
        price_selectors=[".price", ".product-price"],
        link_selectors=["a.product-name", "a[href]"]
    ),
    StoreConfig(
        name="3Strefa",
        urls=["https://3strefa.pl/pokemon-tcg-cat-245"],
        item_selector=".product, .product-box, .product_wrapper",
        name_selectors=[".product-name", ".name", "h3"],
        price_selectors=[".price", ".price-new"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="Graal",
        urls=["https://www.graal.pl/pl/c/Pokemon/1392"],
        item_selector=".product, .product-icon",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="PlanetaGier",
        urls=["https://planetagier.pl/pl/c/Pokemon-TCG/287"],
        item_selector=".product, .product-main_link",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="Dragonus",
        urls=["https://dragonus.pl/pokemon-tcg"],
        item_selector=".product, .product-container",
        name_selectors=[".product-name", ".name", "h2"],
        price_selectors=[".price", ".price-value"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="ShopGracz",
        urls=["https://shopgracz.pl/111-karty-pokemon"],
        item_selector=".product-miniature, .product-container",
        name_selectors=[".product-title", ".h3.product-title", ".name"],
        price_selectors=[".price", ".product-price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="Gnom",
        urls=["https://gnom.pl/pl/c/Pokemon-TCG/132"],
        item_selector=".product, .product-main",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="RGames",
        urls=["https://rgames.pl/pl/c/Pokemon-TCG/223"],
        item_selector=".product, .product-main",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="Pikselownia",
        urls=["https://pikselownia.pl/pl/c/Pokemon-TCG/124"],
        item_selector=".product, .product-main",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="Mepel",
        urls=["https://mepel.pl/pokemon-tcg"],
        item_selector=".product-miniature, .product-box",
        name_selectors=[".product-title", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="GrySilesia",
        urls=["https://grysilesia.pl/pl/c/Pokemon-TCG/145"],
        item_selector=".product, .product-main",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="Aleksander TCG",
        urls=["https://sklep-aleksander.pl/pl/c/Pokemon-TCG/212"],
        item_selector=".product, .product-main",
        name_selectors=[".product-name", ".name"],
        price_selectors=[".price"],
        link_selectors=["a[href]"]
    ),
    StoreConfig(
        name="VeselyDragon",
        urls=["https://www.vesely-dragon.pl/pokemon-karty/"],
        item_selector=".product, .product-item, .p-item",
        name_selectors=[".name", ".product-name", "h2"],
        price_selectors=[".price", ".price-final"],
        link_selectors=["a[href]"]
    )
]

# ── Sygnały i Filtrowanie ────────────────────────────────────────────────────

UNAVAILABLE_SIGNALS = [
    "niedostępny", "produkt niedostępny", "wyprzedany",
    "brak w magazynie", "obecnie niedostępny", "out of stock",
    "unavailable", "sold out", "brak na stanie", "niedostepny"
]

AVAILABLE_SIGNALS = [
    "dodaj do koszyka", "kup teraz", "add to cart", "buy now",
    "zamów", "do koszyka", "do koszyka", "kupuj"
]

SEALED_KEYWORDS = [
    "booster box", "display", "booster pack", "etb", "elite trainer box",
    "tin", "bundle", "collection box", "blister", "build & battle",
    "premium collection", "ultra premium", "starter deck", "theme deck",
    "zestaw", "karty", "pokemon tcg", "trading card", "booster"
]

BLOCKED_KEYWORDS = [
    "single", "pojedyncza", "graded", "psa", "bgs", "cgc",
    "sleeve", "koszulki", "album", "teczka", "folder",
    "playmat", "mata", "dice", "kości", "counter",
    "figurka", "pluszak", "plush", "manga", "book", "książka",
    "protector", "binder", "page"
]

PREORDER_KEYWORDS = [
    "przedsprzedaż", "preorder", "pre-order", "zapowiedź",
    "wkrótce", "dostępny od", "premiera", "planowana premiera",
    "wysyłka od", "wysyłka w"
]

CATEGORIES = [
    ("📦 Booster Boxy / Display",    ["booster box", "display"]),
    ("🎁 Elite Trainer Boxy / Tiny", ["etb", "elite trainer box", "tin"]),
    ("🎴 Blistry / Pack",            ["blister", "booster pack", "build & battle"]),
    ("💎 Kolekcje Premium",          ["premium collection", "ultra premium", "collection box", "bundle"]),
    ("🃏 Decki / Startery",          ["starter deck", "theme deck"]),
    ("🔮 Inne Sealed",               []),
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("tcg_bot.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ── Funkcje Pomocnicze & Zapis Stanu (PRO) ───────────────────────────────────

def normalize_name(name: str) -> str:
    return " ".join(name.lower().split())

def canonical_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def safe_save_json(filepath: str, data: dict):
    """Zapis atomowy zapobiegający uszkodzeniu pliku podczas restartu serwera."""
    tmp_path = f"{filepath}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, filepath)

def load_sent() -> dict:
    if not os.path.exists(SENT_FILE):
        return {"urls": [], "names": []}
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, list):
                return {"urls": raw, "names": []}
            return {"urls": raw.get("urls", []), "names": raw.get("names", [])}
    except Exception as e:
        log.error(f"Błąd odczytu {SENT_FILE}: {e}")
        return {"urls": [], "names": []}

def is_already_sent(sent: dict, name: str, url: str) -> bool:
    return normalize_name(name) in sent["names"] or canonical_url(url) in sent["urls"]

def mark_sent(sent: dict, name: str, url: str):
    sent["names"].append(normalize_name(name))
    sent["urls"].append(canonical_url(url))
    
    # Czyszczenie pamięci, jeśli przekroczymy dopuszczalny próg (zapobiega wyciekom RAM)
    if len(sent["names"]) > MAX_HISTORY_SIZE:
        sent["names"] = sent["names"][-MAX_HISTORY_SIZE:]
    if len(sent["urls"]) > MAX_HISTORY_SIZE:
        sent["urls"] = sent["urls"][-MAX_HISTORY_SIZE:]

def load_summary_state() -> dict:
    if not os.path.exists(SUMMARY_FILE):
        return {"last_summary_date": None, "pending": []}
    try:
        with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_summary_date": None, "pending": []}

# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg: str, session: requests.Session):
    if not TOKEN or TOKEN.startswith("TUTAJ"):
        log.warning("Brak poprawnego TOKEN Telegrama — pomijam wysyłanie.")
        return
    try:
        r = session.post(
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

def format_alert(store_name: str, name: str, price: str, link: str, preorder: bool) -> str:
    status = "🟣 <b>PRZEDPREMIERA</b>" if preorder else "🟢 <b>DOSTĘPNE TERAZ</b>"
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"<b>🔥 NOWY PRODUKT — {store_name.upper()} 🔥</b>\n\n"
        f"{status}\n\n"
        f"📦 <b>{name}</b>\n\n"
        f"💰 <b>{price}</b>\n\n"
        f"👉 <a href=\"{link}\">Zobacz w sklepie {store_name}</a>\n\n"
        f"<i>🕐 {ts}</i>"
    )

def categorize(name: str, full_text: str) -> str:
    combined = (name + " " + full_text).lower()
    for label, keywords in CATEGORIES:
        if not keywords:
            return label
        if any(kw in combined for kw in keywords):
            return label
    return "🔮 Inne Sealed"

def format_daily_summary(pending: list, day_str: str) -> str:
    if not pending:
        return f"<b>📊 PODSUMOWANIE DNIA (REBEL) — {day_str}</b>\n\nBrak nowych produktów na Rebelu dzisiaj. 😴"

    grouped: dict[str, list] = {}
    for p in pending:
        cat = p.get("category", "🔮 Inne Sealed")
        grouped.setdefault(cat, []).append(p)

    lines = [
        f"<b>📊 PODSUMOWANIE DNIA (REBEL) — {day_str}</b>\n",
        f"<b>Łącznie nowych produktów na Rebel.pl: {len(pending)}</b>\n",
    ]

    for label, _ in CATEGORIES:
        items = grouped.get(label)
        if not items:
            continue
        lines.append(f"\n{label}")
        for p in items:
            pre_tag = " 🟣" if p.get("preorder") else ""
            lines.append(f"• <a href=\"{p['link']}\">{p['name']}</a> — {p['price']}{pre_tag}")

    return "\n".join(lines)

# ── Logika Parsowania ─────────────────────────────────────────────────────────

def is_sealed(name: str, full_text: str) -> bool:
    combined = (name + " " + full_text).lower()
    if any(kw in combined for kw in BLOCKED_KEYWORDS):
        return False
    return any(kw in combined for kw in SEALED_KEYWORDS)

def is_preorder(full_text: str) -> bool:
    return any(kw in full_text.lower() for kw in PREORDER_KEYWORDS)

def is_sold_out(full_text: str) -> bool:
    t = full_text.lower()
    return any(s in t for s in UNAVAILABLE_SIGNALS)

def check_availability(full_text: str) -> bool:
    t = full_text.lower()
    if any(s in t for s in UNAVAILABLE_SIGNALS):
        return False
    if any(s in t for s in AVAILABLE_SIGNALS):
        return True
    return True

def extract_products(html: str, base_url: str, store: StoreConfig) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select(store.item_selector)

    if not container:
        container = soup.select(".product, .product-item, .product-box, [class*='product']")

    if not container:
        return []

    products = []
    for p in container:
        try:
            name = None
            for sel in store.name_selectors:
                el = p.select_one(sel)
                if el and el.get_text(strip=True):
                    name = el.get_text(strip=True)
                    break
            if not name:
                continue

            price = "brak ceny"
            for sel in store.price_selectors:
                el = p.select_one(sel)
                if el and el.get_text(strip=True):
                    price = el.get_text(strip=True)
                    break

            link = None
            for sel in store.link_selectors:
                a = p.select_one(sel)
                if a and a.get("href"):
                    href = a["href"]
                    link = href if href.startswith("http") else urljoin(base_url, href)
                    break
            
            if not link:
                continue

            full_text = p.get_text(" ", strip=True)
            available = check_availability(full_text)

            products.append({
                "store": store.name,
                "name": name,
                "price": price,
                "link": link,
                "full_text": full_text,
                "available": available,
            })
        except Exception as e:
            log.debug(f"[{store.name}] Błąd parsowania elementu: {e}")

    return products

# ── Główna Pętla Bota ─────────────────────────────────────────────────────────

def run_check_cycle(session: requests.Session, sent: dict, summary_state: dict) -> int:
    new_count = 0
    for store in STORES:
        for url in store.urls:
            log.info(f"[{store.name}] Sprawdzam: {url}")
            try:
                # Korzystamy z sesji, co chroni przed banami IP
                r = session.get(url, timeout=15)
                
                if r.status_code == 429:
                    log.warning(f"[{store.name}] Rate limit (429) — omijamy na ten cykl.")
                    continue
                if not r.ok:
                    log.warning(f"[{store.name}] HTTP {r.status_code} dla {url}")
                    continue

                products = extract_products(r.text, url, store)
                log.info(f"[{store.name}] Znaleziono produktów: {len(products)}")

                for p in products:
                    if is_already_sent(sent, p["name"], p["link"]):
                        continue
                    if not is_sealed(p["name"], p["full_text"]):
                        continue

                    preorder = is_preorder(p["full_text"])
                    sold_out = is_sold_out(p["full_text"])

                    if sold_out or (not preorder and not p["available"]):
                        mark_sent(sent, p["name"], p["link"])
                        continue

                    category = categorize(p["name"], p["full_text"])
                    msg = format_alert(p["store"], p["name"], p["price"], p["link"], preorder)

                    send_telegram(msg, session)
                    mark_sent(sent, p["name"], p["link"])
                    new_count += 1

                    # PRO ZMIANA: Zbieranie do podsumowania TYLKO dla sklepu Rebel
                    if p["store"].lower() == "rebel":
                        summary_state["pending"].append({
                            "store": p["store"],
                            "name": p["name"],
                            "price": p["price"],
                            "link": p["link"],
                            "category": category,
                            "preorder": preorder,
                        })

                    log.info(f"✅ [{p['store']}] Wysłano: {p['name']} | {p['price']}")
                    time.sleep(1)

            except requests.exceptions.RequestException as e:
                log.error(f"[{store.name}] Błąd sieci: {e}")

            time.sleep(2)

    return new_count

def maybe_send_summary(session: requests.Session, summary_state: dict):
    now = datetime.now()
    today_str = date.today().isoformat()

    if now.hour != SUMMARY_HOUR or summary_state.get("last_summary_date") == today_str:
        return

    day_display = date.today().strftime("%d.%m.%Y")
    msg = format_daily_summary(summary_state["pending"], day_display)
    send_telegram(msg, session)
    log.info(f"📊 Wysłano podsumowanie dnia dla Rebel ({len(summary_state['pending'])} produktów).")

    summary_state["last_summary_date"] = today_str
    summary_state["pending"] = []

def main():
    log.info("🚀 MULTI-STORE POKEMON TCG BOT (PRO) START")
    log.info(f"Śledzę {len(STORES)} polskich sklepów TCG. Cykl co {CHECK_EVERY}s.")

    sent = load_sent()
    summary_state = load_summary_state()

    # PRO ZMIANA: Utrzymywanie stałej sesji
    with requests.Session() as session:
        session.headers.update(HEADERS)
        
        while True:
            try:
                new_alerts = run_check_cycle(session, sent, summary_state)
                safe_save_json(SENT_FILE, sent)
                safe_save_json(SUMMARY_FILE, summary_state)

                maybe_send_summary(session, summary_state)
                safe_save_json(SUMMARY_FILE, summary_state)

                log.info(f"🎯 Zakończono cykl. Nowych alertów: {new_alerts}. Czekam {CHECK_EVERY}s...")
            except Exception as e:
                log.error(f"Błąd pętli głównej: {e}")

            time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
