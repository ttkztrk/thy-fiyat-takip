"""
Uçuş Fiyat Takip - İnteraktif Telegram Botu
Kiwi Tequila API - tüm havayolları - butonlu arayüz
"""

import os, time, logging, smtplib
from email.mime.text import MIMEText
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ── Env ───────────────────────────────────────────────────
KIWI_KEY   = os.environ["KIWI_API_KEY"]
TG_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
GMAIL_ADDR = os.environ.get("GMAIL_ADDRESS")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD")
EMAIL_TO   = os.environ.get("EMAIL_TO")
THRESHOLD  = float(os.environ.get("PRICE_THRESHOLD", "200"))

# ── Conversation states ────────────────────────────────────
(S_ORIGIN, S_DEST, S_TRIP, S_DEP_DATE, S_RET_DATE,
 S_AIRLINE, S_RESULTS, S_CONFIRM) = range(8)

# ── Sabit veriler ──────────────────────────────────────────
AIRPORT_OPTS = [
    ("✈️ Dortmund (DTM)",   "DTM"),
    ("✈️ Düsseldorf (DUS)", "DUS"),
    ("✈️ Köln/Bonn (CGN)",  "CGN"),
    ("🌍 Hepsini Ara",       "ALL"),
]
DEST_OPTS = [
    ("🏖 Sinop (NOP)",       "NOP"),
    ("🌆 İstanbul (IST)",    "IST"),
    ("✏️ Başka şehir yaz",   "CUSTOM"),
]
AIRLINE_OPTS = [
    ("🌍 Tüm Havayolları",   "all"),
    ("🇹🇷 THY",              "TK"),
    ("🟠 Pegasus",           "PC"),
    ("🟡 SunExpress",        "XQ"),
]
MONTH_TR = {
    1:"Ocak",2:"Şubat",3:"Mart",4:"Nisan",5:"Mayıs",6:"Haziran",
    7:"Temmuz",8:"Ağustos",9:"Eylül",10:"Ekim",11:"Kasım",12:"Aralık"
}
AIRLINE_NAMES = {
    "TK":"Turkish Airlines","PC":"Pegasus","XQ":"SunExpress",
    "W6":"Wizz Air","FR":"Ryanair","LH":"Lufthansa",
    "VY":"Vueling","U2":"easyJet",
}

# ── Yardımcılar ───────────────────────────────────────────

def get_try_rate():
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest?from=EUR&to=TRY",
            timeout=8
        )
        return r.json()["rates"]["TRY"]
    except:
        return 38.0

def fmt_dt(ts):
    """Unix timestamp → '15 Temmuz 2026, 07:30'"""
    try:
        d = datetime.utcfromtimestamp(ts)
        return f"{d.day} {MONTH_TR[d.month]} {d.year}, {d.strftime('%H:%M')}"
    except:
        return "?"

def parse_date(text):
    """Birden fazla formatı destekler → DD/MM/YYYY döner ya da None."""
    text = text.strip().replace(".", "/").replace("-", "/")
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except:
            pass
    return None

def kb(buttons):
    """buttons: [(label, callback_data), ...] → InlineKeyboardMarkup"""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(lbl, callback_data=data)]
         for lbl, data in buttons]
    )

def kb_row(buttons):
    """İki sütun yerleşim."""
    rows = []
    for i in range(0, len(buttons), 2):
        row = [InlineKeyboardButton(b[0], callback_data=b[1])
               for b in buttons[i:i+2]]
        rows.append(row)
    return InlineKeyboardMarkup(rows)

# ── Kiwi API ──────────────────────────────────────────────

