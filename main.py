"""
Uçuş Fiyat Takip - Otomatik İzleme (GitHub Actions)
Kiwi Tequila API - tüm havayolları - NRW <-> Sinop
"""

import os, json, time, smtplib
from email.mime.text import MIMEText
from datetime import date, timedelta, datetime
from pathlib import Path
import requests

# ── Ayarlar ───────────────────────────────────────────────
ORIGINS      = ["DTM", "DUS", "CGN"]
DESTINATION  = "NOP"  # Sinop
THRESHOLD    = float(os.environ.get("PRICE_THRESHOLD", "200"))
CHANGE_MIN   = float(os.environ.get("CHANGE_THRESHOLD", "5"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "6"))

KIWI_KEY    = os.environ["KIWI_API_KEY"]
TG_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT     = os.environ.get("TELEGRAM_CHAT_ID")
GMAIL_ADDR  = os.environ.get("GMAIL_ADDRESS")
GMAIL_PASS  = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO    = os.environ.get("EMAIL_TO")

PRICES_FILE = Path(os.environ.get("PRICES_FILE", "/tmp/last_prices.json"))

MONTH_TR = {1:"Ocak",2:"Şubat",3:"Mart",4:"Nisan",5:"Mayıs",6:"Haziran",
            7:"Temmuz",8:"Ağustos",9:"Eylül",10:"Ekim",11:"Kasım",12:"Aralık"}

AIRLINE_NAMES = {
    "TK":"Turkish Airlines","PC":"Pegasus","XQ":"SunExpress",
    "TK/PC":"THY & Pegasus","W6":"Wizz Air","FR":"Ryanair",
}

# ── Yardımcı ──────────────────────────────────────────────

def fmt_date(ts):
    d = datetime.utcfromtimestamp(ts)
    return f"{d.day} {MONTH_TR[d.month]} {d.year}, {d.strftime('%H:%M')}"

def get_try_rate():
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR&to=TRY", timeout=8)
        return r.json()["rates"]["TRY"]
    except:
        return 38.0

def load_prices():
    if PRICES_FILE.exists():
        try: return json.loads(PRICES_FILE.read_text())
        except: pass
    return {}

def save_prices(p):
    try: PRICES_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2))
    except Exception as e: print(f"  [!] Kayıt hatası: {e}")

# ── Kiwi API ──────────────────────────────────────────────

