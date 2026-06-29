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

        lines += [
            f"{i}. {s['yon']}: {s['kalkis']} -> {s['varis']}{firsat}",
            f"   Havayolu: {airline}",
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
