import requests
from bs4 import BeautifulSoup
import time
import os

TOKEN = os.environ.get("TOKEN")
CHAT_ID = "-1003743099672"

sent = set()

def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    })

def format_msg(name, price, link, preorder):
    status = "🟣 <b>PRZEDPREMIERA</b>" if preorder else "🟢 <b>DOSTĘPNE</b>"

    return f"""
<b>🔥 NOWY PRODUKT - REBEL 🔥</b>

{status}

📦 <b>{name}</b>

💰 <b>{price}</b>

👉 <a href="{link}">Zobacz produkt</a>
"""

def check_rebel():
    print("Sprawdzam Rebel...")
    url = "https://www.rebel.pl/pokemon"

    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, "html.parser")

        products = soup.select(".product")

        for p in products:
            try:
                name = p.select_one(".product-name").text.strip()
                price = p.select_one(".price").text.strip()
                link = "https://www.rebel.pl" + p.select_one("a")["href"]

                text_all = p.get_text().lower()

                # 🎯 wykrywanie preorder
                preorder = any(x in text_all for x in [
                    "przedsprzedaż",
                    "preorder",
                    "zapowiedź"
                ])

                if link in sent:
                    continue

                sent.add(link)

                send(format_msg(name, price, link, preorder))

            except:
                continue

    except Exception as e:
        print("Błąd Rebel:", e)

print("🚀 START REBEL BOT")

send("🚀 TEST KANAŁ OKAZJI")

while True:
    try:
        check_rebel()
    except Exception as e:
        print("Błąd:", e)

    time.sleep(30)