def search_kiwi(fly_from, fly_to, date_from, date_to, limit=3):
    """DD/MM/YYYY formatında tarih alır, en ucuz uçuşları döner."""
    try:
        r = requests.get(
            "https://tequila.kiwi.com/v2/search",
            headers={"apikey": KIWI_KEY},
            params={
                "fly_from": fly_from, "fly_to": fly_to,
                "date_from": date_from, "date_to": date_to,
                "curr": "EUR", "limit": limit, "sort": "price",
                "partner_market": "de", "adults": 1,
                "max_stopovers": 2,
            },
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("data", [])
        print(f"  Kiwi {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"  Kiwi hata: {e}")
    return []

def month_range_str(year, month):
    """Bir ayın başı ve sonu için DD/MM/YYYY string döner."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start.strftime("%d/%m/%Y"), end.strftime("%d/%m/%Y")

# ── Bildirim ──────────────────────────────────────────────

def tg(msg):
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": msg}, timeout=15)
        print("  [Telegram] ✓")
    except Exception as e: print(f"  [Telegram] hata: {e}")

def mail(subject, body):
    if not all([GMAIL_ADDR, GMAIL_PASS, EMAIL_TO]): return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDR
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_ADDR, GMAIL_PASS)
            s.send_message(msg)
        print("  [Mail] ✓")
    except Exception as e: print(f"  [Mail] hata: {e}")

# ── Ana akış ──────────────────────────────────────────────

def main():
    print("=== Uçuş fiyat takibi başlıyor ===")
    today     = date.today()
    rate      = get_try_rate()
    last      = load_prices()
    current   = {}
    alerts    = []   # 200€ altı
    changes   = []   # fiyat değişiklikleri

    for i in range(MONTHS_AHEAD):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + (today.month - 1 + i) // 12
        d_from, d_to = month_range_str(y, m)
        label_month = f"{MONTH_TR[m]} {y}"

        for direction, frm, to in [
            ("gidis", ",".join(ORIGINS), DESTINATION),
            ("donus", DESTINATION, ",".join(ORIGINS)),
        ]:
            key = f"{direction}|{m}|{y}"
            print(f"  {direction.upper()}: {frm} → {to} [{label_month}]")
            flights = search_kiwi(frm, to, d_from, d_to)
            time.sleep(0.5)

            if not flights:
                print("    Veri yok.")
                continue

            best = flights[0]
            price = float(best["price"])
            airline_code = best.get("airlines", ["?"])[0]
            airline = AIRLINE_NAMES.get(airline_code, airline_code)
            dep_ts  = best.get("dTime", 0)
            dep_str = fmt_date(dep_ts) if dep_ts else "?"
            fly_from_actual = best.get("flyFrom", frm)
            fly_to_actual   = best.get("flyTo", to)
            current[key] = price

            print(f"    En ucuz: {price:.0f}€ — {airline} — {dep_str}")

            info = {
                "key": key, "direction": direction, "month": label_month,
                "price": price, "airline": airline,
                "from": fly_from_actual, "to": fly_to_actual,
                "dep": dep_str, "try_price": price * rate,
                "link": best.get("deep_link", ""),
            }

            # 200€ altı?
            if price <= THRESHOLD:
                alerts.append(info)

            # Fiyat değişti mi?
            if key in last:
                diff = last[key] - price
                if abs(diff) >= CHANGE_MIN:
                    info["prev"] = last[key]
                    info["diff"] = diff
                    changes.append(info)

    save_prices(current)

    # ── Mesaj üret ──────────────────────────────────────────
    if not alerts and not changes:
        print("\nDeğişiklik yok, bildirim gönderilmedi.")
        return

    # FIRSAT mesajı (200€ altı)
    if alerts:
        alerts.sort(key=lambda x: x["price"])
        lines = [f"🔥 FIRSAT — {THRESHOLD:.0f}€ altı bilet!\n"]
        for a in alerts[:3]:
            dir_emoji = "✈️" if a["direction"] == "gidis" else "🔙"
            lines += [
                f"{dir_emoji} {a['from']} → {a['to']}",
                f"🏢 {a['airline']}",
                f"🗓 {a['dep']}",
                f"💶 {a['price']:.0f} € ({a['try_price']:,.0f} ₺)",
                "",
            ]
        lines.append("⚠️ Satın almadan önce THY/Kiwi sitesinden kontrol et.")
        msg = "\n".join(lines)
        print(msg)
        tg(msg)
        mail("🔥 FIRSAT — Ucuz Uçuş Bulundu!", msg)

    # Değişiklik özeti
    if changes:
        changes.sort(key=lambda x: x["price"])
        lines = ["📊 Fiyat Değişiklikleri:\n"]
        for c in changes[:5]:
            arrow = "📉" if c["diff"] > 0 else "📈"
            word  = "ucuzladı" if c["diff"] > 0 else "pahalandı"
            dir_label = "Gidiş" if c["direction"] == "gidis" else "Dönüş"
            lines += [
                f"{arrow} {dir_label}: {c['from']} → {c['to']} | {c['month']}",
                f"   {c['prev']:.0f}€ → {c['price']:.0f}€  ({abs(c['diff']):.0f}€ {word})",
                f"   {c['airline']} — {c['dep']}",
                "",
            ]
        lines.append("⚠️ THY/Kiwi sitesinden kontrol et.")
        msg = "\n".join(lines)
        print(msg)
        tg(msg)

if __name__ == "__main__":
    main()
