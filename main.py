"""
THY Fiyat Takip Scripti (Travelpayouts / Aviasales Data API ile)
==================================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) <-> Sinop (NOP) rotasını HER İKİ
YÖNDE (gidiş ve dönüş) AYRI AYRI takip eder. 6 ay ileriye bakar.

Günde 3 kez çalışır. Bildirim mantığı:
  - 200 EUR altı bilet bulunursa -> HER ZAMAN Telegram + E-posta UYARI gönderilir.
  - Fiyatlar bir önceki taramaya göre değiştiyse -> Telegram özet gönderilir.
  - Hiçbir değişiklik yoksa -> bildirim gönderilmez (Telegram dolmasın).

Fiyat geçmişi /tmp/last_prices.json dosyasında saklanır.
(GitHub Actions her çalıştırmada temiz bir ortam başlatır, bu yüzden
geçmiş fiyatları GitHub Actions Cache'te saklıyoruz.)
"""

import os
import json
import time
import smtplib
from email.mime.text import MIMEText
from datetime import date
from collections import defaultdict
from pathlib import Path

import requests

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "200"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "6"))
CURRENCY = os.environ.get("CURRENCY", "eur")
# Fiyat değişikliği eşiği: bu EUR'dan fazla değişirse bildirim gönderilir
CHANGE_THRESHOLD = float(os.environ.get("CHANGE_THRESHOLD", "5"))

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")

# Geçmiş fiyatların saklandığı dosya (GitHub Actions cache ile kalıcı hale getirilir)
PRICES_FILE = Path(os.environ.get("PRICES_FILE", "/tmp/last_prices.json"))


# ====================== GEÇMİŞ FİYATLAR ======================

def load_last_prices() -> dict:
    if PRICES_FILE.exists():
        try:
            return json.loads(PRICES_FILE.read_text())
        except Exception:
            pass
    return {}


def save_prices(prices: dict):
    try:
        PRICES_FILE.write_text(json.dumps(prices, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"  [Uyarı] Fiyat geçmişi kaydedilemedi: {e}")


def price_key(label, month):
    return f"{label}|{month}"


# ====================== TRAVELPAYOUTS API ======================

def cheapest_for_month(origin: str, destination: str, month_str: str):
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
    return min(dest_data.values(), key=lambda x: x["price"])


def build_months():
    months = []
    today = date.today()
    for i in range(MONTHS_AHEAD):
        total_month = today.month - 1 + i
        year = today.year + total_month // 12
        month = total_month % 12 + 1
        months.append(f"{year}-{month:02d}")
    return months


def check_direction(label, start, mid, end, month):
    leg1 = cheapest_for_month(start, mid, month)
    time.sleep(0.3)
    leg2 = cheapest_for_month(mid, end, month)
    time.sleep(0.3)
    if not leg1 or not leg2:
        return None
    return {
        "label": label,
        "month": month,
        "leg1_price": leg1["price"],
        "leg1_date": leg1.get("departure_at", "?"),
        "leg2_price": leg2["price"],
        "leg2_date": leg2.get("departure_at", "?"),
        "total": leg1["price"] + leg2["price"],
    }


# ====================== BİLDİRİMLER ======================

def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Bilgi] Telegram ayarları eksik, atlanıyor.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=20)
        print("  [Telegram] Mesaj gönderildi.")
    except Exception as e:
        print(f"  [Hata] Telegram gönderilemedi: {e}")


def send_email(subject: str, body: str) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD or not EMAIL_TO:
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print("  [E-posta] Gönderildi.")
    except Exception as e:
        print(f"  [Hata] E-posta gönderilemedi: {e}")


# ====================== ANA AKIŞ ======================

