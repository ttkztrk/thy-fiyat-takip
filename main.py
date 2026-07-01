"""
Ucus fiyat takip botu
Kendi flight-api servisine baglanir.
"""

import os
import logging
import smtplib
import threading
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GMAIL = os.environ.get("GMAIL_ADDRESS", "")
GPASS = os.environ.get("GMAIL_APP_PASSWORD", "")
MAILTO = os.environ.get("EMAIL_TO", "")

FLIGHT_API_URL = os.environ.get("FLIGHT_API_URL", "http://localhost:3000")
STUDENT_MODE = os.environ.get("STUDENT_MODE", "").lower() in ("1", "true", "yes", "evet")
CURRENCY = "eur"

MONTH_TR = {
    1: "Ocak",
    2: "Subat",
    3: "Mart",
    4: "Nisan",
    5: "Mayis",
    6: "Haziran",
    7: "Temmuz",
    8: "Agustos",
    9: "Eylul",
    10: "Ekim",
    11: "Kasim",
    12: "Aralik",
}

(S_MENU, S_KALKIS, S_VARIS_ONAY, S_VARIS_YAZ, S_YON, S_AY, S_ESIK_ONA, S_ESIK_YAZ) = range(8)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"bot is running")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info("Health server started on port %s", port)


def get_try_rate():
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR&to=TRY", timeout=8)
        return r.json()["rates"]["TRY"]
    except Exception:
        return 38.0


def fmt_date(s):
    try:
        p = s[:10].split("-")
        return f"{int(p[2])} {MONTH_TR[int(p[1])]} {p[0]}"
    except Exception:
        return s


def kb(buttons, cols=1):
    rows = []
    row = []

    for lbl, data in buttons:
        row.append(InlineKeyboardButton(lbl, callback_data=data))
        if len(row) == cols:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return InlineKeyboardMarkup(rows)


def send_mail(subject, body):
    if not all([GMAIL, GPASS, MAILTO]):
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL
    msg["To"] = MAILTO

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL, GPASS)
            s.send_message(msg)
    except Exception:
        pass


def search_own_api(origin, dest, month_str, yon):
    try:
        r = requests.get(
            f"{FLIGHT_API_URL}/flights",
            params={
                "from": origin,
                "to": dest,
                "month": month_str,
                "student": "true" if STUDENT_MODE else "false",
            },
            timeout=20,
        )

        if r.status_code != 200:
            return []

        data = r.json()
        results = []

        for item in data.get("results", []):
            price = float(item.get("price", 0))
            results.append(
                {
                    "yon": "Gidis" if yon == "gidis" else "Donus",
                    "kalkis": item.get("from", origin),
                    "varis": item.get("to", dest),
                    "fiyat": price,
                    "tarih": item.get("departureDate", month_str),
                    "link": item.get("link", ""),
                    "airline": item.get("airline", "Bilinmeyen"),
                    "provider": item.get("provider", "api"),
                    "passenger_type": item.get("passengerType", "student" if STUDENT_MODE else "adult"),
                }
            )

        return results

    except Exception as e:
        print("Flight API hatasi:", e)
        return []


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()

    await update.message.reply_text(
        "Selam! Ne yapmak istersin?",
        reply_markup=kb(
            [
                ("Ucus Ara", "ara"),
                ("Fiyat Alarmi Kur", "alarm"),
                ("Yardim", "yardim"),
            ]
        ),
    )
    return S_MENU