def search_kiwi(fly_from, fly_to, date_from, date_to,
                return_from=None, return_to=None,
                airline=None, limit=5):
    params = {
        "fly_from": fly_from, "fly_to": fly_to,
        "date_from": date_from, "date_to": date_to,
        "curr": "EUR", "limit": limit, "sort": "price",
        "partner_market": "de", "adults": 1,
        "max_stopovers": 2,
    }
    if return_from:
        params["return_from"] = return_from
        params["return_to"]   = return_to or return_from
    if airline and airline != "all":
        params["select_airlines"] = airline

    try:
        r = requests.get(
            "https://tequila.kiwi.com/v2/search",
            headers={"apikey": KIWI_KEY},
            params=params, timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("data", [])
        log.warning(f"Kiwi {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log.error(f"Kiwi hata: {e}")
    return []

def format_flights(flights, rate, trip_type="one"):
    """Uçuş listesini okunabilir metin + link listesi olarak döner."""
    if not flights:
        return "❌ Sonuç bulunamadı.", []

    lines = []
    links = []
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]

    for i, f in enumerate(flights[:5]):
        price    = float(f["price"])
        try_price = price * rate
        airline  = AIRLINE_NAMES.get(f.get("airlines",["?"])[0],
                                     f.get("airlines",["?"])[0])
        dep      = fmt_dt(f.get("dTime", 0))
        arr      = fmt_dt(f.get("aTime", 0))
        frm      = f.get("flyFrom","?")
        to       = f.get("flyTo","?")
        link     = f.get("deep_link","")

        cheap_tag = " 🔥" if price <= 200 else ""
        lines += [
            f"{emojis[i]} {airline}{cheap_tag}",
            f"   {frm} → {to}",
            f"   🛫 {dep}",
            f"   🛬 {arr}",
            f"   💶 {price:.0f} € ({try_price:,.0f} ₺)",
            "",
        ]
        links.append(link)

    return "\n".join(lines), links

# ── E-posta ───────────────────────────────────────────────

def send_mail(subject, body):
    if not all([GMAIL_ADDR, GMAIL_PASS, EMAIL_TO]):
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDR
    msg["To"]      = EMAIL_TO
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_ADDR, GMAIL_PASS)
            s.send_message(msg)
    except Exception as e:
        log.error(f"Mail hata: {e}")

# ── Conversation Handlers ──────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "✈️ Merhaba! Uçuş araması yapalım.\n\n"
        "Nereden uçmak istiyorsun?",
        reply_markup=kb_row(AIRPORT_OPTS)
    )
    return S_ORIGIN

async def origin_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["origin"] = q.data
    label = next(l for l, d in AIRPORT_OPTS if d == q.data)
    await q.edit_message_text(
        f"Kalkış: {label}\n\nNereye gitmek istiyorsun?",
        reply_markup=kb_row(DEST_OPTS)
    )
    return S_DEST

async def dest_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "CUSTOM":
        await q.edit_message_text(
            "Hedef havalimanının IATA kodunu yaz (örn: IST, AYT, ESB):"
        )
        return S_DEST
    ctx.user_data["dest"] = q.data
    label = next((l for l, d in DEST_OPTS if d == q.data), q.data)
    await q.edit_message_text(
        f"Hedef: {label}\n\nSeyahat türünü seç:",
        reply_markup=kb([
            ("✈️ Sadece Gidiş", "one"),
            ("🔄 Gidiş - Dönüş", "round"),
        ])
    )
    return S_TRIP

