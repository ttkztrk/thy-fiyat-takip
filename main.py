"""
Otomatik fiyat izleme - günde 3 kez çalışır
Fiyat düşünce veya eşiğin altına girince Telegram + mail bildirim
"""

import os, json, smtplib
from email.mime.text import MIMEText
from datetime import date, timedelta
from pathlib import Path
import requests

TOKEN    = os.environ["TRAVELPAYOUTS_TOKEN"]
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
GMAIL    = os.environ.get("GMAIL_ADDRESS", "")
GPASS    = os.environ.get("GMAIL_APP_PASSWORD", "")
MAILTO   = os.environ.get("EMAIL_TO", "")

ORIGINS  = ["DTM", "DUS", "CGN"]
DEST     = "NOP"
TRANSIT  = "IST"
CURRENCY = "eur"
MONTHS   = 6
CHANGE   = 5.0   # bu kadar € değişirse bildirim

PRICES_FILE = Path(os.environ.get("PRICES_FILE", "/tmp/last_prices.json"))

MONTH_TR = {1:"Ocak",2:"Şubat",3:"Mart",4:"Nisan",5:"Mayıs",6:"Haziran",
            7:"Temmuz",8:"Ağustos",9:"Eylül",10:"Ekim",11:"Kasım",12:"Aralık"}

def load(): 
    return json.loads(PRICES_FILE.read_text()) if PRICES_FILE.exists() else {}

def save(p): 
    PRICES_FILE.write_text(json.dumps(p, indent=2))

def month_label(y, m): 
    return f"{MONTH_TR[m]} {y}"

def get_try_rate():
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR&to=TRY", timeout=8)
        return r.json()["rates"]["TRY"]
    except:
        return 38.0

def cheapest(origin, dest, month_str):
    try:
        r = requests.get(
            "https://api.travelpayouts.com/v1/prices/cheap",
            params={"origin": origin, "destination": dest,
                    "depart_date": month_str, "currency": CURRENCY,
                    "token": TOKEN},
            timeout=20,
        )
        if r.status_code != 200: return None
        data = r.json().get("data", {}).get(dest)
        if not data: return None
        best = min(data.values(), key=lambda x: x["price"])
        dep = best.get("departure_at", "")
        return {"price": float(best["price"]), "date": dep[:10] if dep else month_str}
    except: return None

def fmt_date(s):
    try:
        parts = s[:10].split("-")
        return f"{int(parts[2])} {MONTH_TR[int(parts[1])]} {parts[0]}"
    except: return s

def tg(msg):
    if not TG_TOKEN or not TG_CHAT: return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": msg}, timeout=15
        )
    except: pass

def mail(subject, body):
    if not all([GMAIL, GPASS, MAILTO]): return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL
    msg["To"] = MAILTO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL, GPASS)
            s.send_message(msg)
    except: pass

def main():
    today = date.today()
    rate  = get_try_rate()
    last  = load()
    curr  = {}

    # Kullanıcı tanımlı eşikler (varsayılan 200)
    threshold_out = float(os.environ.get("THRESHOLD_OUTBOUND", "200"))
    threshold_in  = float(os.environ.get("THRESHOLD_INBOUND", "200"))

    alerts  = []
    changes = []

    for i in range(MONTHS):
        m_idx = (today.month - 1 + i) % 12 + 1
        y     = today.year + (today.month - 1 + i) // 12
        ms    = f"{y}-{m_idx:02d}"
        ml    = month_label(y, m_idx)

        for origin in ORIGINS:
            # GİDİŞ: origin → IST → NOP
            k_out = f"gidis|{origin}|{ms}"
            leg1  = cheapest(origin, TRANSIT, ms)
            leg2  = cheapest(TRANSIT, DEST, ms) if leg1 else None
            if leg1 and leg2:
                total = leg1["price"] + leg2["price"]
                curr[k_out] = total
                info = {"yon": "Gidiş", "kalkis": origin, "varis": DEST,
                        "ay": ml, "fiyat": total, "try": total * rate,
                        "tarih": leg1["date"], "esik": threshold_out}
                if total <= threshold_out:
                    alerts.append(info)
                elif k_out in last and abs(last[k_out] - total) >= CHANGE:
                    info["onceki"] = last[k_out]
                    changes.append(info)

            # DÖNÜŞ: NOP → IST → origin
            k_in  = f"donus|{origin}|{ms}"
            leg1b = cheapest(DEST, TRANSIT, ms)
            leg2b = cheapest(TRANSIT, origin, ms) if leg1b else None
            if leg1b and leg2b:
                total = leg1b["price"] + leg2b["price"]
                curr[k_in] = total
                info = {"yon": "Dönüş", "kalkis": DEST, "varis": origin,
                        "ay": ml, "fiyat": total, "try": total * rate,
                        "tarih": leg1b["date"], "esik": threshold_in}
                if total <= threshold_in:
                    alerts.append(info)
                elif k_in in last and abs(last[k_in] - total) >= CHANGE:
                    info["onceki"] = last[k_in]
                    changes.append(info)

    save(curr)

    if not alerts and not changes:
        print("Değişiklik yok, bildirim gönderilmedi.")
        return

    # 🔥 FIRSAT bildirimi
    if alerts:
        alerts.sort(key=lambda x: x["fiyat"])
        lines = ["🔥 Fırsat! Eşiğin altında bilet var:\n"]
        for a in alerts[:5]:
            lines += [
                f"✈️ {a['yon']}: {a['kalkis']} → {a['varis']}",
                f"📅 {fmt_date(a['tarih'])} | {a['ay']}",
                f"💶 {a['fiyat']:.0f}€ ({a['try']:,.0f}₺)",
                f"🎯 Eşiğin: {a['esik']:.0f}€",
                "",
            ]
        lines.append("⚠️ Almadan önce THY/Aviasales'ten teyit et.")
        msg = "\n".join(lines)
        tg(msg)
        mail("🔥 Fırsat — Ucuz Uçuş!", msg)

    # 📉 Değişiklik bildirimi  
    if changes:
        changes.sort(key=lambda x: x["fiyat"])
        lines = ["📉 Fiyat değişikliği var:\n"]
        for c in changes[:5]:
            diff = c["onceki"] - c["fiyat"]
            word = "ucuzladı" if diff > 0 else "pahalandı"
            lines += [
                f"{'📉' if diff>0 else '📈'} {c['yon']}: {c['kalkis']} → {c['varis']}",
                f"📅 {c['ay']}",
                f"💶 {c['onceki']:.0f}€ → {c['fiyat']:.0f}€  ({abs(diff):.0f}€ {word})",
                "",
            ]
        lines.append("⚠️ Almadan önce THY/Aviasales'ten teyit et.")
        tg("\n".join(lines))

if __name__ == "__main__":
    main()
