import os
import logging
import sqlite3
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "data/fengon_parts.sqlite3")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
log = logging.getLogger("fengon_parts")

# Conversation states
ADD_NAME, ADD_CATEGORY, ADD_PRICE, ADD_DESCRIPTION, ADD_PHOTO = range(5)
ORDER_NAME, ORDER_ADDRESS, ORDER_PHONE, ORDER_CONFIRM = range(5, 9)
BROADCAST_TEXT, POST_TEXT = 9, 10

CATEGORIES = [
    "Мотор ва двигатель", "Фильтрлар", "Тормоз тизими", "Ходовой қисм",
    "Электрика ва датчиклар", "Кузов қисмлари", "Салон аксессуарлари",
    "Фара ва чироқлар", "Ойна ва кузов аксессуарлари", "Бошқа эҳтиёт қисмлар"
]

def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT NOT NULL, price TEXT NOT NULL,
            description TEXT DEFAULT '', photo_id TEXT DEFAULT '',
            active INTEGER DEFAULT 1, created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, username TEXT DEFAULT '',
            product_id INTEGER, product_name TEXT NOT NULL,
            customer_name TEXT NOT NULL, phone TEXT NOT NULL,
            address TEXT NOT NULL, status TEXT DEFAULT 'Янги',
            created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS customers (
            user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
            first_name TEXT DEFAULT '', joined_at TEXT NOT NULL
        )""")

def is_admin(uid):
    return uid in ADMIN_IDS

def main_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🛒 Каталог"), KeyboardButton("🔎 Қидириш")],
         [KeyboardButton("📦 Буюртмаларим"), KeyboardButton("☎️ Алоқа")]],
        resize_keyboard=True
    )

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Маҳсулот қўшиш", callback_data="admin:add")],
        [InlineKeyboardButton("📋 Буюртмалар", callback_data="admin:orders")],
        [InlineKeyboardButton("📢 Каналга пост", callback_data="admin:post")],
        [InlineKeyboardButton("📣 Мижозларга хабар", callback_data="admin:broadcast")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    with db() as con:
        con.execute(
            "INSERT OR REPLACE INTO customers(user_id,username,first_name,joined_at) VALUES(?,?,?,?)",
            (u.id, u.username or "", u.first_name or "", datetime.now().isoformat(timespec="seconds"))
        )
    await update.message.reply_text(
        f"Ассалому алайкум, {u.first_name or 'ҳурматли мижоз'}!\n\n"
        "FENGON PARTS дўконига хуш келибсиз. Каталог фақат Fengon S508 автомобили учун.",
        reply_markup=main_keyboard()
    )

async def catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as con:
        rows = con.execute("SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category").fetchall()
    if not rows:
        await update.message.reply_text("Каталог ҳозирча бўш. Маҳсулотлар тез орада қўшилади.")
        return
    kb = [[InlineKeyboardButton(r["category"], callback_data=f"cat:{r['category']}")] for r in rows]
    await update.message.reply_text("Fengon S508 учун эҳтиёт қисмлар бўлимини танланг:", reply_markup=InlineKeyboardMarkup(kb))

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    category = q.data[4:]
    with db() as con:
        rows = con.execute(
            "SELECT id,name,price FROM products WHERE active=1 AND category=? ORDER BY id DESC", (category,)
        ).fetchall()
    if not rows:
        await q.edit_message_text("Бу бўлимда ҳозирча маҳсулот йўқ.")
        return
    kb = [[InlineKeyboardButton(f"{r['name']} — {r['price']}", callback_data=f"product:{r['id']}")] for r in rows]
    await q.edit_message_text(f"📂 {category}\nМаҳсулотни танланг:", reply_markup=InlineKeyboardMarkup(kb))

async def product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    with db() as con:
        p = con.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    if not p:
        await q.message.reply_text("Маҳсулот топилмади ёки мавжуд эмас.")
        return
    caption = f"<b>{p['name']}</b>\n\n🚘 Модель: Fengon S508\n💰 Нарх: <b>{p['price']}</b>\n📂 Бўлим: {p['category']}"
    if p["description"]:
        caption += f"\n\n{p['description']}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛍 Буюртма бериш", callback_data=f"order:{pid}")]])
    if p["photo_id"]:
        await q.message.reply_photo(p["photo_id"], caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await q.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)

async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["searching"] = True
    await update.message.reply_text("Fengon S508 учун керакли эҳтиёт қисм номини ёзинг:")

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if context.user_data.get("searching"):
        context.user_data["searching"] = False
        with db() as con:
            rows = con.execute(
                "SELECT id,name,price FROM products WHERE active=1 AND (name LIKE ? OR description LIKE ? OR category LIKE ?) ORDER BY id DESC LIMIT 20",
                (f"%{t}%", f"%{t}%", f"%{t}%")
            ).fetchall()
        if not rows:
            await update.message.reply_text("Бу ном бўйича маҳсулот топилмади.")
            return
        kb = [[InlineKeyboardButton(f"{r['name']} — {r['price']}", callback_data=f"product:{r['id']}")] for r in rows]
        await update.message.reply_text("Қидирув натижалари:", reply_markup=InlineKeyboardMarkup(kb))
    elif t == "🛒 Каталог":
        await catalog(update, context)
    elif t == "🔎 Қидириш":
        await search_prompt(update, context)
    elif t == "📦 Буюртмаларим":
        with db() as con:
            rows = con.execute(
                "SELECT id,product_name,status,created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (update.effective_user.id,)
            ).fetchall()
        if not rows:
            await update.message.reply_text("Сизда ҳозирча буюртмалар йўқ.")
        else:
            body = "\n\n".join(
                f"#{r['id']} — {r['product_name']}\nҲолати: {r['status']}\n{r['created_at']}" for r in rows
            )
            await update.message.reply_text(body)
    elif t == "☎️ Алоқа":
        await update.message.reply_text("Администратор билан боғланиш:+998975164677 @fengon_zapchast")
    else:
        await update.message.reply_text("Менюдан керакли бўлимни танланг.", reply_markup=main_keyboard())

# ORDER FLOW: full name -> full address -> phone contact or typed phone -> confirmation
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    with db() as con:
        p = con.execute("SELECT id,name,price FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    if not p:
        await q.message.reply_text("Маҳсулот топилмади.")
        return ConversationHandler.END
    context.user_data["order"] = {
        "product_id": p["id"], "product_name": p["name"], "price": p["price"]
    }
    await q.message.reply_text("1/3. Исмингиз ва фамилиянгизни киритинг:", reply_markup=ReplyKeyboardRemove())
    return ORDER_NAME

async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name.split()) < 2:
        await update.message.reply_text("Илтимос, исм ва фамилиянгизни тўлиқ киритинг:")
        return ORDER_NAME
    context.user_data["order"]["customer_name"] = name
    await update.message.reply_text(
        "2/3. Яшаш манзилингизни тўлиқ киритинг (вилоят, туман/шаҳар, кўча ва уй рақами):"
    )
    return ORDER_ADDRESS

async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if len(address) < 8:
        await update.message.reply_text("Манзил тўлиқ эмас. Илтимос, вилоят, туман/шаҳар ва кўча/уйни киритинг:")
        return ORDER_ADDRESS
    context.user_data["order"]["address"] = address
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Телефон рақамимни юбориш", request_contact=True)],
         [KeyboardButton("Рақамни қўлда киритиш")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text("3/3. Телефон рақамингизни юборинг:", reply_markup=kb)
    return ORDER_PHONE

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        contact = update.message.contact
        if contact.user_id and contact.user_id != update.effective_user.id:
            await update.message.reply_text("Илтимос, ўз телефон рақамингизни юборинг ёки қўлда киритинг.")
            return ORDER_PHONE
        phone = contact.phone_number
    else:
        phone = (update.message.text or "").strip()
        if phone == "Рақамни қўлда киритиш":
            await update.message.reply_text("Телефон рақамингизни +998901234567 кўринишида киритинг:")
            return ORDER_PHONE
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 9:
            await update.message.reply_text("Телефон рақами нотўғри. Қайта киритинг ёки тугма орқали юборинг:")
            return ORDER_PHONE
    context.user_data["order"]["phone"] = phone
    o = context.user_data["order"]
    summary = (
        "📋 <b>Буюртмани текширинг</b>\n\n"
        f"🛒 Маҳсулот: {o['product_name']}\n"
        f"💰 Нарх: {o['price']}\n"
        f"👤 Харидор: {o['customer_name']}\n"
        f"📍 Манзил: {o['address']}\n"
        f"📞 Телефон: {o['phone']}\n\n"
        "Маълумотлар тўғри бўлса, тасдиқланг."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Буюртмани тасдиқлаш", callback_data="orderconfirm:yes")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="orderconfirm:no")]
    ])
    await update.message.reply_text(summary, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Тасдиқлаш учун тугмани босинг:", reply_markup=kb)
    return ORDER_CONFIRM

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.endswith(":no"):
        context.user_data.pop("order", None)
        await q.edit_message_text("Буюртма бекор қилинди.")
        await q.message.reply_text("Асосий меню:", reply_markup=main_keyboard())
        return ConversationHandler.END

    o = context.user_data.get("order")
    if not o:
        await q.edit_message_text("Буюртма маълумотлари топилмади. Илтимос, қайтадан буюртма беринг.")
        return ConversationHandler.END

    u = q.from_user
    with db() as con:
        cur = con.execute(
            """INSERT INTO orders(user_id,username,product_id,product_name,customer_name,phone,address,status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (u.id, u.username or "", o["product_id"], o["product_name"], o["customer_name"],
             o["phone"], o["address"], "Янги", datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        oid = cur.lastrowid
    await q.edit_message_text(f"✅ Буюртмангиз қабул қилинди!\nБуюртма рақами: #{oid}")
    await q.message.reply_text("Асосий меню:", reply_markup=main_keyboard())
    admin_text = (
        f"🆕 <b>ЯНГИ БУЮРТМА #{oid}</b>\n"
        f"🚘 Модель: Fengon S508\n🛒 Маҳсулот: {o['product_name']}\n💰 Нарх: {o['price']}\n"
        f"👤 Харидор: {o['customer_name']}\n📍 Манзил: {o['address']}\n📞 Телефон: {o['phone']}\n"
        f"Telegram ID: <code>{u.id}</code>\nUsername: @{u.username or 'йўқ'}"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, admin_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("Admin notification failed for %s: %s", aid, e)
    context.user_data.pop("order", None)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Амал бекор қилинди.", reply_markup=main_keyboard())
    return ConversationHandler.END

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Бу бўлим фақат администраторлар учун.")
        return
    await update.message.reply_text("FENGON PARTS — администратор панели", reply_markup=admin_keyboard())

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.message.reply_text("Рухсат йўқ.")
        return ConversationHandler.END
    action = q.data.split(":")[1]
    if action == "add":
        context.user_data["new_product"] = {}
        await q.message.reply_text("Маҳсулот номини киритинг:")
        return ADD_NAME
    if action == "orders":
        with db() as con:
            rows = con.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 15").fetchall()
        if not rows:
            await q.message.reply_text("Буюртмалар ҳозирча йўқ.")
        for r in rows:
            msg = (
                f"#{r['id']} | {r['product_name']}\nХаридор: {r['customer_name']}\n"
                f"Телефон: {r['phone']}\nМанзил: {r['address']}\nҲолати: {r['status']}"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Бажарилди", callback_data=f"status:{r['id']}:Бажарилди"),
                InlineKeyboardButton("⏳ Жараёнда", callback_data=f"status:{r['id']}:Жараёнда")
            ]])
            await q.message.reply_text(msg, reply_markup=kb)
        return ConversationHandler.END
    if action == "post":
        await q.message.reply_text("Каналга жойланадиган пост матнини юборинг:")
        return POST_TEXT
    if action == "broadcast":
        await q.message.reply_text("Мижозларга юбориладиган хабар матнини киритинг:")
        return BROADCAST_TEXT
    if action == "stats":
        with db() as con:
            customers = con.execute("SELECT COUNT(*) n FROM customers").fetchone()["n"]
            products = con.execute("SELECT COUNT(*) n FROM products WHERE active=1").fetchone()["n"]
            orders = con.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
            new_orders = con.execute("SELECT COUNT(*) n FROM orders WHERE status='Янги'").fetchone()["n"]
        await q.message.reply_text(
            f"📊 Статистика\nМижозлар: {customers}\nМаҳсулотлар: {products}\n"
            f"Жами буюртмалар: {orders}\nЯнги буюртмалар: {new_orders}"
        )
    return ConversationHandler.END

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["name"] = update.message.text.strip()
    kb = [[InlineKeyboardButton(c, callback_data=f"newcat:{i}")] for i, c in enumerate(CATEGORIES)]
    await update.message.reply_text("Категорияни танланг:", reply_markup=InlineKeyboardMarkup(kb))
    return ADD_CATEGORY

async def add_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END
    idx = int(q.data.split(":")[1])
    context.user_data["new_product"]["category"] = CATEGORIES[idx]
    await q.message.reply_text("Маҳсулот нархини киритинг (масалан: 250 000 сўм):")
    return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["price"] = update.message.text.strip()
    await update.message.reply_text("Маҳсулот ҳақида маълумот киритинг ёки «Йўқ» деб ёзинг:")
    return ADD_DESCRIPTION

async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    context.user_data["new_product"]["description"] = "" if val.lower() == "йўқ" else val
    await update.message.reply_text("Маҳсулот расмини юборинг ёки /skip ёзинг:")
    return ADD_PHOTO

async def save_product(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_id=""):
    p = context.user_data.get("new_product", {})
    with db() as con:
        cur = con.execute(
            "INSERT INTO products(name,category,price,description,photo_id,created_at) VALUES(?,?,?,?,?,?)",
            (p["name"], p["category"], p["price"], p.get("description", ""), photo_id,
             datetime.now().isoformat(timespec="seconds"))
        )
        pid = cur.lastrowid
    await update.message.reply_text(f"✅ Маҳсулот сақланди. ID: {pid}")
    context.user_data.pop("new_product", None)

async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await save_product(update, context, update.message.photo[-1].file_id)
    return ConversationHandler.END

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await save_product(update, context, "")
    return ConversationHandler.END

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, oid, status = q.data.split(":", 2)
    with db() as con:
        row = con.execute("SELECT user_id FROM orders WHERE id=?", (int(oid),)).fetchone()
        con.execute("UPDATE orders SET status=? WHERE id=?", (status, int(oid)))
    await q.edit_message_reply_markup(reply_markup=None)
    await q.message.reply_text(f"Буюртма #{oid} ҳолати: {status}")
    if row:
        try:
            await context.bot.send_message(row["user_id"], f"Буюртмангиз #{oid} ҳолати янгиланди: {status}")
        except Exception:
            pass

async def post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID созланмаган.")
    else:
        try:
            await context.bot.send_message(CHANNEL_ID, update.message.text)
            await update.message.reply_text("✅ Пост каналга жойланди.")
        except Exception as e:
            await update.message.reply_text(f"Пост юборилмади. Бот канал администратори эканини текширинг. Хато: {e}")
    return ConversationHandler.END

async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    with db() as con:
        ids = [r["user_id"] for r in con.execute("SELECT user_id FROM customers").fetchall()]
    sent = failed = 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, update.message.text)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"Хабар юбориш тугади. Юборилди: {sent}; юборилмади: {failed}")
    return ConversationHandler.END

def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN .env файлига киритилмаган.")
    init_db()
    app = Application.builder().token(TOKEN).build()

    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(order_start, pattern=r"^order:\d+$")],
        states={
            ORDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            ORDER_PHONE: [
                MessageHandler(filters.CONTACT, order_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)
            ],
            ORDER_CONFIRM: [CallbackQueryHandler(order_confirm, pattern=r"^orderconfirm:(yes|no)$")]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True, per_chat=True
    )
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern=r"^admin:(add|orders|post|broadcast|stats)$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_CATEGORY: [CallbackQueryHandler(add_category_callback, pattern=r"^newcat:\d+$")],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)],
            ADD_PHOTO: [MessageHandler(filters.PHOTO, add_photo), CommandHandler("skip", skip_photo)],
            POST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_text)],
            BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True, per_chat=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(order_conv)
    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(product_callback, pattern=r"^product:\d+$"))
    app.add_handler(CallbackQueryHandler(status_callback, pattern=r"^status:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    log.info("FENGON PARTS bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
