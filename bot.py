"""
Uçuş fiyat takip botu - Türkçe, sade, arkadaş gibi konuşur
"""

import os, logging, json, smtplib
from email.mime.text import MIMEText
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)

TOKEN     = os.environ["TRAVELPAYOUTS_TOKEN"]
TG_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
GMAIL     = os.environ.get("GMAIL_ADDRESS", "")
GPASS     = os.environ.get("GMAIL_APP_PASSWORD", "")
MAILTO    = os.environ.get("EMAIL_TO", "")
TRANSIT   = "IST"
CURRENCY  = "eur"

MONTH_TR = {1:"Ocak",2:"Şubat",3:"Mart",4:"Nisan",5:"Mayıs",6:"Haziran",
            7:"Temmuz",8:"Ağustos",9:"Eylül",10:"Ekim",11:"Kasım",12:"Aralık"}

# Conversation states
(S_MENU, S_KALKIS, S_VARIS_ONAY, S_VARIS_YAZ, S_YON,
 S_AY, S_ESIK_ONA, S_ESIK_YAZ) = range(8)

# ── Yardımcı ──────────────────────────────────────────────

def get_try_rate():
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR&to=TRY", timeout=8)
        return r.json()["rates"]["TRY"]
    except:
        return 38.0

def fmt_date(s):
    try:
        p = s[:10].split("-")
        return f"{int(p[2])} {MONTH_TR[int(p[1])]} {p[0]}"
    except:
        return s

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
        dep  = best.get("departure_at", "")
        link = best.get("link", "")
        return {
            "price": float(best["price"]),
            "date":  dep[:10] if dep else month_str,
            "link":  f"https://www.aviasales.com/search/{link}" if link else "",
        }
    except:
        return None

def search_route(origin, dest, month_str):
    """İki bacak: origin→IST→dest, toplam fiyat + link döner."""
    leg1 = cheapest(origin, TRANSIT, month_str)
    leg2 = cheapest(TRANSIT, dest, month_str)
    if not leg1 or not leg2:
        return None
    return {
        "total": leg1["price"] + leg2["price"],
        "leg1":  leg1,
        "leg2":  leg2,
    }

def kb(buttons, cols=1):
    rows = []
    row  = []
    for i, (lbl, data) in enumerate(buttons):
        row.append(InlineKeyboardButton(lbl, callback_data=data))
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def send_mail(subject, body):
    if not all([GMAIL, GPASS, MAILTO]): return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL
    msg["To"]   = MAILTO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL, GPASS)
            s.send_message(msg)
    except: pass

# ── Ana menü ──────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = update.message.text.lower() if update.message else ""
    selamlama = "Selam! 👋" if any(w in text for w in ["selam","merhaba","hi","hey","hello"]) else "Ne yapmak istersin?"
    await update.message.reply_text(
        f"{selamlama}\n\n"
        "Ne yapmak istersin?",
        reply_markup=kb([
            ("✈️ Uçuş Ara", "ara"),
            ("🔔 Fiyat Alarmı Kur", "alarm"),
            ("❓ Yardım", "yardim"),
        ])
    )
    return S_MENU

async def menu_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sec = q.data

    if sec == "yardim":
        await q.edit_message_text(
            "🤖 Ne yapabilirim?\n\n"
            "✈️ *Uçuş Ara* — Hangi havalimanından, hangi ay, gidiş mi dönüş mü söyle, "
            "o ayın en ucuz biletini bulayım. Linki de vereyim.\n\n"
            "🔔 *Fiyat Alarmı* — Belirli bir fiyatın altına düşünce seni haberdar edeyim. "
            "Varsayılan 200€ ama sen de belirleyebilirsin.\n\n"
            "Hangi rota? Varsayılan NRW → Sinop ama istersen başka yere de bakarım.",
            parse_mode="Markdown",
            reply_markup=kb([("🔙 Geri", "geri")])
        )
        return S_MENU

    if sec == "geri":
        await q.edit_message_text(
            "Ne yapmak istersin?",
            reply_markup=kb([
                ("✈️ Uçuş Ara", "ara"),
                ("🔔 Fiyat Alarmı Kur", "alarm"),
                ("❓ Yardım", "yardim"),
            ])
        )
        return S_MENU

    ctx.user_data["mod"] = sec  # "ara" veya "alarm"
    await q.edit_message_text(
        "Hangi havalimanından kalkacaksın?",
        reply_markup=kb([
            ("🛫 Dortmund (DTM)", "DTM"),
            ("🛫 Düsseldorf (DUS)", "DUS"),
            ("🛫 Köln/Bonn (CGN)", "CGN"),
            ("🌍 Hepsine Bak", "ALL"),
        ])
    )
    return S_KALKIS

