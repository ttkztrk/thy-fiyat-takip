"""
THY Fiyat Takip Scripti (Travelpayouts / Aviasales Data API ile)
==================================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) <-> Sinop (NOP) rotasını HER İKİ
YÖNDE (gidiş ve dönüş) AYRI AYRI takip eder. 6 ay ileriye bakar.

Bildirim formatı:
  ✈️ Sinop-NRW Fiyat Özeti | Temmuz 2026
  ❌ 200€ altı bilet yok. / 🚨 200€ altı bilet bulundu!
  🏆 En ucuz gidiş: ...
  🏆 En ucuz dönüş: ...
  📉 En büyük düşüş: ...

Bildirim mantığı:
  - 200€ altı varsa -> HER ZAMAN gönderilir (Telegram + e-posta)
  - Fiyat 5€+ değiştiyse -> gönderilir
  - Değişiklik yoksa -> gönderilmez
"""

import os
import json
import time
import smtplib
from email.mime.text import MIMEText
from datetime import date, datetime
from collections import defaultdict
from pathlib import Path

import requests

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS     = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT     = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD     = float(os.environ.get("PRICE_THRESHOLD", "200"))
MONTHS_AHEAD        = int(os.environ.get("MONTHS_AHEAD", "6"))
CURRENCY            = os.environ.get("CURRENCY", "eur")
CHANGE_THRESHOLD    = float(os.environ.get("CHANGE_THRESHOLD", "5"))

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID")
GMAIL_ADDRESS       = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD  = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO            = os.environ.get("EMAIL_TO")

PRICES_FILE = Path(os.environ.get("PRICES_FILE", "/tmp/last_prices.json"))

MONTH_TR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}


# ====================== YARDIMCI ======================

def month_label(month_str):
    """'2026-07' -> 'Temmuz 2026'"""
    y, m = month_str.split("-")
    return f"{MONTH_TR[int(m)]} {y}"


def date_label(date_str):
    """'2026-07-15' -> '15 Temmuz'"""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return f"{d.day} {MONTH_TR[d.month]}"
    except Exception:
        return date_str


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

def cheapest_dates_for_month(origin, destination, month_str):
    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": month_str,
        "currency": CURRENCY,
        "token": TRAVELPAYOUTS_TOKEN,
        "show_to_affiliates": "true",
    }
    resp = requests.get(
        "https://api.travelpayouts.com/v1/prices/calendar",
        params=params, timeout=20,
    )
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        if data:
            results = [{"date": d, "price": float(v["price"])}
                       for d, v in data.items() if v.get("price")]
            results.sort(key=lambda x: x["price"])
            return results[:3]

    # Fallback: cheap endpoint
    params2 = {k: v for k, v in params.items() if k != "show_to_affiliates"}
    resp2 = requests.get(
        "https://api.travelpayouts.com/v1/prices/cheap",
        params=params2, timeout=20,
    )
    if resp2.status_code == 200:
        dest_data = resp2.json().get("data", {}).get(destination)
        if dest_data:
            cheapest = min(dest_data.values(), key=lambda x: x["price"])
            dep = cheapest.get("departure_at", month_str)
            return [{"date": dep[:10], "price": float(cheapest["price"])}]
    return []


def build_months():
    months = []
    today = date.today()
    for i in range(MONTHS_AHEAD):
        total_month = today.month - 1 + i
        year  = today.year + total_month // 12
        month = total_month % 12 + 1
        months.append(f"{year}-{month:02d}")
    return months


def check_direction(short_label, start, mid, end, month):
    """Tek yön için en ucuz tarih kombinasyonunu döner."""
    leg1 = cheapest_dates_for_month(start, mid, month)
    time.sleep(0.4)
    leg2 = cheapest_dates_for_month(mid, end, month)
    time.sleep(0.4)

    if not leg1 or not leg2:
        return None

    best1, best2 = leg1[0], leg2[0]
    return {
        "short_label": short_label,   # örn: "CGN → NOP"
        "month":       month,
        "leg1_date":   best1["date"],
        "leg1_price":  best1["price"],
        "leg2_date":   best2["date"],
        "leg2_price":  best2["price"],
        "total":       best1["price"] + best2["price"],
    }


# ====================== BİLDİRİMLER ======================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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


def send_email(subject, body):
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


# ====================== MESAJ FORMATI ======================