async def dest_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı IATA kodu yazdıysa."""
    code = update.message.text.strip().upper()
    if len(code) != 3 or not code.isalpha():
        await update.message.reply_text(
            "⚠️ Lütfen geçerli bir 3 harfli IATA kodu gir (örn: IST)."
        )
        return S_DEST
    ctx.user_data["dest"] = code
    await update.message.reply_text(
        f"Hedef: {code}\n\nSeyahat türünü seç:",
        reply_markup=kb([
            ("✈️ Sadece Gidiş", "one"),
            ("🔄 Gidiş - Dönüş", "round"),
        ])
    )
    return S_TRIP

async def trip_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["trip"] = q.data
    await q.edit_message_text(
        "🗓 Gidiş tarih aralığı?\n\n"
        "Örnek: 15/07/2026 - 31/07/2026\n"
        "(Başlangıç - Bitiş)"
    )
    return S_DEP_DATE

async def dep_date_entered(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # "15/07/2026 - 31/07/2026" veya "15/07/2026-31/07/2026"
    parts = [p.strip() for p in text.replace(" - ","-").split("-", 2)]
    # Eğer "-" ile ay/gün birbirine karışmasın diye "/" kontrolü
    if len(parts) >= 2:
        # Son deneme: DD/MM/YYYY-DD/MM/YYYY ya da DD/MM/YYYY - DD/MM/YYYY
        raw = text.replace(" ","")
        halves = raw.split("-",1) if raw.count("-")==1 else None
        if halves is None:
            # birden fazla - var, DD/MM/YYYY şeklinde split
            idx = text.rfind(" - ")
            if idx != -1:
                halves = [text[:idx].strip(), text[idx+3:].strip()]
            else:
                halves = None

        if halves:
            d1 = parse_date(halves[0])
            d2 = parse_date(halves[1])
            if d1 and d2:
                ctx.user_data["dep_from"] = d1
                ctx.user_data["dep_to"]   = d2
                if ctx.user_data.get("trip") == "round":
                    await update.message.reply_text(
                        "🗓 Dönüş tarih aralığı?\n\nÖrnek: 10/08/2026 - 31/08/2026"
                    )
                    return S_RET_DATE
                else:
                    await update.message.reply_text(
                        "Hangi havayolunda arayım?",
                        reply_markup=kb_row(AIRLINE_OPTS)
                    )
                    return S_AIRLINE

    await update.message.reply_text(
        "⚠️ Format anlaşılamadı. Şu şekilde gir:\n"
        "15/07/2026 - 31/07/2026"
    )
    return S_DEP_DATE

async def ret_date_entered(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    raw = text.replace(" ","")
    idx = text.rfind(" - ")
    if idx != -1:
        halves = [text[:idx].strip(), text[idx+3:].strip()]
    else:
        halves = raw.split("-",1) if raw.count("-")==1 else [raw, raw]

    d1 = parse_date(halves[0])
    d2 = parse_date(halves[1]) if len(halves)>1 else d1
    if d1 and d2:
        ctx.user_data["ret_from"] = d1
        ctx.user_data["ret_to"]   = d2
        await update.message.reply_text(
            "Hangi havayolunda arayım?",
            reply_markup=kb_row(AIRLINE_OPTS)
        )
        return S_AIRLINE

    await update.message.reply_text(
        "⚠️ Format anlaşılamadı. Şu şekilde gir:\n"
        "10/08/2026 - 31/08/2026"
    )
    return S_RET_DATE

async def airline_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["airline"] = q.data
    airline_label = next(l for l, d in AIRLINE_OPTS if d == q.data)

    ud = ctx.user_data
    origin = ud["origin"] if ud["origin"] != "ALL" else "DTM,DUS,CGN"
    dest   = ud["dest"]
    dep_f  = ud["dep_from"]
    dep_t  = ud["dep_to"]
    ret_f  = ud.get("ret_from")
    ret_t  = ud.get("ret_to")
    airline = ud["airline"]

    await q.edit_message_text(
        f"🔍 Aranıyor...\n"
        f"{origin} → {dest}\n"
        f"Gidiş: {dep_f} – {dep_t}\n"
        f"{('Dönüş: '+ret_f+' – '+ret_t) if ret_f else 'Tek yön'}\n"
        f"Havayolu: {airline_label}"
    )

    rate    = get_try_rate()
    flights = search_kiwi(origin, dest, dep_f, dep_t, ret_f, ret_t, airline)

    if not flights:
        await q.message.reply_text(
            "❌ Bu kriterlere uygun uçuş bulunamadı.\n"
            "Tarih aralığını genişletmeyi veya farklı havayolu seçmeyi dene.\n\n"
            "/start ile yeni arama yap."
        )
        return ConversationHandler.END

    result_text, links = format_flights(flights, rate)
    ctx.user_data["links"]   = links
    ctx.user_data["rate"]    = rate
    ctx.user_data["results"] = result_text

    n = min(len(flights), 5)
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]
    link_btns = [(emojis[i], str(i)) for i in range(n)]
    link_btns.append(("❌ İptal", "cancel"))

    await q.message.reply_text(
        f"✅ {n} sonuç bulundu!\n\n{result_text}"
        f"Hangi biletin linkini istiyorsun?",
        reply_markup=kb_row(link_btns)
    )
    return S_RESULTS

async def result_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "cancel":
        await q.edit_message_text("İptal edildi. /start ile yeni arama yapabilirsin.")
        return ConversationHandler.END

    idx = int(q.data)
    ctx.user_data["chosen_idx"] = idx
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]

    await q.edit_message_text(
        f"{emojis[idx]} numaralı bilet için link göndereyim mi?",
        reply_markup=kb([
            ("✅ Evet, gönder", "yes"),
            ("🔙 Geri dön",    "back"),
        ])
    )
    return S_CONFIRM

async def confirm_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "back":
        n = len(ctx.user_data.get("links", []))
        emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣"]
        link_btns = [(emojis[i], str(i)) for i in range(n)]
        link_btns.append(("❌ İptal", "cancel"))
        await q.edit_message_text(
            ctx.user_data.get("results","") + "Hangi biletin linkini istiyorsun?",
            reply_markup=kb_row(link_btns)
        )
        return S_RESULTS

    idx  = ctx.user_data.get("chosen_idx", 0)
    links = ctx.user_data.get("links", [])
    link  = links[idx] if idx < len(links) else None

    if link:
        await q.edit_message_text(
            f"🔗 Rezervasyon linkin:\n\n{link}\n\n"
            f"⚠️ Fiyatlar anlık değişebilir, satın almadan önce teyit et.\n\n"
            f"✈️ İyi yolculuklar! /start ile yeni arama yapabilirsin."
        )
        # 200€ altıysa mail de gönder
        if ctx.user_data.get("results","").count("🔥") > 0:
            send_mail(
                "🔥 FIRSAT — Bilet Rezervasyonu",
                f"Seçilen bilet:\n\n{ctx.user_data.get('results','')}\n\nLink: {link}"
            )
    else:
        await q.edit_message_text(
            "⚠️ Link alınamadı. Kiwi.com'dan manuel arama yapabilirsin:\n"
            "https://www.kiwi.com\n\n/start ile tekrar dene."
        )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "İptal edildi. /start ile yeni arama yapabilirsin. ✈️"
    )
    return ConversationHandler.END

async def fallback_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! 👋 /start ile uçuş araması başlatabilirsin.\n\n"
        "📋 Komutlar:\n"
        "/start — Yeni arama\n"
        "/iptal — Aramayı iptal et"
    )

# ── Uygulama ──────────────────────────────────────────────

def main():
    app = Application.builder().token(TG_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(
                filters.Regex(r"(?i)(merhaba|selam|hi|hello|hey|başla|baslat)"),
                start
            ),
        ],
        states={
            S_ORIGIN:   [CallbackQueryHandler(origin_chosen)],
            S_DEST:     [
                CallbackQueryHandler(dest_chosen),
                MessageHandler(filters.TEXT & ~filters.COMMAND, dest_custom),
            ],
            S_TRIP:     [CallbackQueryHandler(trip_chosen)],
            S_DEP_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dep_date_entered)],
            S_RET_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ret_date_entered)],
            S_AIRLINE:  [CallbackQueryHandler(airline_chosen)],
            S_RESULTS:  [CallbackQueryHandler(result_selected)],
            S_CONFIRM:  [CallbackQueryHandler(confirm_link)],
        },
        fallbacks=[
            CommandHandler("iptal", cancel),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_msg))

    log.info("Bot başlatılıyor (polling)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