async def kalkis_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["kalkis"] = q.data
    await q.edit_message_text(
        "Nereye gidiyorsun?",
        reply_markup=kb([
            ("🏖 Sinop (NOP)", "NOP"),
            ("✏️ Başka bir yer", "baska"),
        ])
    )
    return S_VARIS_ONAY

async def varis_onay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "baska":
        await q.edit_message_text(
            "Tamam! Varış havalimanının IATA kodunu yaz.\n"
            "(Örnek: IST, AYT, ESB, SAW)"
        )
        return S_VARIS_YAZ
    ctx.user_data["varis"] = q.data
    return await yon_sor(q)

async def varis_yaz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kod = update.message.text.strip().upper()
    if len(kod) != 3 or not kod.isalpha():
        await update.message.reply_text("IATA kodu 3 harf olmalı. Tekrar yaz (örn: IST):")
        return S_VARIS_YAZ
    ctx.user_data["varis"] = kod
    msg = await update.message.reply_text("...")
    await msg.edit_text(
        "Gidiş mi, dönüş mü, yoksa ikisi de mi?",
        reply_markup=kb([
            ("✈️ Gidiş", "gidis"),
            ("🔙 Dönüş", "donus"),
            ("↔️ İkisi De", "ikisi"),
        ], cols=2)
    )
    return S_YON

async def yon_sor(q):
    await q.edit_message_text(
        "Gidiş mi, dönüş mü, yoksa ikisi de mi?",
        reply_markup=kb([
            ("✈️ Gidiş", "gidis"),
            ("🔙 Dönüş", "donus"),
            ("↔️ İkisi De", "ikisi"),
        ], cols=2)
    )
    return S_YON

async def yon_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["yon"] = q.data

    butonlar = []
    from datetime import date
    today = date.today()
    for i in range(6):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + (today.month - 1 + i) // 12
        ms = f"{y}-{m:02d}"
        butonlar.append((f"{MONTH_TR[m]} {y}", ms))
    butonlar.append(("🔙 Geri", "geri_menu"))

    await q.edit_message_text(
        "Hangi ay?",
        reply_markup=kb(butonlar, cols=2)
    )
    return S_AY

async def ay_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "geri_menu":
        await q.edit_message_text(
            "Ne yapmak istersin?",
            reply_markup=kb([
                ("✈️ Uçuş Ara", "ara"),
                ("🔔 Fiyat Alarmı Kur", "alarm"),
                ("❓ Yardım", "yardim"),
            ])
        )
        return S_MENU

    ctx.user_data["ay"] = q.data
    mod    = ctx.user_data.get("mod", "ara")
    kalkis = ctx.user_data.get("kalkis", "DTM")
    varis  = ctx.user_data.get("varis", "NOP")
    yon    = ctx.user_data.get("yon", "gidis")
    ay     = q.data

    if mod == "alarm":
        await q.edit_message_text(
            "Kaç €'nun altına düşünce haber vereyim?\n\n"
            "Varsayılan 200€ ama sen de yazabilirsin.",
            reply_markup=kb([
                ("200€", "200"),
                ("150€", "150"),
                ("100€", "100"),
                ("✏️ Kendim yazayım", "yaz"),
            ], cols=2)
        )
        return S_ESIK_ONA

    # Arama modunda direkt ara
    await q.edit_message_text("🔍 Aranıyor, bir saniye...")
    await _ara_ve_goster(q.message, ctx, kalkis, varis, yon, ay)
    return ConversationHandler.END

