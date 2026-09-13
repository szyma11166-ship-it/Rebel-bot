import os
import time
import json
import logging
import urllib3
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Set, Optional
from urllib.parse import urljoin, urlparse

import requests
import cloudscraper
from bs4 import BeautifulSoup

# Wyłączenie ostrzeżeń o braku weryfikacji SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# KONFIGURACJA LOGOWANIA
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

# ==========================================
# INICJALIZACJA SCRAPERA (Obejście Cloudflare / HTTP 403)
# ==========================================
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# ==========================================
# KONFIGURACJA TELEGRAMA & APLIKACJI
# ==========================================

TOKEN   = "8641671766:AAEfRWe-lHc_8LLTA-rDecW3NjooDmENOl4"
CHAT_ID = "-1003743099672"

def send_telegram_message(text: str):
    """Wysyła powiadomienie na Telegram, jeśli podano token i chat_id w zmiennych środowiskowych."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Błąd wysyłania na Telegram: {e}")

# ==========================================
# STRUKTURY DANYCH
# ==========================================
@dataclass
class StoreConfig:
    name: str
    urls: List[str]
    item_selector: str
    name_selectors: List[str]
    price_selectors: List[str]
    link_selectors: List[str]

@dataclass
class Product:
    store_name: str
    title: str
    price: str
    url: str

    def unique_id(self) -> str:
        return f"{self.store_name}:{self.title}"

# ==========================================
# KONFIGURACJA SKLEPÓW (Wyszukiwarki + Selectory CSS)
# ==========================================
STORES: List[StoreConfig] = [
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
        price_selectors=[".price", ".amount"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="PokeTrader",
        urls=["https://poketrader.eu/?s=pokemon&post_type=product"],
        item_selector="li.product, div.product-grid-item",
        name_selectors=[".product-title", ".woocommerce-loop-product__title", "h2"],
        price_selectors=[".price", ".amount"],
        link_selectors=["a.product-title-link", "a[href]"]
    ),
    StoreConfig(
        name="BoosterPoint",
        urls=["https://boosterpoint.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price", ".amount"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="Flamberg",
        urls=["https://flamberg.com.pl/szukaj?q=pokemon"],
        item_selector="div.product-layout, div.product-thumb, div.product",
        name_selectors=[".caption h4", ".name", "h4", "h3"],
        price_selectors=[".price", ".price-new"],
        link_selectors=["a[href*='/product/']", ".caption a", "a[href]"]
    ),
    StoreConfig(
        name="3Trolle",
        urls=["https://3trolle.pl/szukaj?controller=search&s=pokemon"],
        item_selector="article.product-miniature, div.product-container",
        name_selectors=[".product-title", ".h3.product-title", "h3"],
        price_selectors=[".price", ".product-price"],
        link_selectors=["a.product-thumbnail", ".product-title a", "a[href]"]
    ),
    StoreConfig(
        name="PokeCollect",
        urls=["https://pokecollect.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price", ".amount"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="Świat Kart",
        urls=["https://swiatkart.com.pl/?s=pokemon&post_type=product"],
        item_selector="li.product",
        name_selectors=[".woocommerce-loop-product__title", "h2", "h3"],
        price_selectors=[".price", ".amount"],
        link_selectors=["a.woocommerce-LoopProduct-link", "a[href]"]
    ),
    StoreConfig(
        name="Gry Bez Prądu",
        urls=["https://grybezpradu.eu/pl/s?q=pokemon"],
        item_selector="div.product-main, div.product-icon, div.product-inner",
        name_selectors=[".product-name", "span.product-name"],
        price_selectors=[".price", "em"],
        link_selectors=["a.product-name", "a[href*='/pl/p/']"]
    )
]

# ==========================================
# LOGIKA SCRAPINGU
# ==========================================
def extract_product(store: StoreConfig, element, base_url: str) -> Optional[Product]:
    """Wyciąga pojedynczy produkt z elementu HTML."""
    title = None
    for sel in store.name_selectors:
        el = element.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break

    if not title:
        return None

    price = "Brak ceny"
    for sel in store.price_selectors:
        el = element.select_one(sel)
        if el and el.get_text(strip=True):
            price = " ".join(el.get_text(strip=True).split())
            break

    link = base_url
    for sel in store.link_selectors:
        el = element.select_one(sel)
        if el and el.get('href'):
            link = urljoin(base_url, el['href'])
            break

    return Product(store_name=store.name, title=title, price=price, url=link)

def check_store(store: StoreConfig) -> List[Product]:
    """Pobiera stronę sklepu i wyciąga znalezione produkty."""
    found_products: List[Product] = []

    for url in store.urls:
        logging.info(f"[{store.name}] Sprawdzam: {url}")
        try:
            response = scraper.get(url, timeout=12)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                items = soup.select(store.item_selector)

                for item in items:
                    prod = extract_product(store, item, url)
                    if prod and prod.title not in [p.title for p in found_products]:
                        found_products.append(prod)

                logging.info(f"[{store.name}] Znaleziono produktów: {len(found_products)}")
                if found_products:
                    break
            else:
                logging.warning(f"[{store.name}] HTTP {response.status_code} dla {url}")

        except Exception as e:
            logging.error(f"[{store.name}] Błąd podczas połączenia z {url}: {e}")

    return found_products

def send_alert(product: Product):
    """Wysyła log oraz powiadomienie na Telegram."""
    msg_log = f"✅ [{product.store_name}] Wysłano: {product.title} | {product.price}"
    logging.info(msg_log)

    tg_msg = (
        f"<b>[{product.store_name}]</b> Nowy produkt!\n"
        f"<b>Nazwa:</b> {product.title}\n"
        f"<b>Cena:</b> {product.price}\n"
        f"<a href='{product.url}'>Zobacz produkt</a>"
    )
    send_telegram_message(tg_msg)

# ==========================================
# GŁÓWNA PĘTLA BOTA
# ==========================================
def main():
    logging.info("🚀 MULTI-STORE TCG BOT (Zaufane Sklepy) START")
    seen_products: Set[str] = set()
    interval_seconds = 300  # Pętla co 5 minut

    while True:
        new_alerts = 0
        for store in STORES:
            products = check_store(store)
            for product in products:
                prod_id = product.unique_id()
                if prod_id not in seen_products:
                    send_alert(product)
                    seen_products.add(prod_id)
                    new_alerts += 1

            time.sleep(1.5)

        logging.info(f"🎯 Zakończono cykl. Nowych alertów: {new_alerts}. Czekam {interval_seconds}s...\n")
        time.sleep(interval_seconds)

if __name__ == "__main__":
    main()
