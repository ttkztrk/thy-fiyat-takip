"""
THY Fiyat Takip Scripti (Travelpayouts / Aviasales Data API ile)
==================================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) -> Sinop (NOP) rotasını takip eder.

Amadeus self-service API 17 Temmuz 2026'da tamamen kapandığı için bu script
Travelpayouts'un (Aviasales) ücretsiz Data API'sini kullanıyor.

ÖNEMLİ NOT: Sinop gibi az aranan bir rota için "NRW havalimanı -> Sinop"
şeklinde direkt arama yapıldığında cache'te veri bulunamayabilir (bu API
gerçek zamanlı değil, kullanıcıların geçmiş aramalarından oluşan bir
cache'tir). Bu yüzden rota ikiye bölünüyor:
    1) Kalkış havalimanı -> İstanbul (IST)   [çok aranan, bol veri]
    2) İstanbul (IST) -> Sinop (NOP)          [THY'nin iç hat seferi]
ve iki bacağın en ucuz fiyatları toplanarak TAHMİNİ bir toplam fiyat
hesaplanıyor. Bu, THY'den tek PNR ile alınacak gerçek birleşik bilet
fiyatından farklı olabilir (genelde birleşik bilet daha ucuzdur) -- bu
yüzden script sadece "erken uyarı" amaçlıdır, bilet almadan önce mutlaka
THY'nin sitesinden gerçek fiyatı teyit et.
"""

import os
import time
import smtplib
from email.mime.text import MIMEText
from datetime import date

import requests

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT = os.environ.get("TRANSIT_AIRPORT", "IST")        # İstanbul Havalimanı
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")  # Sinop
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "200"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "4"))  # kaç ay ileriye kadar bakılsın
CURRENCY = os.environ.get("CURRENCY", "eur")

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")


# ====================== TRAVELPAYOUTS API ======================

def cheapest_for_month(origin: str, destination: str, month_str: str):
    """Belirli bir ay (YYYY-MM) için origin->destination cache'teki en ucuz
    fiyatı döner. Veri yoksa None döner."""
    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": month_str,
        "currency": CURRENCY,
        "token": TRAVELPAYOUTS_TOKEN,
    }
    resp = requests.get(
        "https://api.travelpayouts.com/v1/prices/cheap",
        params=params,
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"  [Uyarı] {origin}->{destination} ({month_str}): "
              f"{resp.status_code} {resp.text[:150]}")
        return None

    dest_data = resp.json().get("data", {}).get(destination)
    if not dest_data:
        return None

    # dest_data örn: {"0": {...direkt...}, "1": {...1 aktarmalı...}}
    # En ucuz olanı seç.
    cheapest = min(dest_data.values(), key=lambda x: x["price"])
    return cheapest


def build_months():
    months = []
    today = date.today()
    for i in range(MONTHS_AHEAD):
        total_month = today.month - 1 + i
        year = today.year + total_month // 12
        month = total_month % 12 + 1
        months.append(f"{year}-{month:02d}")
    return months


# ====================== BİLDİRİMLER ======================

def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Bilgi] Telegram ayarları eksik, atlanıyor.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=20)
    except Exception as e:
        print(f"  [Hata] Telegram gönderilemedi: {e}")


def send_email(subject: str, body: str) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD or not EMAIL_TO:
        print("  [Bilgi] E-posta ayarları eksik, atlanıyor.")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"  [Hata] E-posta gönderilemedi: {e}")


# ====================== ANA AKIŞ ======================

def main():
    print("THY fiyat takip scripti başlıyor (Travelpayouts/Aviasales Data API)...")
    months = build_months()

    cheap_offers = []
    for raw_origin in ORIGIN_AIRPORTS:
        origin = raw_origin.strip()
        for month in months:
            print(f"Kontrol: {origin} -> {TRANSIT_AIRPORT} -> {DESTINATION_AIRPORT}, {month}")

            leg1 = cheapest_for_month(origin, TRANSIT_AIRPORT, month)
            time.sleep(0.3)
            leg2 = cheapest_for_month(TRANSIT_AIRPORT, DESTINATION_AIRPORT, month)
            time.sleep(0.3)

            if not leg1 or not leg2:
                print("  Bu ay için yeterli cache verisi yok, atlanıyor.")
                continue

            total_price = leg1["price"] + leg2["price"]
            if total_price <= PRICE_THRESHOLD:
                cheap_offers.append({
                    "origin": origin,
                    "month": month,
                    "leg1_price": leg1["price"],
                    "leg1_date": leg1.get("departure_at", "?"),
                    "leg2_price": leg2["price"],
                    "leg2_date": leg2.get("departure_at", "?"),
                    "total": total_price,
                })

    if cheap_offers:
        cheap_offers.sort(key=lambda x: x["total"])
        lines = [
            f"{PRICE_THRESHOLD:.0f} {CURRENCY.upper()} altında TAHMİNİ "
            f"{len(cheap_offers)} kombinasyon bulundu (iki bacağın toplamı, "
            f"gerçek birleşik bilet fiyatı farklı olabilir):\n"
        ]
        for o in cheap_offers[:15]:
            lines.append(
                f"• {o['origin']} → İstanbul: {o['leg1_price']:.0f} {CURRENCY.upper()} "
                f"({o['leg1_date']}) | İstanbul → Sinop: {o['leg2_price']:.0f} "
                f"{CURRENCY.upper()} ({o['leg2_date']}) | TOPLAM ≈ {o['total']:.0f} "
                f"{CURRENCY.upper()} | Ay: {o['month']}"
            )
        lines.append("\n⚠️ Bilet almadan önce THY sitesinden gerçek fiyatı teyit et.")
        message = "\n".join(lines)
        print(message)
        send_telegram(message)
        send_email("✈️ Ucuz THY Bileti Olabilir!", message)
    else:
        print(f"Bu çalıştırmada {PRICE_THRESHOLD:.0f} {CURRENCY.upper()} altında "
              f"kombinasyon bulunamadı (veya cache'te yeterli veri yoktu).")


if __name__ == "__main__":
    main()
