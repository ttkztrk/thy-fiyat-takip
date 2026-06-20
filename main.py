"""
THY fiyat takip scripti (Travelpayouts / Aviasales Data API)
============================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) <-> Sinop (NOP) rotasını
gidiş ve dönüş olarak takip eder.

Bildirim mantigi:
  - 200€ altı varsa: ayrıca kısa "FIRSAT" bildirimi gönderilir.
  - Uzun bildirimler ay ay bölünmez; tek özet mesaj gönderilir.
  - 200€ altı yoksa özette sadece en ucuz gidiş, en ucuz dönüş ve
    en büyük fiyat düşüşü gösterilir.
  - Fırsat listesi en fazla ilk 3 sonucu gösterir.

Telegram komutları:
  /ara YYYY-MM-DD YYYY-MM-DD   -> Gidiş + dönüş ara
  /gidis YYYY-MM-DD YYYY-MM-DD -> Sadece gidiş ara
  /donus YYYY-MM-DD YYYY-MM-DD -> Sadece dönüş ara
  /yardim                      -> Komutları listeler
"""

import logging
import os
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText

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
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
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

def month_cursor(start_date, end_date):
