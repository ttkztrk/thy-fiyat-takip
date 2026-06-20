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
"""

import json
import os
import smtplib
import time
from collections import defaultdict
from datetime import date, datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests

# ====================== AYARLAR ======================
ORIGIN_AIRPORTS = os.environ.get("ORIGIN_AIRPORTS", "DTM,DUS,CGN").split(",")
TRANSIT_AIRPORT = os.environ.get("TRANSIT_AIRPORT", "IST")
DESTINATION_AIRPORT = os.environ.get("DESTINATION_AIRPORT", "NOP")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "200"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "6"))
CURRENCY = os.environ.get("CURRENCY", "eur")
CHANGE_THRESHOLD = float(os.environ.get("CHANGE_THRESHOLD", "5"))

TRAVELPAYOUTS_TOKEN = os.environ["TRAVELPAYOUTS_TOKEN"]
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")

PRICES_FILE = Path(os.environ.get("PRICES_FILE", "/tmp/last_prices.json"))

MONTH_TR = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
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


def eur(value):
    return f"{value:.0f}€"


def load_last_prices() -> dict:
    if PRICES_FILE.exists():
        try:
            return json.loads(PRICES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_prices(prices: dict):
    try:
        PRICES_FILE.write_text(
            json.dumps(prices, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  [Uyarı] Fiyat geçmişi kaydedilemedi: {e}")


# ====================== TRAVELPAYOUTS API ======================
