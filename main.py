"""
THY fiyat takip scripti (Travelpayouts / Aviasales Data API)
============================================================
NRW (Dortmund / Düsseldorf / Köln-Bonn) <-> Sinop (NOP) rotasını
gidiş ve dönüş olarak takip eder.

Bildirim mantığı:
  - Her gün 200€ altı bilet varsa kısa "FIRSAT" bildirimi gönderilir.
  - Bilet ucuzlarsa kaç euro ucuzladığı yazılır: "73€ ucuzladı".
  - Değişiklik yoksa otomatik bildirim gönderilmez.
  - Her ay için en ucuz gidiş ve en ucuz dönüş takip edilir.
  - Telegram'da "selam" yazınca bot tarih ve yön sorup ona göre arama yapar.
"""

import json
import logging
import os
import smtplib
import time
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "200"))
CHANGE_THRESHOLD = float(os.environ.get("CHANGE_THRESHOLD", "5"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "6"))
AUTO_CHECK_HOUR = int(os.environ.get("AUTO_CHECK_HOUR", "8"))
CURRENCY = os.environ.get("CURRENCY", "eur")

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
STATE_FILE = Path(os.environ.get("STATE_FILE", "/tmp/thy_price_state.json"))

MONTH_TR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

USER_STATES = {}


# ====================== TELEGRAM ======================

def tg_send(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard, ensure_ascii=False)
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", data=data, timeout=20)
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


def direction_keyboard():
    return {
        "keyboard": [[
            {"text": "Gidiş"},
            {"text": "Dönüş"},
            {"text": "Gidiş + Dönüş"},
        ]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_keyboard():
    return {"remove_keyboard": True}
