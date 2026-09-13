import os
import time
import json
import logging
import urllib3
from dataclasses import dataclass
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

# Wyłączenie ostrzeżeń o braku certyfikatu SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Konfiguracja Telegrama & Aplikacji ───────────────────────────────────────

TOKEN   = "8641671766:AAEfRWe-lHc_8LLTA-rDecW3NjooDmENOl4"
CHAT_ID = "-1003743099672"

SENT_FILE = "tcg_sent.json"
SUMMARY_FILE = "tcg_summary.json"
CHECK_EVERY = 300       # 5 minut (300 sekund)
SUMMARY_HOUR = 18       # Godzina wysyłki podsumowania
MAX_HISTORY_SIZE = 5000 

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
}

# ── Definicja Sklepów TCG (Zaufane z UmbreNews) ───────────────────────────────

@dataclass
class StoreConfig:
    name: str
    urls: list[str]
    item_selector: str
    name_selectors: list[str]
    price_selectors: list[str]
    link_selectors: list[str]

# Uniwersalne selektory radzące sobie z 90% polskich sklepów e-commerce
UNI_ITEM = ".product, .product-item, .product-box, .product-miniature, .product-wrapper, li.product"
UNI_NAME = [".product-name", ".name", ".product-title", "h2", "h3"]
UNI_PRICE = [".price", ".product-price", ".price-new", ".amount"]
UNI_LINK = ["a.product-name", "a.name", "a.title", "a[href]"]

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
        name="LofiCards",
        urls=["https://loficards.pl/kategoria-produktu/pokemon-tcg/"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="PokeTrader",
        urls=["https://poketrader.eu/kategoria/pokemon-tcg/"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="BoosterPoint",
        urls=["https://boosterpoint.pl/kategoria-produktu/pokemon-tcg/"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="Flamberg",
        urls=["https://flamberg.com.pl/category/gry-karciane-pokemon-tcg"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="3Trolle",
        urls=["https://3trolle.pl/113-pokemon"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="PokeCollect",
        urls=["https://pokecollect.pl/kategoria-produktu/pokemon-tcg/"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="Świat Kart",
        urls=["https://swiatkart.com.pl/kategoria-produktu/pokemon-tcg/"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    ),
    StoreConfig(
        name="Gry Bez Prądu",
        urls=["https://grybezpradu.eu/pl/c/Pokemon-TCG/88"],
        item_selector=UNI_ITEM,
        name_selectors=UNI_NAME,
        price_selectors=UNI_PRICE,
        link_selectors=UNI_LINK
    )
]

# ── Sygnały i Filtrowanie ────────────────────────────────────────────────────

UNAVAILABLE_SIGNALS = [
    "niedostępny", "wyprzedany", "brak w magazynie", 
    "out of stock", "sold out", "brak na stanie", "niedostepny"
]

AVAILABLE_SIGNALS = [
    "dodaj do koszyka", "kup teraz", "add to cart", "buy now",
    "zamów", "do koszyka", "kupuj"
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
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

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
    if len(sent["names"]) > MAX_HISTORY_SIZE: sent["names"] = sent["names"][-MAX_HISTORY_SIZE:]
    if len(sent["urls"]) > MAX_HISTORY_SIZE: sent["urls"] = sent["urls"][-MAX_HISTORY_SIZE:]

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
    if not TOKEN or TOKEN.startswith("TUTAJ"): return
    try:
        session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10, verify=False
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
        if keywords and any(kw in combined for kw in keywords): return label
    return "🔮 Inne Sealed"

def format_daily_summary(pending: list, day_str: str) -> str:
    if not pending: return f"<b>📊 PODSUMOWANIE DNIA (REBEL) — {day_str}</b>\n\nBrak nowych produktów na Rebelu dzisiaj. 😴"
    grouped = {}
    for p in pending: grouped.setdefault(p.get("category", "🔮 Inne Sealed"), []).append(p)
    lines = [f"<b>📊 PODSUMOWANIE DNIA (REBEL) — {day_str}</b>\n", f"<b>Łącznie nowych produktów: {len(pending)}</b>\n"]
    for label, _ in CATEGORIES:
        if items := grouped.get(label):
            lines.append(f"\n{label}")
            for p in items: lines.append(f"• <a href=\"{p['link']}\">{p['name']}</a> — {p['price']}{' 🟣' if p.get('preorder') else ''}")
    return "\n".join(lines)

# ── Logika Parsowania ─────────────────────────────────────────────────────────

def is_sealed(name: str, full_text: str) -> bool:
    combined = (name + " " + full_text).lower()
    return not any(kw in combined for kw in BLOCKED_KEYWORDS) and any(kw in combined for kw in SEALED_KEYWORDS)

def extract_products(html: str, base_url: str, store: StoreConfig) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select(store.item_selector)
    if not container: container = soup.select(".product, .product-item, .product-box, [class*='product']")
    
    products = []
    for p in container:
        try:
            name = next((el.get_text(strip=True) for sel in store.name_selectors if (el := p.select_one(sel)) and el.get_text(strip=True)), None)
            if not name: continue
            
            price = next((el.get_text(strip=True) for sel in store.price_selectors if (el := p.select_one(sel)) and el.get_text(strip=True)), "brak ceny")
            
            link = next((a["href"] if a["href"].startswith("http") else urljoin(base_url, a["href"]) 
                         for sel in store.link_selectors if (a := p.select_one(sel)) and a.get("href")), None)
            if not link: continue

            full_text = p.get_text(" ", strip=True).lower()
            available = not any(s in full_text for s in UNAVAILABLE_SIGNALS)
            
            products.append({
                "store": store.name, "name": name, "price": price, 
                "link": link, "full_text": full_text, "available": available,
            })
        except Exception:
            pass
    return products

# ── Główna Pętla Bota ─────────────────────────────────────────────────────────

def run_check_cycle(session: requests.Session, sent: dict, summary_state: dict) -> int:
    new_count = 0
    for store in STORES:
        for url in store.urls:
            log.info(f"[{store.name}] Sprawdzam: {url}")
            try:
                r = session.get(url, timeout=15, verify=False)
                if not r.ok: continue

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
                    send_telegram(msg, session)
                    mark_sent(sent, p["name"], p["link"])
                    new_count += 1

                    if p["store"].lower() == "rebel":
                        summary_state["pending"].append({
                            "store": p["store"], "name": p["name"], "price": p["price"], 
                            "link": p["link"], "category": categorize(p["name"], p["full_text"]), "preorder": preorder
                        })
                    log.info(f"✅ [{p['store']}] Wysłano: {p['name']}")
                    time.sleep(1)

            except Exception as e:
                log.error(f"[{store.name}] Błąd: {e}")
            time.sleep(2)
    return new_count

def main():
    log.info(f"🚀 MULTI-STORE TCG BOT (Zaufane Sklepy) START")
    sent = load_sent()
    summary_state = load_summary_state()

    with requests.Session() as session:
        session.headers.update(HEADERS)
        while True:
            try:
                new_alerts = run_check_cycle(session, sent, summary_state)
                safe_save_json(SENT_FILE, sent)
                
                if datetime.now().hour == SUMMARY_HOUR and summary_state.get("last_summary_date") != date.today().isoformat():
                    send_telegram(format_daily_summary(summary_state["pending"], date.today().strftime("%d.%m.%Y")), session)
                    summary_state.update({"last_summary_date": date.today().isoformat(), "pending": []})
                
                safe_save_json(SUMMARY_FILE, summary_state)
                log.info(f"🎯 Zakończono cykl. Nowych alertów: {new_alerts}. Czekam {CHECK_EVERY}s...")
            except Exception as e:
                log.error(f"Błąd pętli głównej: {e}")
            time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    main()