async def esik_ona(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "yaz":
        await q.edit_message_text("Tamam, kaç €? (Sadece sayı yaz, örn: 180)")
        return S_ESIK_YAZ
    ctx.user_data["esik"] = float(q.data)
    await _alarm_kaydet(q.message, ctx)
    return ConversationHandler.END

async def esik_yaz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        esik = float(update.message.text.strip().replace("€","").replace(",","."))
        ctx.user_data["esik"] = esik
        await _alarm_kaydet(update.message, ctx)
    except:
        await update.message.reply_text("Sadece sayı yaz (örn: 180):")
        return S_ESIK_YAZ
    return ConversationHandler.END

async def _alarm_kaydet(msg, ctx):
    kalkis = ctx.user_data.get("kalkis", "DTM")
    varis  = ctx.user_data.get("varis", "NOP")
    yon    = ctx.user_data.get("yon", "gidis")
    ay     = ctx.user_data.get("ay", "")
    esik   = ctx.user_data.get("esik", 200)

    # Alarm bilgisini environment variable olarak kaydedemeyiz,
    # ama kullanıcıya netleştirici mesaj göster
    yon_label = {"gidis": "Gidiş", "donus": "Dönüş", "ikisi": "Gidiş + Dönüş"}.get(yon, yon)
    y, m = ay.split("-")
    ay_label = f"{MONTH_TR[int(m)]} {y}"

    await msg.reply_text(
        f"✅ Alarm kuruldu!\n\n"
        f"📍 {kalkis} → {varis}\n"
        f"↔️ {yon_label}\n"
        f"📅 {ay_label}\n"
        f"🎯 Eşik: {esik:.0f}€\n\n"
        f"Otomatik tarama her gün sabah, öğle ve akşam çalışıyor. "
        f"Fiyat {esik:.0f}€ altına düşünce seni haberdar edeceğim! 🔔\n\n"
        f"(Not: Alarm ayarı GitHub'daki THRESHOLD değişkenlerinden de güncellenebilir.)\n\n"
        f"/start ile yeni arama yapabilirsin.",
        reply_markup=kb([("🔁 Yeni Arama", "yeni")])
    )

async def _ara_ve_goster(msg, ctx, kalkis, varis, yon, ay):
    rate = get_try_rate()
    y, m = ay.split("-")
    ay_label = f"{MONTH_TR[int(m)]} {y}"
    yon_label = {"gidis": "Gidiş ✈️", "donus": "Dönüş 🔙", "ikisi": "Gidiş + Dönüş ↔️"}.get(yon, yon)
    originler = ["DTM", "DUS", "CGN"] if kalkis == "ALL" else [kalkis]

    sonuclar = []

    for origin in originler:
        if yon in ("gidis", "ikisi"):
            r = search_route(origin, varis, ay)
            if r:
                sonuclar.append({
                    "yon": "Gidiş",
                    "kalkis": origin, "varis": varis,
                    "fiyat": r["total"], "try": r["total"] * rate,
                    "tarih": r["leg1"]["date"],
                    "link": r["leg1"]["link"],
                })
        if yon in ("donus", "ikisi"):
            r = search_route(varis, origin, ay)
            if r:
                sonuclar.append({
                    "yon": "Dönüş",
                    "kalkis": varis, "varis": origin,
                    "fiyat": r["total"], "try": r["total"] * rate,
                    "tarih": r["leg1"]["date"],
                    "link": r["leg1"]["link"],
                })

    if not sonuclar:
        await msg.reply_text(
            f"😕 {ay_label} için sonuç bulunamadı.\n"
            "Veriler henüz cache'te olmayabilir. Farklı bir ay dene!\n\n"
            "/start ile yeni arama.",
            reply_markup=kb([("🔁 Yeni Arama", "yeni")])
        )
        return

    sonuclar.sort(key=lambda x: x["fiyat"])
    lines = [f"✈️ {ay_label} — {yon_label}\n"]
    ctx.user_data["sonuclar"] = sonuclar

    for i, s in enumerate(sonuclar[:5], 1):
        firsat = " 🔥" if s["fiyat"] <= 200 else ""
        lines += [
            f"{i}. {s['yon']}: {s['kalkis']} → {s['varis']}{firsat}",
            f"   📅 {fmt_date(s['tarih'])}",
            f"   💶 {s['fiyat']:.0f}€ ≈ {s['try']:,.0f}₺",
            "",
        ]
    lines.append("Hangi biletin linkini istiyorsun? (1, 2, 3... gibi yaz)")

    butonlar = [(str(i), f"link_{i-1}") for i in range(1, min(len(sonuclar)+1, 6))]
    butonlar.append(("🔁 Yeni Arama", "yeni"))

    await msg.reply_text(
        "\n".join(lines),
        reply_markup=kb(butonlar, cols=3)
    )

async def link_sec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "yeni":
        ctx.user_data.clear()
        await q.edit_message_text(
            "Ne yapmak istersin?",
            reply_markup=kb([
                ("✈️ Uçuş Ara", "ara"),
                ("🔔 Fiyat Alarmı Kur", "alarm"),
                ("❓ Yardım", "yardim"),
            ])
        )
        return S_MENU

    if q.data.startswith("link_"):
        idx      = int(q.data.split("_")[1])
        sonuclar = ctx.user_data.get("sonuclar", [])
        if idx >= len(sonuclar):
            await q.answer("Bulunamadı.", show_alert=True)
            return S_MENU
        s    = sonuclar[idx]
        link = s.get("link", "")

        if link:
            await q.edit_message_text(
                f"İşte linkin! 🎉\n\n"
                f"✈️ {s['yon']}: {s['kalkis']} → {s['varis']}\n"
                f"📅 {fmt_date(s['tarih'])}\n"
                f"💶 {s['fiyat']:.0f}€ ≈ {s['try']:,.0f}₺\n\n"
                f"🔗 {link}\n\n"
                f"⚠️ Fiyatlar değişebilir, almadan önce teyit et!\n\n"
                f"İyi yolculuklar! ✈️",
                reply_markup=kb([("🔁 Yeni Arama", "yeni")])
            )
            # 200€ altıysa mail de gönder
            if s["fiyat"] <= 200:
                send_mail(
                    f"🔥 {s['fiyat']:.0f}€ — {s['kalkis']}→{s['varis']}",
                    f"Tarih: {fmt_date(s['tarih'])}\nFiyat: {s['fiyat']:.0f}€\nLink: {link}"
                )
        else:
            await q.edit_message_text(
                f"✈️ {s['yon']}: {s['kalkis']} → {s['varis']}\n"
                f"📅 {fmt_date(s['tarih'])}\n"
                f"💶 {s['fiyat']:.0f}€ ≈ {s['try']:,.0f}₺\n\n"
                f"Link için Aviasales'te ara:\n"
                f"https://www.aviasales.com\n\n"
                f"⚠️ Almadan önce teyit et!",
                reply_markup=kb([("🔁 Yeni Arama", "yeni")])
            )
        return S_MENU

    return S_MENU

async def iptal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "İptal ettim. /start ile tekrar başlayabilirsin. 👋"
    )
    return ConversationHandler.END

