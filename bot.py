"""
THY Fiyat Takip - İnteraktif Telegram Botu
============================================
Bu bot sürekli çalışır (Railway/Render gibi ücretsiz bir hosting üzerinde)
ve Telegram'dan gelen komutlara cevap verir.

KOMUTLAR:
  /ara YYYY-MM-DD YYYY-MM-DD   -> Belirtilen tarih aralığında gidiş+dönüş ara
  /gidis YYYY-MM-DD YYYY-MM-DD -> Sadece gidiş ara
  /donus YYYY-MM-DD YYYY-MM-DD -> Sadece dönüş ara
  /yardim                       -> Komutları listeler

Örnek: /ara 2026-08-01 2026-08-31
"""

import os
import time
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "200"))
CURRENCY = os.environ.get("CURRENCY", "eur")

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# ====================== TELEGRAM ======================

def tg_send(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage",
                      data={"chat_id": chat_id, "text": text}, timeout=20)
    except Exception as e:
        log.error(f"Telegram gönderme hatası: {e}")


def tg_get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        log.error(f"getUpdates hatası: {e}")
        return []


# ====================== E-POSTA ======================

def send_email(subject, body):
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
        log.info("E-posta gönderildi.")
    except Exception as e:
        log.error(f"E-posta hatası: {e}")


# ====================== TRAVELPAYOUTS API ======================

def cheapest_for_date_range(origin, destination, start_date, end_date):
    """
    start_date - end_date aralığındaki tüm ayları tara,
    her ay için en ucuz fiyatı bul, sonuçları listele.
    """
    results = []
    current = start_date.replace(day=1)
    while current <= end_date:
        month_str = current.strftime("%Y-%m")
        params = {
            "origin": origin,
            "destination": destination,
            "depart_date": month_str,
            "currency": CURRENCY,
            "token": TRAVELPAYOUTS_TOKEN,
        }
        try:
            r = requests.get("https://api.travelpayouts.com/v1/prices/cheap",
                             params=params, timeout=20)
            if r.status_code == 200:
                dest_data = r.json().get("data", {}).get(destination)
                if dest_data:
                    cheapest = min(dest_data.values(), key=lambda x: x["price"])
                    dep_at = cheapest.get("departure_at", "")
                    # Tarih aralığı filtresi: departure_at başlıyorsa kontrol et
                    if dep_at:
                        dep_date = datetime.fromisoformat(dep_at[:10]).date()
                        if start_date <= dep_date <= end_date:
                            results.append({
                                "origin": origin,
                                "destination": destination,
                                "date": dep_at[:10],
                                "price": cheapest["price"],
                            })
                        else:
                            # Tarih aralığı dışında ama ay içinde en ucuz var,
                            # yine de ekleyelim (erken uyarı amaçlı)
                            results.append({
                                "origin": origin,
                                "destination": destination,
                                "date": dep_at[:10] + " (yaklaşık)",
                                "price": cheapest["price"],
                            })
                    else:
                        results.append({
                            "origin": origin,
                            "destination": destination,
                            "date": month_str,
                            "price": cheapest["price"],
                        })
        except Exception as e:
            log.error(f"API hatası {origin}->{destination} {month_str}: {e}")

        # Sonraki ay
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
        time.sleep(0.3)

    return results