async def menu_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sec = q.data

    if sec == "yardim":
        await q.edit_message_text(
            "Ne yapabilirim?\n\n"
            "Ucus Ara: Kalkis, varis, yon ve ay secersin; ben kendi API'nden sonuc getiririm.\n\n"
            "Fiyat Alarmi: Esik fiyat belirleyebilirsin.",
            reply_markup=kb([("Geri", "geri")]),
        )
        return S_MENU

    if sec == "geri":
        await q.edit_message_text(
            "Ne yapmak istersin?",
            reply_markup=kb(
                [
                    ("Ucus Ara", "ara"),
                    ("Fiyat Alarmi Kur", "alarm"),
                    ("Yardim", "yardim"),
                ]
            ),
        )
        return S_MENU

    ctx.user_data["mod"] = sec

    await q.edit_message_text(
        "Hangi havalimanindan kalkacaksin?",
        reply_markup=kb(
            [
                ("Dortmund (DTM)", "DTM"),
                ("Dusseldorf (DUS)", "DUS"),
                ("Koln/Bonn (CGN)", "CGN"),
                ("Hepsine Bak", "ALL"),
            ]
        ),
    )
    return S_KALKIS


async def kalkis_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data["kalkis"] = q.data

    await q.edit_message_text(
        "Nereye gidiyorsun?",
        reply_markup=kb(
            [
                ("Sinop (NOP)", "NOP"),
                ("Baska bir yer", "baska"),
            ]
        ),
    )
    return S_VARIS_ONAY


async def varis_onay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "baska":
        await q.edit_message_text(
            "Tamam! Varis havalimaninin IATA kodunu yaz.\n"
            "Ornek: IST, AYT, ESB, SAW"
        )
        return S_VARIS_YAZ

    ctx.user_data["varis"] = q.data
    return await yon_sor(q)


async def varis_yaz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kod = update.message.text.strip().upper()

    if len(kod) != 3 or not kod.isalpha():
        await update.message.reply_text("IATA kodu 3 harf olmali. Tekrar yaz, orn: IST")
        return S_VARIS_YAZ

    ctx.user_data["varis"] = kod
    msg = await update.message.reply_text("Tamam.")

    await msg.edit_text(
        "Gidis mi, donus mu, yoksa ikisi de mi?",
        reply_markup=kb(
            [
                ("Gidis", "gidis"),
                ("Donus", "donus"),
                ("Ikisi De", "ikisi"),
            ],
            cols=2,
        ),
    )
    return S_YON


async def yon_sor(q):
    await q.edit_message_text(
        "Gidis mi, donus mu, yoksa ikisi de mi?",
        reply_markup=kb(
            [
                ("Gidis", "gidis"),
                ("Donus", "donus"),
                ("Ikisi De", "ikisi"),
            ],
            cols=2,
        ),
    )
    return S_YON


async def yon_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    ctx.user_data["yon"] = q.data

    butonlar = []
    today = date.today()

    for i in range(6):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + (today.month - 1 + i) // 12
        ms = f"{y}-{m:02d}"
        butonlar.append((f"{MONTH_TR[m]} {y}", ms))

    butonlar.append(("Geri", "geri_menu"))

    await q.edit_message_text("Hangi ay?", reply_markup=kb(butonlar, cols=2))
    return S_AY


async def ay_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "geri_menu":
        await q.edit_message_text(
            "Ne yapmak istersin?",
            reply_markup=kb(
                [
                    ("Ucus Ara", "ara"),
                    ("Fiyat Alarmi Kur", "alarm"),
                    ("Yardim", "yardim"),
                ]
            ),
        )
        return S_MENU

    ctx.user_data["ay"] = q.data

    mod = ctx.user_data.get("mod", "ara")

    if mod == "alarm":
        await q.edit_message_text(
            "Kac euro altina dusunce haber vereyim?",
            reply_markup=kb(
                [
                    ("200 euro", "200"),
                    ("150 euro", "150"),
                    ("100 euro", "100"),
                    ("Kendim yazayim", "yaz"),
                ],
                cols=2,
            ),
        )
        return S_ESIK_ONA

    kalkis = ctx.user_data.get("kalkis", "DTM")
    varis = ctx.user_data.get("varis", "NOP")
    yon = ctx.user_data.get("yon", "gidis")
    ay = q.data

    await q.edit_message_text("Araniyor, bir saniye...")
    await _ara_ve_goster(q.message, ctx, kalkis, varis, yon, ay)
    return ConversationHandler.END


