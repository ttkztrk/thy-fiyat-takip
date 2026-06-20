"""
THY Fiyat Takip Scripti (Travelpayouts / Aviasales Data API ile)
==================================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) <-> Sinop (NOP) rotasını HER İKİ
YÖNDE (gidiş ve dönüş) AYRI AYRI takip eder.

- 200 EUR altında bilet bulunursa -> Telegram'a UYARI bildirimi gönderilir.
- Her durumda -> o ayın en ucuz gidiş ve dönüş fiyatları Telegram'a gönderilir.
"""

import os
import time
import smtplib
from email.mime.text import MIMEText
from datetime import date
from collections import defaultdict

import requests

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "200"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "4"))
CURRENCY = os.environ.get("CURRENCY", "eur")

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")


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
    print("THY fiyat takip scripti başlıyor...")
    months = build_months()

    cheap_offers = []  # 200€ altındakiler
    # Ay bazında tüm bulunan fiyatlar: {month: [offer, ...]}
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
                if outbound["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(outbound)
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
                if inbound["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(inbound)
            else:
                print("  Cache verisi yok, atlanıyor.")

    # --- UCUZ BİLET UYARISI ---
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
        send_email("✈️ Ucuz THY Bileti!", message)

    # --- AYLIK EN UCUZ ÖZET (her zaman gönderilir) ---
    if all_offers:
        lines = ["📊 Aylık En Ucuz Fiyat Özeti (tahmini, iki bacak toplamı):\n"]
        for month in sorted(all_offers.keys()):
            offers = all_offers[month]
            if not offers:
                continue
            # Gidiş ve dönüş en ucuzlarını ayrı bul
            outbounds = [o for o in offers if "Gidiş" in o["label"]]
            inbounds = [o for o in offers if "Dönüş" in o["label"]]
            lines.append(f"📅 {month}:")
            if outbounds:
                best_out = min(outbounds, key=lambda x: x["total"])
                lines.append(f"  ✈️ Gidiş en ucuz: {best_out['label']} → "
                             f"{best_out['total']:.0f} {CURRENCY.upper()} "
                             f"({best_out['leg1_price']:.0f}+{best_out['leg2_price']:.0f})")
            if inbounds:
                best_in = min(inbounds, key=lambda x: x["total"])
                lines.append(f"  🔙 Dönüş en ucuz: {best_in['label']} → "
                             f"{best_in['total']:.0f} {CURRENCY.upper()} "
                             f"({best_in['leg1_price']:.0f}+{best_in['leg2_price']:.0f})")
        lines.append("\n⚠️ Bilet almadan önce THY sitesinden teyit et.")
        summary = "\n".join(lines)
        print(summary)
        send_telegram(summary)
        if EMAIL_TO:
            send_email("✈️ THY Aylık Fiyat Özeti", summary)
    else:
        msg = "ℹ️ Bu çalıştırmada hiçbir ay için cache verisi bulunamadı."
        print(msg)
        send_telegram(msg)


if __name__ == "__main__":
    main()