def main():
    print("THY fiyat takip scripti başlıyor (6 aylık tarama)...")
    months = build_months()
    last_prices = load_last_prices()
    current_prices = {}

    cheap_offers = []       # 200€ altındakiler
    changed_offers = []     # Fiyatı değişenler
    all_offers = defaultdict(list)

    for raw_origin in ORIGIN_AIRPORTS:
        origin = raw_origin.strip()
        for month in months:
            # GİDİŞ
            print(f"Kontrol (Gidiş): {origin} -> {TRANSIT_AIRPORT} -> {DESTINATION_AIRPORT}, {month}")
            outbound = check_direction(
                f"Gidiş ({origin}→{DESTINATION_AIRPORT})",
                origin, TRANSIT_AIRPORT, DESTINATION_AIRPORT, month,
            )
            if outbound:
                print(f"  Tahmini: {outbound['total']:.0f} {CURRENCY.upper()} "
                      f"({outbound['leg1_price']:.0f}+{outbound['leg2_price']:.0f})")
                all_offers[month].append(outbound)
                key = price_key(outbound["label"], month)
                current_prices[key] = outbound["total"]
                # 200€ altı mı?
                if outbound["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(outbound)
                # Fiyat değişti mi?
                if key in last_prices:
                    diff = last_prices[key] - outbound["total"]
                    if abs(diff) >= CHANGE_THRESHOLD:
                        outbound["prev_price"] = last_prices[key]
                        outbound["diff"] = diff
                        changed_offers.append(outbound)
            else:
                print("  Cache verisi yok, atlanıyor.")

            # DÖNÜŞ
            print(f"Kontrol (Dönüş): {DESTINATION_AIRPORT} -> {TRANSIT_AIRPORT} -> {origin}, {month}")
            inbound = check_direction(
                f"Dönüş ({DESTINATION_AIRPORT}→{origin})",
                DESTINATION_AIRPORT, TRANSIT_AIRPORT, origin, month,
            )
            if inbound:
                print(f"  Tahmini: {inbound['total']:.0f} {CURRENCY.upper()} "
                      f"({inbound['leg1_price']:.0f}+{inbound['leg2_price']:.0f})")
                all_offers[month].append(inbound)
                key = price_key(inbound["label"], month)
                current_prices[key] = inbound["total"]
                if inbound["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(inbound)
                if key in last_prices:
                    diff = last_prices[key] - inbound["total"]
                    if abs(diff) >= CHANGE_THRESHOLD:
                        inbound["prev_price"] = last_prices[key]
                        inbound["diff"] = diff
                        changed_offers.append(inbound)
            else:
                print("  Cache verisi yok, atlanıyor.")

    # Fiyatları kaydet
    save_prices(current_prices)

    # --- 1. UCUZ BİLET UYARISI (her zaman gönderilir, 200€ altıysa) ---
    if cheap_offers:
        cheap_offers.sort(key=lambda x: x["total"])
        lines = [f"🚨 {PRICE_THRESHOLD:.0f} {CURRENCY.upper()} ALTI BİLET BULUNDU!\n"]
        for o in cheap_offers[:10]:
            lines.append(
                f"✅ {o['label']} | {o['month']} | "
                f"≈ {o['total']:.0f} {CURRENCY.upper()} "
                f"({o['leg1_price']:.0f}+{o['leg2_price']:.0f})"
            )
        lines.append("\n⚠️ Bilet almadan önce THY sitesinden teyit et!")
        message = "\n".join(lines)
        print(message)
        send_telegram(message)
        send_email("🚨 Ucuz THY Bileti Bulundu!", message)

    # --- 2. FİYAT DEĞİŞİKLİĞİ BİLDİRİMİ ---
    elif changed_offers:
        changed_offers.sort(key=lambda x: x["total"])
        lines = ["📉 Fiyat Değişikliği Tespit Edildi:\n"]
        for o in changed_offers[:10]:
            arrow = "📉" if o["diff"] > 0 else "📈"
            lines.append(
                f"{arrow} {o['label']} | {o['month']} | "
                f"{o['prev_price']:.0f} → {o['total']:.0f} {CURRENCY.upper()} "
                f"({'+' if o['diff'] > 0 else ''}{o['diff']:.0f}€)"
            )
        lines.append("\n⚠️ Bilet almadan önce THY sitesinden teyit et.")
        message = "\n".join(lines)
        print(message)
        send_telegram(message)

    # --- 3. DEĞİŞİKLİK YOK ---
    else:
        print("Fiyatlarda önemli bir değişiklik yok, bildirim gönderilmedi.")


if __name__ == "__main__":
    main()
