import requests
from bs4 import BeautifulSoup
import time
import json
import os

print("START SNIPER BOT")

URL = "https://www.rebel.pl/pokemon"

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

CHECK_INTERVAL = 15  # co ile sekund (możesz dać np. 10)


def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.get(url, params={
            "chat_id": CHAT_ID,
            "text": msg
        })
    except Exception as e:
        print("ERROR TELEGRAM:", e)


def get_products():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    products = []

    items = soup.find_all("a")

    for item in items:
        try:
            name = item.text.strip()
            link = item.get("href")

            if not link or not name:
                continue

            if "/produkt/" in link:
                full_link = "https://www.rebel.pl" + link

                # sprawdzamy czy preorder
                text = item.text.lower()

                if "przedsprzedaż" in text or "preorder" in text:
                    status = "preorder"
                else:
                    status = "available"

                products.append({
                    "name": name,
                    "price": "Sprawdź cenę",
                    "link": full_link,
                    "status": status
                })

        except:
            continue

    return products


def load_seen():
    try:
        with open("seen.json", "r") as f:
            return json.load(f)
    except:
        return []


def save_seen(data):
    with open("seen.json", "w") as f:
        json.dump(data, f)


def main():
    seen = load_seen()

    while True:
        print("SPRAWDZAM...")

        products = get_products()

        for p in products:
            if p["link"] not in seen:

                if p["status"] == "available":
                    msg = f"🟢 W SPRZEDAŻY\n\n{p['name']}\n{p['price']}\n{p['link']}"
                else:
                    msg = f"🟡 PRZEDPREMIEROWE\n\n{p['name']}\n{p['price']}\n{p['link']}"

                send_telegram(msg)
                seen.append(p["link"])

        save_seen(seen)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()