def build_message(month, offers, cheap, changed):
    """
    Tek bir ay için Telegram mesajını oluşturur.
    Format:
      ✈️ Sinop-NRW Fiyat Özeti | Temmuz 2026
      ❌/🚨 durum
      🏆 En ucuz gidiş
      🏆 En ucuz dönüş
      📉 En büyük düşüş (varsa)
    """
    lines = [f"✈️ Sinop-NRW Fiyat Özeti | {month_label(month)}", ""]

    # 200€ altı durum
    cheap_this = [o for o in cheap if o["month"] == month]
    if cheap_this:
        lines.append(f"🚨 {len(cheap_this)} adet {PRICE_THRESHOLD:.0f}€ altı bilet bulundu!")
    else:
        lines.append(f"❌ {PRICE_THRESHOLD:.0f}€ altı bilet yok.")
    lines.append("")

    outbounds = [o for o in offers if "→NOP" in o["short_label"] or
                 "→" + DESTINATION_AIRPORT in o["short_label"]]
    inbounds  = [o for o in offers if o not in outbounds]

    # En ucuz gidiş
    if outbounds:
        best_out = min(outbounds, key=lambda x: x["total"])
        lines.append("🏆 En ucuz gidiş:")
        lines.append(f"{best_out['short_label']}")
        lines.append(f"{best_out['total']:.0f} €")
        lines.append(f"{date_label(best_out['leg1_date'])} + {date_label(best_out['leg2_date'])}")
        lines.append("")

    # En ucuz dönüş
    if inbounds:
        best_in = min(inbounds, key=lambda x: x["total"])
        lines.append("🏆 En ucuz dönüş:")
        lines.append(f"{best_in['short_label']}")
        lines.append(f"{best_in['total']:.0f} €")
        lines.append(f"{date_label(best_in['leg1_date'])} + {date_label(best_in['leg2_date'])}")
        lines.append("")

    # En büyük düşüş (bu ay)
    changed_this = [o for o in changed if o["month"] == month and o.get("diff", 0) > 0]
    if changed_this:
        biggest = max(changed_this, key=lambda x: x["diff"])
        lines.append("📉 En büyük düşüş:")
        lines.append(f"{biggest['short_label']}")
        lines.append(f"{biggest['prev_price']:.0f} € → {biggest['total']:.0f} €")
        lines.append(f"{biggest['diff']:.0f} € ucuzladı")
        lines.append("")

    lines.append("⚠️ Satın almadan önce THY sitesinden kontrol et.")
    return "\n".join(lines)


# ====================== ANA AKIŞ ======================

def main():
    print("THY fiyat takip scripti başlıyor (6 aylık, gün bazında tarama)...")
    months      = build_months()
    last_prices = load_last_prices()
    current_prices = {}

    cheap_offers   = []
    changed_offers = []
    all_offers     = defaultdict(list)  # month -> [offer, ...]

    for raw_origin in ORIGIN_AIRPORTS:
        origin = raw_origin.strip()
        for month in months:
            # GİDİŞ
            print(f"Gidiş: {origin}→{TRANSIT_AIRPORT}→{DESTINATION_AIRPORT} [{month}]")
            out = check_direction(
                f"{origin} → {DESTINATION_AIRPORT}",
                origin, TRANSIT_AIRPORT, DESTINATION_AIRPORT, month,
            )
            if out:
                print(f"  {out['leg1_date']} + {out['leg2_date']} = {out['total']:.0f}€")
                all_offers[month].append(out)
                key = f"gidis|{origin}|{month}"
                current_prices[key] = out["total"]
                if out["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(out)
                if key in last_prices:
                    diff = last_prices[key] - out["total"]
                    if abs(diff) >= CHANGE_THRESHOLD:
                        out["prev_price"] = last_prices[key]
                        out["diff"]       = diff
                        changed_offers.append(out)
            else:
                print("  Veri yok.")

            # DÖNÜŞ
            print(f"Dönüş: {DESTINATION_AIRPORT}→{TRANSIT_AIRPORT}→{origin} [{month}]")
            inn = check_direction(
                f"{DESTINATION_AIRPORT} → {origin}",
                DESTINATION_AIRPORT, TRANSIT_AIRPORT, origin, month,
            )
            if inn:
                print(f"  {inn['leg1_date']} + {inn['leg2_date']} = {inn['total']:.0f}€")
                all_offers[month].append(inn)
                key = f"donus|{origin}|{month}"
                current_prices[key] = inn["total"]
                if inn["total"] <= PRICE_THRESHOLD:
                    cheap_offers.append(inn)
                if key in last_prices:
                    diff = last_prices[key] - inn["total"]
                    if abs(diff) >= CHANGE_THRESHOLD:
                        inn["prev_price"] = last_prices[key]
                        inn["diff"]       = diff
                        changed_offers.append(inn)
            else:
                print("  Veri yok.")

    save_prices(current_prices)

    # Bildirim gönderilecek mi?
    has_cheap   = bool(cheap_offers)
    has_change  = bool(changed_offers)

    if not has_cheap and not has_change:
        print("Değişiklik yok, bildirim gönderilmedi.")
        return

    # Her ay için ayrı mesaj gönder
    for month in sorted(all_offers.keys()):
        offers = all_offers[month]
        if not offers:
            continue

        # Bu ayda cheap veya değişiklik var mı?
        month_cheap   = [o for o in cheap_offers   if o["month"] == month]
        month_changed = [o for o in changed_offers if o["month"] == month]
        if not month_cheap and not month_changed:
            continue  # Bu ayda değişiklik yoksa mesaj yok

        msg = build_message(month, offers, cheap_offers, changed_offers)
        print(f"\n--- {month_label(month)} ---")
        print(msg)
        send_telegram(msg)

        # 200€ altıysa e-posta da gönder
        if month_cheap:
            send_email(
                f"🚨 {PRICE_THRESHOLD:.0f}€ Altı THY Bileti! ({month_label(month)})",
                msg
            )


if __name__ == "__main__":
    main()
