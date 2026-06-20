"""
THY Fiyat Takip Scripti (Travelpayouts / Aviasales Data API ile)
==================================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) <-> Sinop (NOP) rotasını HER İKİ
YÖNDE (gidiş ve dönüş) AYRI AYRI takip eder. 6 ay ileriye bakar.

Her ay için /v1/prices/calendar endpoint'i kullanılır -> gün bazında fiyat.
En ucuz 3 tarih gösterilir (örn: 15 Temmuz - 187€, 22 Temmuz - 192€ ...)

Bildirim mantığı:
  - 200 EUR altı bilet bulunursa -> HER ZAMAN Telegram + E-posta UYARI.
  - Fiyatlar önceki taramaya göre 5€+ değiştiyse -> Telegram özet.
  - Değişiklik yoksa -> bildirim yok.
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
TRANSIT_AIRPORT  = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD  = float(os.environ.get("PRICE_THRESHOLD", "200"))
MONTHS_AHEAD     = int(os.environ.get("MONTHS_AHEAD", "6"))
CURRENCY         = os.environ.get("CURRENCY", "eur")
CHANGE_THRESHOLD = float(os.environ.get("CHANGE_THRESHOLD", "5"))
TOP_DATES        = int(os.environ.get("TOP_DATES", "3"))  # kaç tarih gösterilsin

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID")
GMAIL_ADDRESS       = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD  = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO            = os.environ.get("EMAIL_TO")

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


# ====================== TRAVELPAYOUTS API ======================

def cheapest_dates_for_month(origin: str, destination: str, month_str: str):
    """
    Belirtilen ay için gün bazında fiyatları çeker.
    En ucuz TOP_DATES tarihi liste olarak döner:
    [{"date": "2026-07-15", "price": 187.0}, ...]
    """
    params = {
        "origin":      origin,
        "destination": destination,
        "depart_date": month_str,
        "currency":    CURRENCY,
        "token":       TRAVELPAYOUTS_TOKEN,
        "show_to_affiliates": "true",
    }
    resp = requests.get(
        "https://api.travelpayouts.com/v1/prices/calendar",
        params=params,
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"  [Uyarı] calendar {origin}->{destination} ({month_str}): "
              f"{resp.status_code} {resp.text[:150]}")
        return []

    data = resp.json().get("data", {})
    if not data:
        # calendar'da veri yoksa cheap endpoint'e geri dön
        return _fallback_cheap(origin, destination, month_str)

    results = []
    for day_str, info in data.items():
        price = info.get("price")
        if price:
            results.append({"date": day_str, "price": float(price)})

    results.sort(key=lambda x: x["price"])
    return results[:TOP_DATES]


def _fallback_cheap(origin: str, destination: str, month_str: str):
    """calendar'da veri yoksa /v1/prices/cheap ile ay bazında en ucuzu döner."""
    params = {
        "origin":      origin,
        "destination": destination,
        "depart_date": month_str,
        "currency":    CURRENCY,
        "token":       TRAVELPAYOUTS_TOKEN,
    }
    resp = requests.get(
        "https://api.travelpayouts.com/v1/prices/cheap",
        params=params,
        timeout=20,
    )
    if resp.status_code != 200:
        return []
    dest_data = resp.json().get("data", {}).get(destination)
    if not dest_data:
        return []
    cheapest = min(dest_data.values(), key=lambda x: x["price"])
    dep_at = cheapest.get("departure_at", "")
    day_str = dep_at[:10] if dep_at else month_str
    return [{"date": day_str, "price": float(cheapest["price"])}]


def build_months():
    months = []
    today = date.today()
    for i in range(MONTHS_AHEAD):
        total_month = today.month - 1 + i
        year  = today.year + total_month // 12
        month = total_month % 12 + 1
        months.append(f"{year}-{month:02d}")
    return months


def check_direction(label, start, mid, end, month):
    """
    start->mid->end için iki bacağın en ucuz tarihlerini birleştirip
    toplam fiyatı hesaplar. Her bacak için TOP_DATES tarih çekilir,
    en ucuz kombinasyon seçilir.
    """
    leg1_dates = cheapest_dates_for_month(start, mid, month)
    time.sleep(0.4)
    leg2_dates = cheapest_dates_for_month(mid, end, month)
    time.sleep(0.4)

    if not leg1_dates or not leg2_dates:
        return None

    best1 = leg1_dates[0]
    best2 = leg2_dates[0]
    total = best1["price"] + best2["price"]

    # Alternatif tarihler (2. ve 3. en ucuzlar)
    alt_dates = []
    for d in leg1_dates[1:]:
        alt_dates.append({"leg1": d, "leg2": best2, "total": d["price"] + best2["price"]})
    for d in leg2_dates[1:]:
        alt_dates.append({"leg1": best1, "leg2": d, "total": best1["price"] + d["price"]})
    alt_dates.sort(key=lambda x: x["total"])

    return {
        "label":      label,
        "month":      month,
        "leg1_date":  best1["date"],
        "leg1_price": best1["price"],
        "leg2_date":  best2["date"],
        "leg2_price": best2["price"],
        "total":      total,
        "alts":       alt_dates[:2],  # en iyi 2 alternatif
    }


# ====================== BİLDİRİMLER ======================

def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Bilgi] Telegram ayarları eksik.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=20,
        )
        print("  [Telegram] Gönderildi.")
    except Exception as e:
        print(f"  [Hata] Telegram: {e}")