def search_and_reply(chat_id, start_date, end_date, direction="both"):
    """
    Belirtilen tarih aralığında fiyat ara ve sonucu Telegram'a gönder.
    direction: "outbound" | "inbound" | "both"
    """
    tg_send(chat_id, f"🔍 {start_date} - {end_date} aralığı taranıyor, lütfen bekle...")

    outbound_results = []
    inbound_results = []

    for raw_origin in ORIGIN_AIRPORTS:
        origin = raw_origin.strip()

        if direction in ("outbound", "both"):
            # GİDİŞ: origin -> IST
            leg1 = cheapest_for_date_range(origin, TRANSIT_AIRPORT, start_date, end_date)
            # GİDİŞ: IST -> NOP
            leg2 = cheapest_for_date_range(TRANSIT_AIRPORT, DESTINATION_AIRPORT, start_date, end_date)
            if leg1 and leg2:
                best1 = min(leg1, key=lambda x: x["price"])
                best2 = min(leg2, key=lambda x: x["price"])
                total = best1["price"] + best2["price"]
                outbound_results.append({
                    "origin": origin,
                    "leg1": best1,
                    "leg2": best2,
                    "total": total,
                })

        if direction in ("inbound", "both"):
            # DÖNÜŞ: NOP -> IST
            leg1 = cheapest_for_date_range(DESTINATION_AIRPORT, TRANSIT_AIRPORT, start_date, end_date)
            # DÖNÜŞ: IST -> origin
            leg2 = cheapest_for_date_range(TRANSIT_AIRPORT, origin, start_date, end_date)
            if leg1 and leg2:
                best1 = min(leg1, key=lambda x: x["price"])
                best2 = min(leg2, key=lambda x: x["price"])
                total = best1["price"] + best2["price"]
                inbound_results.append({
                    "origin": origin,
                    "leg1": best1,
                    "leg2": best2,
                    "total": total,
                })

    # Sonucu formatla
    lines = [f"✈️ {start_date} - {end_date} Arama Sonuçları:\n"]
    found = False

    if outbound_results:
        found = True
        lines.append("🛫 GİDİŞ (NRW → Sinop):")
        outbound_results.sort(key=lambda x: x["total"])
        for r in outbound_results[:6]:
            flag = "🚨 " if r["total"] <= PRICE_THRESHOLD else ""
            lines.append(f"  {flag}{r['origin']}→NOP: ≈{r['total']:.0f} {CURRENCY.upper()} "
                        f"({r['leg1']['price']:.0f}+{r['leg2']['price']:.0f}) "
                        f"| ~{r['leg1']['date']}")

    if inbound_results:
        found = True
        lines.append("\n🛬 DÖNÜŞ (Sinop → NRW):")
        inbound_results.sort(key=lambda x: x["total"])
        for r in inbound_results[:6]:
            flag = "🚨 " if r["total"] <= PRICE_THRESHOLD else ""
            lines.append(f"  {flag}NOP→{r['origin']}: ≈{r['total']:.0f} {CURRENCY.upper()} "
                        f"({r['leg1']['price']:.0f}+{r['leg2']['price']:.0f}) "
                        f"| ~{r['leg1']['date']}")

    if not found:
        lines.append("❌ Bu tarih aralığı için cache'te yeterli veri bulunamadı.")
        lines.append("💡 İpucu: Daha geniş bir tarih aralığı dene.")
    else:
        lines.append(f"\n⚠️ Fiyatlar tahmini (iki bacak toplamı).")
        lines.append("Bilet almadan önce THY sitesinden teyit et!")

        # 200€ altı bulunduysa e-posta da gönder
        cheap_out = [r for r in outbound_results if r["total"] <= PRICE_THRESHOLD]
        cheap_in = [r for r in inbound_results if r["total"] <= PRICE_THRESHOLD]
        if cheap_out or cheap_in:
            send_email(
                f"🚨 {PRICE_THRESHOLD:.0f}€ Altı THY Bileti! ({start_date} - {end_date})",
                "\n".join(lines)
            )

    tg_send(chat_id, "\n".join(lines))


# ====================== KOMUT İŞLEYİCİ ======================

YARDIM_METNI = """✈️ THY Fiyat Takip Botu

Komutlar:
/ara YYYY-MM-DD YYYY-MM-DD
  → Gidiş ve dönüş ara
  Örnek: /ara 2026-08-01 2026-08-31

/gidis YYYY-MM-DD YYYY-MM-DD
  → Sadece gidiş ara (NRW→Sinop)
  Örnek: /gidis 2026-07-15 2026-08-15

/donus YYYY-MM-DD YYYY-MM-DD
  → Sadece dönüş ara (Sinop→NRW)
  Örnek: /donus 2026-09-01 2026-09-30

/yardim
  → Bu mesajı göster

Otomatik tarama: Her gün 08:00, 14:00, 20:00'de
200€ altına düşünce otomatik bildirim gelir."""


def parse_dates(parts):
    """Komut parçalarından iki tarih parse et. Başarısızsa None döner."""
    if len(parts) < 2:
        return None, None
    try:
        d1 = datetime.strptime(parts[0], "%Y-%m-%d").date()
        d2 = datetime.strptime(parts[1], "%Y-%m-%d").date()
        if d1 > d2:
            d1, d2 = d2, d1
        return d1, d2
    except ValueError:
        return None, None


def handle_message(chat_id, text):
    text = text.strip()
    parts = text.split()
    cmd = parts[0].lower() if parts else ""

    if cmd in ("/start", "/yardim", "/help"):
        tg_send(chat_id, YARDIM_METNI)

    elif cmd == "/ara":
        d1, d2 = parse_dates(parts[1:])
        if not d1:
            tg_send(chat_id, "❌ Tarih formatı yanlış.\nÖrnek: /ara 2026-08-01 2026-08-31")
        else:
            search_and_reply(chat_id, d1, d2, direction="both")

    elif cmd == "/gidis":
        d1, d2 = parse_dates(parts[1:])
        if not d1:
            tg_send(chat_id, "❌ Tarih formatı yanlış.\nÖrnek: /gidis 2026-08-01 2026-08-31")
        else:
            search_and_reply(chat_id, d1, d2, direction="outbound")

    elif cmd == "/donus":
        d1, d2 = parse_dates(parts[1:])
        if not d1:
            tg_send(chat_id, "❌ Tarih formatı yanlış.\nÖrnek: /donus 2026-09-01 2026-09-30")
        else:
            search_and_reply(chat_id, d1, d2, direction="inbound")

    else:
        tg_send(chat_id, "❓ Komutu tanımadım. /yardim yaz.")


# ====================== ANA DÖNGÜ ======================

def main():
    log.info("İnteraktif THY Fiyat Botu başlıyor...")
    offset = None

    while True:
        updates = tg_get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message")
            if not msg:
                continue
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "")
            if text:
                log.info(f"Mesaj [{chat_id}]: {text}")
                handle_message(chat_id, text)

        time.sleep(1)


if __name__ == "__main__":
    main()
