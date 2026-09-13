import os
import time
import json
import logging
import ssl
import urllib3
from dataclasses import dataclass
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import cloudscraper
from bs4 import BeautifulSoup

# ── Globalne naprawienie problemów z SSL i certyfikatami ──────────────────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Inicjalizacja Scrapera z nagłówkami User-Agent ───────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
}

scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)
scraper.headers.update(HEADERS)

# ── Konfiguracja Telegrama & Aplikacji ───────────────────────────────────────

TOKEN   = "8641671766:AAEfRWe-lHc_8LLTA-rDecW3NjooDmENOl4"
CHAT_ID = "-1003743099672"


SENT_FILE = "tcg_sent.json"
SUMMARY_FILE = "tcg_summary.json"
CHECK_EVERY = 300       # 5 minut
SUMMARY_HOUR = 18       # Godzina podsumowania
MAX_HISTORY_SIZE = 5000 

# ── Definicja Sklepów TCG ────────────────────────────────────────────────────

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
        urls=["https://www.rebel.pl/pokemon"],
        item_selector="div.product, div.product-box, .productCard",
        name_selectors=[".product-name", "h2", "h3", ".title"],
        price_selectors=[".price", ".product-price", ".amount"],
        link_selectors=["a.product-name", "a[href*='/pokemon/']", "a[href]"]
    ),
    StoreConfig(
        name="LofiCards",
        urls=["https://loficards.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price .amount", ".price", "bdi"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="PokeTrader",
        urls=["https://poketrader.eu/?s=pokemon&post_type=product"],
        item_selector="li.product, div.product-grid-item",
        name_selectors=[".product-title", ".woocommerce-loop-product__title", "h2"],
        price_selectors=[".price .amount", ".price", "bdi"],
        link_selectors=["a.product-title-link", "a[href]"]
    ),
    StoreConfig(
        name="BoosterPoint",
        urls=["https://boosterpoint.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price .amount", ".price", "bdi"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="Flamberg",
        urls=["https://flamberg.com.pl/pol_m_Karty-Kolekcjonerskie_Pokemon-TCG-381.html"],
        item_selector="div.product_data, div.product, div.product-layout",
        name_selectors=[".product-name", ".name", "h3", "h4"],
        price_selectors=[".price_value", ".price", ".price-new"],
        link_selectors=["a.product-name", "a[href]"]
    ),
    StoreConfig(
        name="3Trolle",
        urls=["https://3trolle.pl/szukaj?controller=search&s=pokemon"],
        item_selector="article.product-miniature, div.product-container",
        name_selectors=[".product-title", ".h3.product-title", "h3"],
        price_selectors=[".current-price", ".product-price-and-shipping", ".price", ".product-price"],
        link_selectors=["a.product-thumbnail", ".product-title a", "a[href]"]
    ),
    StoreConfig(
        name="PokeCollect",
        urls=["https://pokecollect.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price .amount", ".price", "bdi"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="Świat Kart",
        urls=["https://swiatkart.com.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price .amount", ".price", "bdi"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="Gry Bez Prądu",
        urls=["https://grybezpradu.eu/pl/s?q=pokemon"],
        item_selector="div.product-main, div.product-icon, div.product-inner",
        name_selectors=[".product-name", "span.product-name"],
        price_selectors=[".price em", ".price", "em"],
        link_selectors=["a.product-name", "a[href*='/pl/p/']"]
    )
]

# ── Sygnały i Filtrowanie ────────────────────────────────────────────────────

UNAVAILABLE_SIGNALS = [
    "niedostępny", "wyprzedany", "brak w magazynie", 
    "out of stock", "sold out", "brak na stanie", "niedostepny"
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
    "protector", "binder", "page",
    "wszystkie nowości", "kategorie", "promocje", "bestsellery"
]

PREORDER_KEYWORDS = [
    "przedsprzedaż", "preorder", "pre-order", "zapowiedź",
    "wkrótce", "dostępny od", "premiera", "planowana premiera",
    "wysyłka od", "wysyłka w"
]

CATEGORIES = [
    ("📦 Booster Boxy / Display",    ["booster box", "display"]),
    ("🎁 Elite Trainer Boxy / Tiny", ["etb", "elite trainer box", "tin"]),
    ("🎴 Blistry / Packi",           ["blister", "booster pack", "build & battle"]),
    ("💎 Kolekcje Premium",          ["premium collection", "ultra premium", "collection box", "bundle"]),
    ("🃏 Decki / Startery",          ["starter deck", "theme deck"]),
    ("🔮 Inne Sealed",               []),
]

# ── Funkcje Pomocnicze & Zapis Stanu ──────────────────────────────────────────

def normalize_name(name: str) -> str:
    return " ".join(name.lower().split())

def canonical_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def safe_save_json(filepath: str, data: dict):
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
            return {"urls": raw.get("urls", []), "names": raw.get("names", [])} if isinstance(raw, dict) else {"urls": raw, "names": []}
    except Exception:
        return {"urls": [], "names": []}

def is_already_sent(sent: dict, name: str, url: str) -> bool:
    return normalize_name(name) in sent["names"] or canonical_url(url) in sent["urls"]

def mark_sent(sent: dict, name: str, url: str):
    sent["names"].append(normalize_name(name))
    sent["urls"].append(canonical_url(url))
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

def send_telegram(msg: str):
    if not TOKEN or TOKEN.startswith("TUTAJ"): 
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID, 
                "text": msg, 
                "parse_mode": "HTML", 
                "disable_web_page_preview": True
            },
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram błąd: {e}")

def format_alert(store_name: str, name: str, price: str, link: str, preorder: bool) -> str:
    status = "🟣 <b>PRZEDPREMIERA</b>" if preorder else "🟢 <b>DOSTĘPNE TERAZ</b>"
    return (
        f"<b>🔥 NOWY PRODUKT — {store_name.upper()} 🔥</b>\n\n{status}\n\n"
        f"📦 <b>{name}</b>\n\n💰 <b>{price}</b>\n\n"
        f"👉 <a href=\"{link}\">Zobacz w sklepie {store_name}</a>\n\n"
        f"<i>🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
    )

def categorize(name: str, full_text: str) -> str:
    combined = (name + " " + full_text).lower()
    for label, keywords in CATEGORIES:
        if keywords and any(kw in combined for kw in keywords): 
            return label
    return "🔮 Inne Sealed"

def format_daily_summary(pending: list, day_str: str) -> str:
    if not pending: 
        return f"<b>📊 PODSUMOWANIE DNIA (REBEL) — {day_str}</b>\n\nBrak nowych produktów na Rebelu dzisiaj. 😴"
    grouped = {}
    for p in pending: 
        grouped.setdefault(p.get("category", "🔮 Inne Sealed"), []).append(p)
    lines = [f"<b>📊 PODSUMOWANIE DNIA (REBEL) — {day_str}</b>\n", f"<b>Łącznie nowych produktów: {len(pending)}</b>\n"]
    for label, _ in CATEGORIES:
        if items := grouped.get(label):
            lines.append(f"\n{label}")
            for p in items: 
                lines.append(f"• <a href=\"{p['link']}\">{p['name']}</a> — {p['price']}{' 🟣' if p.get('preorder') else ''}")
    return "\n".join(lines)

# ── Logika Parsowania HTML ───────────────────────────────────────────────────

def is_sealed(name: str, full_text: str) -> bool:
    combined = (name + " " + full_text).lower()
    return not any(kw in combined for kw in BLOCKED_KEYWORDS) and any(kw in combined for kw in SEALED_KEYWORDS)

def extract_products(html: str, base_url: str, store: StoreConfig) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select(store.item_selector)
    
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

            price = "Brak ceny"
            for sel in store.price_selectors:
                el = p.select_one(sel)
                if el and el.get_text(strip=True):
                    price_text = " ".join(el.get_text(strip=True).split())
                    if any(char.isdigit() for char in price_text):
                        price = price_text
                        break

            link = None
            for sel in store.link_selectors:
                a = p.select_one(sel)
                if a and a.get("href"):
                    href = a["href"].strip()
                    link = href if href.startswith("http") else urljoin(base_url, href)
                    break
            if not link:
                continue

            full_text = p.get_text(" ", strip=True).lower()
            available = not any(s in full_text for s in UNAVAILABLE_SIGNALS)

            products.append({
                "store": store.name,
                "name": name,
                "price": price,
                "link": link,
                "full_text": full_text,
                "available": available,
            })
        except Exception:
            pass
    return products

# ── Główna Pętla Bota ─────────────────────────────────────────────────────────

def run_check_cycle(sent: dict, summary_state: dict) -> int:
    new_count = 0
    for store in STORES:
        for url in store.urls:
            log.info(f"[{store.name}] Sprawdzam: {url}")
            try:
                r = scraper.get(url, timeout=15)
                if r.status_code != 200:
                    log.warning(f"[{store.name}] HTTP {r.status_code} dla {url}")
                    continue

                products = extract_products(r.text, url, store)
                log.info(f"[{store.name}] Znaleziono produktów: {len(products)}")

                for p in products:
                    if is_already_sent(sent, p["name"], p["link"]) or not is_sealed(p["name"], p["full_text"]):
                        continue

                    preorder = any(kw in p["full_text"] for kw in PREORDER_KEYWORDS)
                    
                    if any(s in p["full_text"] for s in UNAVAILABLE_SIGNALS) or (not preorder and not p["available"]):
                        mark_sent(sent, p["name"], p["link"])
                        continue

                    msg = format_alert(p["store"], p["name"], p["price"], p["link"], preorder)
                    send_telegram(msg)
                    mark_sent(sent, p["name"], p["link"])
                    new_count += 1

                    if p["store"].lower() == "rebel":
                        summary_state["pending"].append({
                            "store": p["store"], 
                            "name": p["name"], 
                            "price": p["price"], 
                            "link": p["link"], 
                            "category": categorize(p["name"], p["full_text"]), 
                            "preorder": preorder
                        })
                    log.info(f"✅ [{p['store']}] Wysłano: {p['name']} | {p['price']}")
                    time.sleep(1)

                if products:
                    break

            except Exception as e:
                log.error(f"[{store.name}] Błąd podczas pobierania {url}: {e}")
            time.sleep(1.5)
    return new_count

def main():
    log.info("🚀 MULTI-STORE TCG BOT (Zaufane Sklepy) START")
    sent = load_sent()
    summary_state = load_summary_state()

    while True:
        try:
            new_alerts = run_check_cycle(sent, summary_state)
            safe_save_json(SENT_FILE, sent)
            
            if datetime.now().hour == SUMMARY_HOUR and summary_state.get("last_summary_date") != date.today().isoformat():
                send_telegram(format_daily_summary(summary_state["pending"], date.today().strftime("%d.%m.%Y")))
                summary_state.update({"last_summary_date": date.today().isoformat(), "pending": []})
            
            safe_save_json(SUMMARY_FILE, summary_state)
            log.info(f"🎯 Zakończono cykl. Nowych alertów: {new_alerts}. Czekam {CHECK_EVERY}s...\n")
        except Exception as e:
            log.error(f"Błąd pętli głównej: {e}")
        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
