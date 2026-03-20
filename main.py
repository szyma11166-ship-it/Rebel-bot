print("START BOT")
import requests
from bs4 import BeautifulSoup
import time
import json
import os

URL = "https://www.rebel.pl/pokemon"

TOKEN = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_products():
    r = requests.get(URL)
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

                products.append({
                    "name": name,
                    "price": "Sprawdź na stronie",
                    "link": full_link
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
        products = get_products()

        for p in products:
            if p["link"] not in seen:
                msg = f"🔥 Nowy produkt!\n\n{p['name']}\n{p['price']}\n{p['link']}"
                send_telegram(msg)
                seen.append(p["link"])

        save_seen(seen)
        time.sleep(300)

if __name__ == "__main__":
    main()