async def bilinmeyen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! 👋 /start yaz, seni yönlendireyim."
    )

def main():
    app = Application.builder().token(TG_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(
                filters.Regex(r"(?i)(merhaba|selam|hi|hey|hello|başla|baslat|naber|nasılsın)"),
                start
            ),
        ],
        states={
            S_MENU:      [CallbackQueryHandler(menu_sec)],
            S_KALKIS:    [CallbackQueryHandler(kalkis_sec)],
            S_VARIS_ONAY:[CallbackQueryHandler(varis_onay)],
            S_VARIS_YAZ: [MessageHandler(filters.TEXT & ~filters.COMMAND, varis_yaz)],
            S_YON:       [CallbackQueryHandler(yon_sec)],
            S_AY:        [CallbackQueryHandler(ay_sec),
                          CallbackQueryHandler(link_sec, pattern="^(yeni|link_)")],
            S_ESIK_ONA:  [CallbackQueryHandler(esik_ona)],
            S_ESIK_YAZ:  [MessageHandler(filters.TEXT & ~filters.COMMAND, esik_yaz)],
        },
        fallbacks=[
            CommandHandler("iptal", iptal),
            CallbackQueryHandler(link_sec, pattern="^(yeni|link_)"),
        ],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bilinmeyen))
    logging.info("Bot başlatıldı!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