async def esik_ona(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "yaz":
        await q.edit_message_text("Tamam, kac euro? Sadece sayi yaz, orn: 180")
        return S_ESIK_YAZ

    ctx.user_data["esik"] = float(q.data)
    await _alarm_kaydet(q.message, ctx)
    return ConversationHandler.END


async def esik_yaz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        esik = float(update.message.text.strip().replace("€", "").replace(",", "."))
        ctx.user_data["esik"] = esik
        await _alarm_kaydet(update.message, ctx)
    except Exception:
        await update.message.reply_text("Sadece sayi yaz, orn: 180")
        return S_ESIK_YAZ

    return ConversationHandler.END


async def _alarm_kaydet(msg, ctx):
    kalkis = ctx.user_data.get("kalkis", "DTM")
    varis = ctx.user_data.get("varis", "NOP")
    yon = ctx.user_data.get("yon", "gidis")
    ay = ctx.user_data.get("ay", "")
    esik = ctx.user_data.get("esik", 200)

    yon_label = {
        "gidis": "Gidis",
        "donus": "Donus",
        "ikisi": "Gidis + Donus",
    }.get(yon, yon)

    y, m = ay.split("-")
    ay_label = f"{MONTH_TR[int(m)]} {y}"

    await msg.reply_text(
        f"Alarm kuruldu!\n\n"
        f"{kalkis} -> {varis}\n"
        f"{yon_label}\n"
        f"{ay_label}\n"
        f"Esik: {esik:.0f} euro\n\n"
        f"/start ile yeni arama yapabilirsin.",
        reply_markup=kb([("Yeni Arama", "yeni")]),
    )


async def _ara_ve_goster(msg, ctx, kalkis, varis, yon, ay):
    rate = get_try_rate()
    y, m = ay.split("-")
    ay_label = f"{MONTH_TR[int(m)]} {y}"
    yon_label = {
        "gidis": "Gidis",
        "donus": "Donus",
        "ikisi": "Gidis + Donus",
    }.get(yon, yon)

    originler = ["DTM", "DUS", "CGN"] if kalkis == "ALL" else [kalkis]
    sonuclar = []

    for origin in originler:
        if yon in ("gidis", "ikisi"):
            api_results = search_own_api(origin, varis, ay, "gidis")

            for s in api_results:
                s["try"] = s["fiyat"] * rate
                sonuclar.append(s)

        if yon in ("donus", "ikisi"):
            api_results = search_own_api(varis, origin, ay, "donus")

            for s in api_results:
                s["try"] = s["fiyat"] * rate
                sonuclar.append(s)

    if not sonuclar:
        await msg.reply_text(
            f"{ay_label} icin sonuc bulunamadi.\n"
            "Kendi API su an sonuc dondurmedi. Flight API calisiyor mu kontrol et.\n\n"
            "/start ile yeni arama yapabilirsin.",
            reply_markup=kb([("Yeni Arama", "yeni")]),
        )
        return

    sonuclar.sort(key=lambda x: x["fiyat"])
    ctx.user_data["sonuclar"] = sonuclar

    lines = [f"{ay_label} - {yon_label}\n"]

    for i, s in enumerate(sonuclar[:5], 1):
        firsat = " FIRSAT" if s["fiyat"] <= 200 else ""
        airline = s.get("airline", "Bilinmeyen")
        provider = s.get("provider", "api")
        passenger_label = "Ogrenci" if s.get("passenger_type") == "student" else "Normal"

        lines += [
            f"{i}. {s['yon']}: {s['kalkis']} -> {s['varis']}{firsat}",
            f"   Havayolu: {airline}",
            f"   Yolcu tipi: {passenger_label}",
            f"   Tarih: {fmt_date(s['tarih'])}",
            f"   Fiyat: {s['fiyat']:.0f} euro yaklasik {s['try']:,.0f} TL",
            f"   Kaynak: {provider}",
            "",
        ]

    lines.append("Hangi biletin linkini istiyorsun?")

    butonlar = [(str(i), f"link_{i-1}") for i in range(1, min(len(sonuclar) + 1, 6))]
    butonlar.append(("Yeni Arama", "yeni"))

    await msg.reply_text("\n".join(lines), reply_markup=kb(butonlar, cols=3))


async def link_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "yeni":
        ctx.user_data.clear()
        await q.edit_message_text(
            "Ne yapmak istersin?",
            reply_markup=kb(
                [
                    ("Ucus Ara", "ara"),
                    ("Fiyat Alarmi Kur", "alarm"),
                    ("Yardim", "yardim"),
                ]
            ),
        )
        return S_MENU

    if q.data.startswith("link_"):
        idx = int(q.data.split("_")[1])
        sonuclar = ctx.user_data.get("sonuclar", [])

        if idx >= len(sonuclar):
            await q.answer("Bulunamadi.", show_alert=True)
            return S_MENU

        s = sonuclar[idx]
        link = s.get("link", "")

        if link:
            text = (
                f"Iste linkin!\n\n"
                f"{s['yon']}: {s['kalkis']} -> {s['varis']}\n"
                f"Havayolu: {s.get('airline', 'Bilinmeyen')}\n"
                f"Tarih: {fmt_date(s['tarih'])}\n"
                f"Fiyat: {s['fiyat']:.0f} euro yaklasik {s['try']:,.0f} TL\n\n"
                f"{link}\n\n"
                f"Fiyatlar degisebilir, almadan once teyit et."
            )
        else:
            text = (
                f"{s['yon']}: {s['kalkis']} -> {s['varis']}\n"
                f"Havayolu: {s.get('airline', 'Bilinmeyen')}\n"
                f"Tarih: {fmt_date(s['tarih'])}\n"
                f"Fiyat: {s['fiyat']:.0f} euro yaklasik {s['try']:,.0f} TL\n\n"
                f"Bu kayitta link yok. Almadan once havayolu sitesinden teyit et."
            )

        await q.edit_message_text(text, reply_markup=kb([("Yeni Arama", "yeni")]))

        if s["fiyat"] <= 200:
            send_mail(
                f"{s['fiyat']:.0f} euro - {s['kalkis']}->{s['varis']}",
                text,
            )

        return S_MENU

    return S_MENU


async def iptal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Iptal ettim. /start ile tekrar baslayabilirsin.")
    return ConversationHandler.END


async def bilinmeyen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Merhaba! /start yaz, seni yonlendireyim.")


def main():
    start_health_server()

    app = Application.builder().token(TG_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(
                filters.Regex(r"(?i)(merhaba|selam|hi|hey|hello|basla|naber|nasilsin)"),
                start,
            ),
        ],
        states={
            S_MENU: [CallbackQueryHandler(menu_sec)],
            S_KALKIS: [CallbackQueryHandler(kalkis_sec)],
            S_VARIS_ONAY: [CallbackQueryHandler(varis_onay)],
            S_VARIS_YAZ: [MessageHandler(filters.TEXT & ~filters.COMMAND, varis_yaz)],
            S_YON: [CallbackQueryHandler(yon_sec)],
            S_AY: [CallbackQueryHandler(ay_sec)],
            S_ESIK_ONA: [CallbackQueryHandler(esik_ona)],
            S_ESIK_YAZ: [MessageHandler(filters.TEXT & ~filters.COMMAND, esik_yaz)],
        },
        fallbacks=[
            CommandHandler("iptal", iptal),
            CallbackQueryHandler(link_sec, pattern="^(yeni|link_)"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(link_sec, pattern="^(yeni|link_)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bilinmeyen))

    logging.info("Bot baslatildi!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