def send_email(subject: str, body: str) -> None:
    if not all([GMAIL_ADDRESS, GMAIL_APP_PASSWORD, EMAIL_TO]):
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = EMAIL_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        print("  [E-posta] Gönderildi.")
    except Exception as e:
        print(f"  [Hata] E-posta: {e}")


def format_offer(o, currency):
    """Tek bir teklifi okunabilir satır olarak formatlar."""
    lines = [
        f"  📅 {o['leg1_date']} — {o['leg1_price']:.0f} {currency.upper()} "
        f"(1.bacak: {o['leg1_date']})",
        f"  📅 {o['leg2_date']} — {o['leg2_price']:.0f} {currency.upper()} "
        f"(2.bacak: {o['leg2_date']})",
        f"  💰 TOPLAM ≈ {o['total']:.0f} {currency.upper()}",
    ]
    if o.get("alts"):
        lines.append("  Alternatif tarihler:")
        for a in o["alts"]:
            lines.append(
                f"    • {a['leg1']['date']} + {a['leg2']['date']} "
                f"≈ {a['total']:.0f} {currency.upper()}"
            )
    return "\n".join(lines)


# ====================== ANA AKIŞ ======================

def main():
    print("THY fiyat takip scripti başlıyor (6 aylık, gün bazında tarama)...")
    months      = build_months()
    last_prices = load_last_prices()
    current_prices = {}

    cheap_offers   = []
    changed_offers = []
    all_offers     = defaultdict(list)

    for raw_origin in ORIGIN_AIRPORTS:
        origin = raw_origin.strip()
        for month in months:
            # GİDİŞ
            print(f"Gidiş: {origin}→{TRANSIT_AIRPORT}→{DESTINATION_AIRPORT} [{month}]")
            outbound = check_direction(
                f"Gidiş ({origin}→{DESTINATION_AIRPORT})",
                origin, TRANSIT_AIRPORT, DESTINATION_AIRPORT, month,
            )
            if outbound:
                print(f"  En ucuz: {outbound['leg1_date']} + {outbound['leg2_date']} "
                      f"= {outbound['total']:.0f} {CURRENCY.upper()}")
                all_offers[month].append(outbound)
                key = f"{outbound['label']}|{month}"
                current_prices[key] = outbound["total"]
                if outbound["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(outbound)
                if key in last_prices:
                    diff = last_prices[key] - outbound["total"]
                    if abs(diff) >= CHANGE_THRESHOLD:
                        outbound["prev_price"] = last_prices[key]
                        outbound["diff"]       = diff
                        changed_offers.append(outbound)
            else:
                print("  Veri yok, atlanıyor.")

            # DÖNÜŞ
            print(f"Dönüş: {DESTINATION_AIRPORT}→{TRANSIT_AIRPORT}→{origin} [{month}]")
            inbound = check_direction(
                f"Dönüş ({DESTINATION_AIRPORT}→{origin})",
                DESTINATION_AIRPORT, TRANSIT_AIRPORT, origin, month,
            )
            if inbound:
                print(f"  En ucuz: {inbound['leg1_date']} + {inbound['leg2_date']} "
                      f"= {inbound['total']:.0f} {CURRENCY.upper()}")
                all_offers[month].append(inbound)
                key = f"{inbound['label']}|{month}"
                current_prices[key] = inbound["total"]
                if inbound["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(inbound)
                if key in last_prices:
                    diff = last_prices[key] - inbound["total"]
                    if abs(diff) >= CHANGE_THRESHOLD:
                        inbound["prev_price"] = last_prices[key]
                        inbound["diff"]       = diff
                        changed_offers.append(inbound)
            else:
                print("  Veri yok, atlanıyor.")

    save_prices(current_prices)

    # --- 1. UCUZ BİLET UYARISI ---
    if cheap_offers:
        cheap_offers.sort(key=lambda x: x["total"])
        lines = [f"🚨 {PRICE_THRESHOLD:.0f}€ ALTI BİLET BULUNDU!\n"]
        for o in cheap_offers[:6]:
            lines.append(f"✅ {o['label']} | {o['month']}")
            lines.append(format_offer(o, CURRENCY))
            lines.append("")
        lines.append("⚠️ Bilet almadan önce THY sitesinden teyit et!")
        msg = "\n".join(lines)
        print(msg)
        send_telegram(msg)
        send_email("🚨 Ucuz THY Bileti Bulundu!", msg)

    # --- 2. FİYAT DEĞİŞİKLİĞİ ---
    elif changed_offers:
        changed_offers.sort(key=lambda x: x["total"])
        lines = ["📉 Fiyat Değişikliği:\n"]
        for o in changed_offers[:8]:
            arrow = "📉" if o["diff"] > 0 else "📈"
            sign  = "+" if o["diff"] > 0 else ""
            lines.append(
                f"{arrow} {o['label']} | {o['month']}\n"
                f"  {o['prev_price']:.0f}€ → {o['total']:.0f}€ "
                f"({sign}{o['diff']:.0f}€)\n"
                f"  📅 {o['leg1_date']} ({o['leg1_price']:.0f}€) + "
                f"{o['leg2_date']} ({o['leg2_price']:.0f}€)"
            )
        lines.append("\n⚠️ THY sitesinden teyit et.")
        msg = "\n".join(lines)
        print(msg)
        send_telegram(msg)

    # --- 3. DEĞİŞİKLİK YOK ---
    else:
        print("Değişiklik yok, bildirim gönderilmedi.")


if __name__ == "__main__":
    main()
