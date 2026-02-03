import logging
import sqlite3
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
from telegram import InputMediaPhoto
from threading import Thread
from flask import Flask, request, jsonify

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

    BOT_TOKEN = "" # Токен и айди удалены в целях безопасности 

ADMIN_IDS = []

PHOTOS_DIR = "user_photos"
if not os.path.exists(PHOTOS_DIR):
    os.makedirs(PHOTOS_DIR)

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот знакомств работает! 🚀"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route('/webhook', methods=['POST'])
def webhook():
    return jsonify({"status": "webhook received"})

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

def init_db():
    try:
        conn = sqlite3.connect('school_dating.db', check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                class TEXT,
                interests TEXT,
                about_me TEXT,
                gender TEXT,
                search_gender TEXT,
                registered_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                is_approved BOOLEAN DEFAULT FALSE,
                last_match_time TIMESTAMP,
                photo_path TEXT,
                favorite_subject TEXT,
                hobby TEXT,
                dream TEXT,
                reported_count INTEGER DEFAULT 0,
                last_reported TIMESTAMP
            )
        ''')

        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'is_under_review' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_under_review BOOLEAN DEFAULT FALSE")
            logger.info("Добавлена колонка is_under_review в таблицу users")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER,
                user2_id INTEGER,
                matched_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (user1_id) REFERENCES users (user_id),
                FOREIGN KEY (user2_id) REFERENCES users (user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                liked_at TIMESTAMP,
                is_notified BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (from_user_id) REFERENCES users (user_id),
                FOREIGN KEY (to_user_id) REFERENCES users (user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER,
                reported_user_id INTEGER,
                reason TEXT,
                reported_at TIMESTAMP,
                status TEXT DEFAULT 'pending',
                reviewed_by INTEGER,
                reviewed_at TIMESTAMP,
                FOREIGN KEY (reporter_id) REFERENCES users (user_id),
                FOREIGN KEY (reported_user_id) REFERENCES users (user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_user_id INTEGER,
                details TEXT,
                action_at TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users (user_id),
                FOREIGN KEY (target_user_id) REFERENCES users (user_id)
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("🛠️ Панель модерации", callback_data="moderation_panel")],
            [InlineKeyboardButton("👀 Найти собеседника", callback_data="find_match")],
            [InlineKeyboardButton("📝 Редактировать анкету", callback_data="edit_profile")],
            [InlineKeyboardButton("🖼️ Добавить/изменить фото", callback_data="add_photo")],
            [InlineKeyboardButton("💝 Мои лайки", callback_data="my_likes")],
            [InlineKeyboardButton("👥 Мои совпадения", callback_data="my_matches")],
            [InlineKeyboardButton("🚫 Удалить анкету", callback_data="delete_profile")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(
                f"Добро пожаловать, администратор {update.effective_user.first_name}! 👑\n"
                "Вы можете использовать панель модерации для управления анкетами.",
                reply_markup=reply_markup
            )
        else:
            await update.callback_query.edit_message_text(
                f"Добро пожаловать, администратор {update.effective_user.first_name}! 👑\n"
                "Вы можете использовать панель модерации для управления анкетами.",
                reply_markup=reply_markup
            )
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'is_under_review' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_under_review BOOLEAN DEFAULT FALSE")
        conn.commit()

    cursor.execute("SELECT is_approved, is_under_review, is_active FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        is_approved = user[0]
        is_under_review = user[1]
        is_active = user[2]

        if not is_active:
            if update.message:
                await update.message.reply_text(
                    "🚫 Ваша анкета заблокирована.\n"
                    "Для разблокировки обратитесь к администраторам."
                )
            else:
                await update.callback_query.edit_message_text(
                    "🚫 Ваша анкета заблокирована.\n"
                    "Для разблокировки обратитесь к администраторам."
                )
            return

        if not is_approved:
            if is_under_review:
                if update.message:
                    await update.message.reply_text(
                        "⏳ Твоя анкета находится на модерации.\n"
                        "Мы проверим ее в ближайшее время и уведомим тебя!"
                    )
                else:
                    await update.callback_query.edit_message_text(
                        "⏳ Твоя анкета находится на модерации.\n"
                        "Мы проверим ее в ближайшее время и уведомим тебя!"
                    )
                return
            else:
                if update.message:
                    await update.message.reply_text(
                        "⚠️ Твоя анкета еще не проверена модераторами.\n"
                        "Пожалуйста, подожди немного, мы скоро ее проверим!"
                    )
                else:
                    await update.callback_query.edit_message_text(
                        "⚠️ Твоя анкета еще не проверена модераторами.\n"
                        "Пожалуйста, подожди немного, мы скоро ее проверим!"
                    )
                return

        keyboard = [
            [InlineKeyboardButton("👀 Найти собеседника", callback_data="find_match")],
            [InlineKeyboardButton("📝 Редактировать анкету", callback_data="edit_profile")],
            [InlineKeyboardButton("🖼️ Добавить/изменить фото", callback_data="add_photo")],
            [InlineKeyboardButton("💝 Мои лайки", callback_data="my_likes")],
            [InlineKeyboardButton("👥 Мои совпадения", callback_data="my_matches")],
            [InlineKeyboardButton("🚫 Удалить анкету", callback_data="delete_profile")],
            [InlineKeyboardButton("🚨 Пожаловаться", callback_data="report_user_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(
                f"С возвращением, {update.effective_user.first_name}! 😊\n"
                "Что хочешь сделать?",
                reply_markup=reply_markup
            )
        else:
            await update.callback_query.edit_message_text(
                f"С возвращением, {update.effective_user.first_name}! 😊\n"
                "Что хочешь сделать?",
                reply_markup=reply_markup
            )
    else:
        keyboard = [[InlineKeyboardButton("📝 Создать анкету", callback_data="create_profile")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(
                "Привет! 👋\n"
                "Это чат-бот знакомств для нашей школы.\n\n"
                "⚠️ Правила использования:\n"
                "• Уважай других участников\n"
                "• Не размещай личную информацию\n"
                "• Запрещены оскорбления и неприемлемый контент\n"
                "• Сообщи администраторам о нарушениях\n\n"
                "Все анкеты проходят модерацию перед публикацией!\n\n"
                "Для начала создай свою анкету!",
                reply_markup=reply_markup
            )
        else:
            await update.callback_query.edit_message_text(
                "Привет! 👋\n"
                "Это чат-бот знакомств для нашей школы.\n\n"
                "⚠️ Правила использования:\n"
                "• Уважай других участников\n"
                "• Не размещай личную информацию\n"
                "• Запрещены оскорбления и неприемлемый контент\n"
                "• Сообщи администраторам о нарушениях\n\n"
                "Все анкеты проходят модерацию перед публикацией!\n\n"
                "Для начала создай свою анкету!",
                reply_markup=reply_markup
            )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def create_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['profile_creation'] = True
    context.user_data['profile_step'] = 'first_name'

    await query.edit_message_text(
        "📝 Давай создадим твою анкету!\n\n"
        "Введи свое имя:"
    )

async def handle_profile_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('profile_creation'):
        text = update.message.text
        step = context.user_data.get('profile_step')

        if step == 'first_name':
            context.user_data['first_name'] = text
            context.user_data['profile_step'] = 'last_name'
            await update.message.reply_text("Отлично! Теперь введи свою фамилию:")

        elif step == 'last_name':
            context.user_data['last_name'] = text
            context.user_data['profile_step'] = 'class'
            await update.message.reply_text("Введи свой класс (например: 10А, 11Б, 9В):")

        elif step == 'class':
            context.user_data['class'] = text
            context.user_data['profile_step'] = 'gender'
            keyboard = [
                [
                    InlineKeyboardButton("👦 Мужской", callback_data="gender_male"),
                    InlineKeyboardButton("👩 Женский", callback_data="gender_female")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Отлично! Теперь выбери свой пол:", reply_markup=reply_markup)

        elif step == 'interests':
            context.user_data['interests'] = text
            context.user_data['profile_step'] = 'favorite_subject'
            await update.message.reply_text("📚 Отлично! Теперь напиши свой любимый школьный предмет:")

        elif step == 'favorite_subject':
            context.user_data['favorite_subject'] = text
            context.user_data['profile_step'] = 'hobby'
            await update.message.reply_text("🎨 Расскажи о своем хобби (чем любишь заниматься в свободное время):")

        elif step == 'hobby':
            context.user_data['hobby'] = text
            context.user_data['profile_step'] = 'dream'
            await update.message.reply_text("💫 Какая у тебя мечта? Кем хочешь стать в будущем?")

        elif step == 'dream':
            context.user_data['dream'] = text
            context.user_data['profile_step'] = 'about_me'
            await update.message.reply_text(
                "🎯 Теперь расскажи немного о себе:\n"
                "(Твой характер, что тебе важно в людях, какие качества ценишь и т.д.)"
            )

        elif step == 'about_me':
            context.user_data['about_me'] = text
            await save_profile_to_db(update, context)

    elif context.user_data.get('editing_profile'):
        await handle_edit_profile_text(update, context)
    elif context.user_data.get('awaiting_report_reason'):
        await handle_user_report(update, context)
    elif context.user_data.get('awaiting_reject_reason') or context.user_data.get('awaiting_ban_reason'):
        await handle_moderation_reason(update, context)
    else:
        await update.message.reply_text("Используй команду /start для начала работы.")

async def save_profile_to_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = context.user_data

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'is_under_review' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_under_review BOOLEAN DEFAULT FALSE")
            logger.info("Добавлена колонка is_under_review в таблицу users")

        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, class, interests, about_me, gender, search_gender, 
             favorite_subject, hobby, dream, registered_at, is_under_review, is_approved, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            update.effective_user.username,
            user_data.get('first_name'),
            user_data.get('last_name'),
            user_data.get('class'),
            user_data.get('interests'),
            user_data.get('about_me'),
            user_data.get('gender'),
            user_data.get('search_gender', 'все'),
            user_data.get('favorite_subject'),
            user_data.get('hobby'),
            user_data.get('dream'),
            datetime.now(),
            1,
            0,
            1
        ))

        conn.commit()

        context.user_data.pop('profile_creation', None)
        context.user_data.pop('profile_step', None)

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📋 Новая анкета на модерации!\n\n"
                         f"Пользователь: {user_data.get('first_name')} {user_data.get('last_name') or ''}\n"
                         f"Класс: {user_data.get('class')}\n"
                         f"ID: {user_id}\n\n"
                         f"Используйте панель модерации для проверки."
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")

        keyboard = [
            [InlineKeyboardButton("📝 Посмотреть мою анкету", callback_data="view_my_profile")],
            [InlineKeyboardButton("🖼️ Добавить фото", callback_data="add_photo")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🎉 Твоя анкета создана!\n\n"
            "⏳ Она отправлена на модерацию. Мы проверим ее в ближайшее время и уведомим тебя!\n"
            "Обычно это занимает не более 24 часов.",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении анкеты: {e}")
        await update.message.reply_text("😔 Произошла ошибка при создании анкеты. Попробуй еще раз.")

    finally:
        conn.close()

async def handle_gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'gender_male':
        context.user_data['gender'] = 'мужской'
    else:
        context.user_data['gender'] = 'женский'

    context.user_data['profile_step'] = 'search_gender'

    keyboard = [
        [
            InlineKeyboardButton("👦 Парни", callback_data="search_male"),
            InlineKeyboardButton("👩 Девушки", callback_data="search_female")
        ],
        [InlineKeyboardButton("👥 Все", callback_data="search_all")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Теперь выбери, с кем ты хочешь знакомиться:",
        reply_markup=reply_markup
    )

async def handle_search_gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'search_male':
        context.user_data['search_gender'] = 'парни'
    elif query.data == 'search_female':
        context.user_data['search_gender'] = 'девушки'
    else:
        context.user_data['search_gender'] = 'все'

    context.user_data['profile_step'] = 'interests'

    await query.edit_message_text(
        "🎯 Отлично! Теперь напиши свои интересы:\n"
        "(Например: музыка, спорт, программирование, книги, игры и т.д.)"
    )

async def view_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        keyboard = [[InlineKeyboardButton("📝 Создать анкету", callback_data="create_profile")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("У тебя еще нет анкеты! Создай ее:", reply_markup=reply_markup)
        return

    profile_text = (
        f"👤 Твоя анкета:\n\n"
        f"📱 Имя: {user[2]} {user[3] or ''}\n"
        f"🏫 Класс: {user[4]}\n"
        f"⚧ Пол: {user[7]}\n"
        f"🔍 Ищу: {user[8]}\n"
        f"🎯 Интересы: {user[5]}\n"
        f"📚 Любимый предмет: {user[15] or 'Не указано'}\n"
        f"🎨 Хобби: {user[16] or 'Не указано'}\n"
        f"💫 Мечта: {user[17] or 'Не указано'}\n"
        f"📝 О себе: {user[6]}\n"
    )

    has_photo = user[14] and os.path.exists(user[14])

    keyboard = [
        [InlineKeyboardButton("✏️ Редактировать анкету", callback_data="edit_profile")],
        [InlineKeyboardButton("🖼️ Добавить/изменить фото", callback_data="add_photo")],
        [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if has_photo:
        with open(user[14], 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=profile_text,
                reply_markup=reply_markup
            )
        try:
            await query.delete_message()
        except BadRequest:
            pass
    else:
        try:
            await query.edit_message_text(profile_text, reply_markup=reply_markup)
        except BadRequest:
            await query.message.reply_text(profile_text, reply_markup=reply_markup)

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👤 Изменить имя", callback_data="edit_first_name")],
        [InlineKeyboardButton("👤 Изменить фамилию", callback_data="edit_last_name")],
        [InlineKeyboardButton("🏫 Изменить класс", callback_data="edit_class")],
        [InlineKeyboardButton("🎯 Изменить интересы", callback_data="edit_interests")],
        [InlineKeyboardButton("📚 Изменить любимый предмет", callback_data="edit_favorite_subject")],
        [InlineKeyboardButton("🎨 Изменить хобби", callback_data="edit_hobby")],
        [InlineKeyboardButton("💫 Изменить мечту", callback_data="edit_dream")],
        [InlineKeyboardButton("📝 Изменить 'О себе'", callback_data="edit_about")],
        [InlineKeyboardButton("⚧ Изменить пол", callback_data="edit_gender")],
        [InlineKeyboardButton("🔍 Изменить поиск", callback_data="edit_search")],
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            "Что ты хочешь изменить в анкете?",
            reply_markup=reply_markup
        )
    except BadRequest:
        await query.message.reply_text(
            "Что ты хочешь изменить в анкете?",
            reply_markup=reply_markup
        )

async def handle_edit_profile_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    edit_field = context.user_data.get('editing_field')

    if not edit_field:
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        if edit_field == 'first_name':
            cursor.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Имя успешно обновлено!"
        elif edit_field == 'last_name':
            cursor.execute("UPDATE users SET last_name = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Фамилия успешно обновлена!"
        elif edit_field == 'class':
            cursor.execute("UPDATE users SET class = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Класс успешно обновлен!"
        elif edit_field == 'interests':
            cursor.execute("UPDATE users SET interests = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Интересы успешно обновлены!"
        elif edit_field == 'favorite_subject':
            cursor.execute("UPDATE users SET favorite_subject = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Любимый предмет успешно обновлен!"
        elif edit_field == 'hobby':
            cursor.execute("UPDATE users SET hobby = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Хобби успешно обновлено!"
        elif edit_field == 'dream':
            cursor.execute("UPDATE users SET dream = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Мечта успешно обновлена!"
        elif edit_field == 'about_me':
            cursor.execute("UPDATE users SET about_me = ? WHERE user_id = ?", (text, user_id))
            message = "✅ Раздел 'О себе' успешно обновлен!"

        conn.commit()

        context.user_data.pop('editing_profile', None)
        context.user_data.pop('editing_field', None)

        keyboard = [
            [InlineKeyboardButton("📝 Посмотреть анкету", callback_data="view_my_profile")],
            [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data="edit_profile")],
            [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при обновлении анкеты: {e}")
        await update.message.reply_text("😔 Произошла ошибка при обновлении анкеты.")

    finally:
        conn.close()

async def edit_first_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'first_name'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Введи новое имя:", reply_markup=reply_markup)

async def edit_last_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'last_name'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Введи новую фамилию:", reply_markup=reply_markup)

async def edit_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'class'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Введи новый класс (например: 10А, 11Б, 9В):", reply_markup=reply_markup)

async def edit_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'interests'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Введи новые интересы:\n"
        "(Например: музыка, спорт, программирование, книги, игры и т.д.)",
        reply_markup=reply_markup
    )

async def edit_favorite_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'favorite_subject'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Введи новый любимый школьный предмет:", reply_markup=reply_markup)

async def edit_hobby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'hobby'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Расскажи о своем хобби заново:", reply_markup=reply_markup)

async def edit_dream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'dream'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Расскажи о своей мечте заново:", reply_markup=reply_markup)

async def edit_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['editing_profile'] = True
    context.user_data['editing_field'] = 'about_me'

    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Расскажи о себе заново:\n"
        "(Твой характер, что тебе важно в людях, какие качества ценишь и т.д.)",
        reply_markup=reply_markup
    )

async def edit_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("👦 Мужской", callback_data="update_gender_male"),
            InlineKeyboardButton("👩 Женский", callback_data="update_gender_female")
        ],
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Выбери новый пол:", reply_markup=reply_markup)

async def edit_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("👦 Парни", callback_data="update_search_male"),
            InlineKeyboardButton("👩 Девушки", callback_data="update_search_female")
        ],
        [InlineKeyboardButton("👥 Все", callback_data="update_search_all")],
        [InlineKeyboardButton("📋 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Выбери, с кем ты хочешь знакомиться:", reply_markup=reply_markup)

async def update_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    gender = 'мужской' if query.data == 'update_gender_male' else 'женский'

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE users SET gender = ? WHERE user_id = ?", (gender, user_id))
        conn.commit()

        keyboard = [
            [InlineKeyboardButton("📝 Посмотреть анкету", callback_data="view_my_profile")],
            [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data="edit_profile")],
            [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text("✅ Пол успешно обновлен!", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при обновлении пола: {e}")
        await query.edit_message_text("😔 Произошла ошибка при обновлении пола.")

    finally:
        conn.close()

async def update_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if query.data == 'update_search_male':
        search_gender = 'парни'
    elif query.data == 'update_search_female':
        search_gender = 'девушки'
    else:
        search_gender = 'все'

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE users SET search_gender = ? WHERE user_id = ?", (search_gender, user_id))
        conn.commit()

        keyboard = [
            [InlineKeyboardButton("📝 Посмотреть анкету", callback_data="view_my_profile")],
            [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data="edit_profile")],
            [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"✅ Настройки поиска обновлены! Теперь ты ищешь: {search_gender}",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Ошибка при обновлении поиска: {e}")
        await query.edit_message_text("😔 Произошла ошибка при обновлении настроек поиска.")

    finally:
        conn.close()

async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📝 Посмотреть анкету", callback_data="view_my_profile")],
        [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            "📸 Отправь мне свое фото для анкеты!\n\n"
            "⚠️ Фото должно быть четким и показывать твое лицо.\n"
            "Рекомендуемый размер: квадратное фото.",
            reply_markup=reply_markup
        )
    except BadRequest:
        await query.message.reply_text(
            "📸 Отправь мне свое фото для анкеты!\n\n"
            "⚠️ Фото должно быть четким и показывать твое лицо.\n"
            "Рекомендуемый размер: квадратное фото.",
            reply_markup=reply_markup
        )

    context.user_data['awaiting_photo'] = True

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_photo'):
        user_id = update.effective_user.id

        try:
            photo_file = await update.message.photo[-1].get_file()
            photo_path = os.path.join(PHOTOS_DIR, f"{user_id}.jpg")
            await photo_file.download_to_drive(photo_path)

            conn = sqlite3.connect('school_dating.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET photo_path = ? WHERE user_id = ?", (photo_path, user_id))
            conn.commit()
            conn.close()

            context.user_data.pop('awaiting_photo', None)

            keyboard = [
                [InlineKeyboardButton("📝 Посмотреть анкету", callback_data="view_my_profile")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text("✅ Фото успешно добавлено в анкету!", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Ошибка при сохранении фото: {e}")
            await update.message.reply_text("😔 Произошла ошибка при сохранении фото.")
    else:
        await update.message.reply_text("Для добавления фото используй кнопку 'Добавить/изменить фото' в меню.")

async def delete_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data="confirm_delete"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data="main_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            "⚠️ Ты уверен, что хочешь удалить свою анкету?\n\n"
            "Это действие:\n"
            "• Удалит твою анкету из поиска\n"
            "• Удалит все твои лайки и совпадения\n"
            "• Удалит твое фото (если есть)\n\n"
            "Восстановить анкету будет невозможно!",
            reply_markup=reply_markup
        )
    except BadRequest:
        await query.message.reply_text(
            "⚠️ Ты уверен, что хочешь удалить свою анкету?\n\n"
            "Это действие:\n"
            "• Удалит твою анкету из поиска\n"
            "• Удалит все твои лайки и совпадения\n"
            "• Удалит твое фото (если есть)\n\n"
            "Восстановить анкету будет невозможно!",
            reply_markup=reply_markup
        )

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT photo_path FROM users WHERE user_id = ?", (user_id,))
        user_photo = cursor.fetchone()

        if user_photo and user_photo[0] and os.path.exists(user_photo[0]):
            try:
                os.remove(user_photo[0])
            except Exception as e:
                logger.error(f"Ошибка при удалении фото: {e}")

        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM likes WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id))
        cursor.execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))

        conn.commit()
        context.user_data.clear()

        keyboard = [
            [InlineKeyboardButton("📝 Создать новую анкету", callback_data="create_profile")],
            [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🗑️ Твоя анкета и все связанные данные были удалены.\n\n"
            "Если захочешь вернуться - создай новую анкету!",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Ошибка при удалении анкеты: {e}")
        await query.edit_message_text("😔 Произошла ошибка при удалении анкеты.")

    finally:
        conn.close()

async def my_likes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, u.last_name, u.class, l.liked_at
        FROM likes l
        JOIN users u ON l.from_user_id = u.user_id
        WHERE l.to_user_id = ?
        ORDER BY l.liked_at DESC
    ''', (user_id,))
    likes_received = cursor.fetchall()

    cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, u.last_name, u.class, l.liked_at
        FROM likes l
        JOIN users u ON l.to_user_id = u.user_id
        WHERE l.from_user_id = ?
        ORDER BY l.liked_at DESC
    ''', (user_id,))
    likes_given = cursor.fetchall()
    conn.close()

    likes_text = "💝 Твои лайки:\n\n"
    if likes_received:
        likes_text += "❤️ Лайки, которые тебе поставили:\n"
        for like in likes_received:
            likes_text += f"👤 {like[2]} {like[3] or ''} (@{like[1] or 'без username'})\n🏫 {like[4]}\n\n"
    else:
        likes_text += "❤️ Тебе еще никто не поставил лайк\n\n"

    if likes_given:
        likes_text += "💖 Лайки, которые ты поставил:\n"
        for like in likes_given:
            likes_text += f"👤 {like[2]} {like[3] or ''} (@{like[1] or 'без username'})\n🏫 {like[4]}\n\n"
    else:
        likes_text += "💖 Ты еще никому не поставил лайк\n\n"

    keyboard = []
    if likes_received:
        for like in likes_received:
            keyboard.append([
                InlineKeyboardButton(
                    f"👀 Посмотреть анкету {like[2]}",
                    callback_data=f"view_anonymous_{like[0]}"
                )
            ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(likes_text, reply_markup=reply_markup)
    except BadRequest:
        await query.message.reply_text(likes_text, reply_markup=reply_markup)

async def find_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    context.user_data.pop('current_match_id', None)

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, is_approved FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        keyboard = [[InlineKeyboardButton("📝 Создать анкету", callback_data="create_profile")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Сначала создай анкету!", reply_markup=reply_markup)
        conn.close()
        return

    is_approved = user[1]
    if not is_approved:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Твоя анкета еще не одобрена модераторами.\n"
            "Пожалуйста, подожди, пока мы ее проверим! ⏳",
            reply_markup=reply_markup
        )
        conn.close()
        return

    cursor.execute("SELECT search_gender, gender FROM users WHERE user_id = ?", (user_id,))
    user_settings = cursor.fetchone()

    if not user_settings:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Ошибка при получении настроек поиска.", reply_markup=reply_markup)
        conn.close()
        return

    search_gender = user_settings[0] or 'все'
    user_gender = user_settings[1]

    if search_gender == "парни":
        gender_condition = "u.gender = 'мужской'"
    elif search_gender == "девушки":
        gender_condition = "u.gender = 'женский'"
    else:
        gender_condition = "1=1"

    cursor.execute('SELECT to_user_id FROM likes WHERE from_user_id = ?', (user_id,))
    liked_users = [row[0] for row in cursor.fetchall()]

    params = [user_id]

    sql_query = f'''
        SELECT u.user_id, u.username, u.first_name, u.last_name, u.class, 
               u.interests, u.about_me, u.gender, u.photo_path,
               u.favorite_subject, u.hobby, u.dream
        FROM users u
        WHERE u.user_id != ? 
        AND u.is_active = 1
        AND u.is_approved = 1
        AND ({gender_condition})
    '''

    if liked_users:
        placeholders = ','.join(['?' for _ in liked_users])
        sql_query += f" AND u.user_id NOT IN ({placeholders})"
        params.extend(liked_users)

    sql_query += " ORDER BY RANDOM() LIMIT 1"

    try:
        cursor.execute(sql_query, params)
    except Exception as e:
        logger.error(f"Ошибка SQL запроса: {e}")
        logger.error(f"SQL: {sql_query}")
        logger.error(f"Параметры: {params}")
        conn.close()
        await query.edit_message_text("Произошла ошибка при поиске. Попробуйте позже.")
        return

    match_user = cursor.fetchone()
    conn.close()

    if not match_user:
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="find_match")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "😔 Пока нет подходящих анкет для тебя.\n"
            "Попробуй позже или измени критерии поиска в настройках анкеты.",
            reply_markup=reply_markup
        )
        return

    context.user_data['current_match_id'] = match_user[0]

    profile_text = (
        f"👤 {match_user[2]} {match_user[3] or ''}\n"
        f"🏫 Класс: {match_user[4]}\n"
        f"⚧ Пол: {match_user[7]}\n"
        f"🎯 Интересы: {match_user[5]}\n"
        f"📚 Любимый предмет: {match_user[9] or 'Не указано'}\n"
        f"🎨 Хобби: {match_user[10] or 'Не указано'}\n"
        f"💫 Мечта: {match_user[11] or 'Не указано'}\n"
        f"📝 О себе: {match_user[6]}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("💖 Лайк", callback_data="like_user"),
            InlineKeyboardButton("➡️ Дальше", callback_data="next_match")
        ],
        [
            InlineKeyboardButton("🚨 Пожаловаться", callback_data="report_current_match"),
            InlineKeyboardButton("🔙 Назад", callback_data="main_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    has_photo = match_user[8] and os.path.exists(match_user[8])

    try:
        if has_photo:
            with open(match_user[8], 'rb') as photo:
                try:
                    await query.edit_message_media(
                        media=InputMediaPhoto(media=photo, caption=f"Вот анкета для знакомства:\n\n{profile_text}"),
                        reply_markup=reply_markup
                    )
                except BadRequest:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=f"Вот анкета для знакомства:\n\n{profile_text}",
                        reply_markup=reply_markup
                    )
        else:
            await query.edit_message_text(
                f"Вот анкета для знакомства:\n\n{profile_text}",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Ошибка при отправке анкеты: {e}")
        if has_photo:
            with open(match_user[8], 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=f"Вот анкета для знакомства:\n\n{profile_text}",
                    reply_markup=reply_markup
                )
        else:
            await query.message.reply_text(
                f"Вот анкета для знакомства:\n\n{profile_text}",
                reply_markup=reply_markup
            )

async def next_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.edit_message_text("🔍 Ищем следующего собеседника...")
    except BadRequest:
        await query.message.reply_text("🔍 Ищем следующего собеседника...")

    await find_match(update, context)

async def like_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    liked_user_id = context.user_data.get('current_match_id')

    if not liked_user_id:
        try:
            await query.edit_message_text("Ошибка! Попробуй найти собеседника снова.")
        except BadRequest:
            await query.message.reply_text("Ошибка! Попробуй найти собеседника снова.")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT id FROM likes 
            WHERE from_user_id = ? AND to_user_id = ?
        ''', (user_id, liked_user_id))
        existing_like = cursor.fetchone()

        if existing_like:
            keyboard = [
                [InlineKeyboardButton("➡️ Смотреть дальше", callback_data="next_match")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.edit_message_text(
                    "❌ Ты уже лайкал эту анкету ранее!",
                    reply_markup=reply_markup
                )
            except BadRequest:
                await query.message.reply_text(
                    "❌ Ты уже лайкал эту анкету ранее!",
                    reply_markup=reply_markup
                )
            conn.close()
            return

        cursor.execute('''
            INSERT INTO likes (from_user_id, to_user_id, liked_at)
            VALUES (?, ?, ?)
        ''', (user_id, liked_user_id, datetime.now()))

        cursor.execute("SELECT first_name, last_name FROM users WHERE user_id = ?", (user_id,))
        liker_user = cursor.fetchone()

        if liker_user:
            notification_text = (
                f"💖 Твоя анкета кому-то понравилась!\n\n"
                f"Кто-то поставил лайк твоей анкете. "
                f"Если поставишь взаимный лайк - узнаешь кто это! 😊"
            )

            keyboard = [
                [InlineKeyboardButton("👀 Посмотреть анкету", callback_data=f"view_anonymous_{user_id}")],
                [InlineKeyboardButton("💝 Мои лайки", callback_data="my_likes")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await context.bot.send_message(
                    chat_id=liked_user_id,
                    text=notification_text,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {liked_user_id}: {e}")

        cursor.execute('''
            SELECT id FROM likes 
            WHERE from_user_id = ? AND to_user_id = ?
        ''', (liked_user_id, user_id))
        mutual_like = cursor.fetchone()

        if mutual_like:
            cursor.execute('''
                INSERT INTO matches (user1_id, user2_id, matched_at)
                VALUES (?, ?, ?)
            ''', (min(user_id, liked_user_id), max(user_id, liked_user_id), datetime.now()))

            cursor.execute("SELECT username, first_name, last_name FROM users WHERE user_id = ?", (liked_user_id,))
            matched_user = cursor.fetchone()

            conn.commit()

            keyboard = [
                [InlineKeyboardButton("👀 Посмотреть анкету", callback_data=f"view_match_{liked_user_id}")],
                [InlineKeyboardButton("💝 Мои совпадения", callback_data="my_matches")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(
                    f"🎉 У вас взаимная симпатия с {matched_user[1]} {matched_user[2] or ''} (@{matched_user[0] or 'без username'})!\n\n"
                    "Теперь вы можете написать друг другу!",
                    reply_markup=reply_markup
                )
            except BadRequest:
                await query.message.reply_text(
                    f"🎉 У вас взаимная симпатия с {matched_user[1]} {matched_user[2] or ''} (@{matched_user[0] or 'без username'})!\n\n"
                    "Теперь вы можете написать друг другу!",
                    reply_markup=reply_markup
                )

            cursor.execute("SELECT first_name, last_name, username FROM users WHERE user_id = ?", (user_id,))
            current_user = cursor.fetchone()

            mutual_notification = (
                f"🎉 У вас взаимная симпатия с {current_user[0]} {current_user[1] or ''} "
                f"(@{current_user[2] or 'без username'})!\n\n"
                "Теперь вы можете написать друг другу!"
            )

            mutual_keyboard = [
                [InlineKeyboardButton("👀 Посмотреть анкету", callback_data=f"view_match_{user_id}")],
                [InlineKeyboardButton("💝 Мои совпадения", callback_data="my_matches")]
            ]
            mutual_reply_markup = InlineKeyboardMarkup(mutual_keyboard)

            try:
                await context.bot.send_message(
                    chat_id=liked_user_id,
                    text=mutual_notification,
                    reply_markup=mutual_reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о взаимном лайке: {e}")

        else:
            conn.commit()

            keyboard = [
                [InlineKeyboardButton("➡️ Смотреть дальше", callback_data="next_match")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(
                    "💖 Твой лайк отправлен!\n"
                    "Если этот пользователь тоже лайкнет тебя - вы получите уведомление о совпадении!",
                    reply_markup=reply_markup
                )
            except BadRequest:
                await query.message.reply_text(
                    "💖 Твой лайк отправлен!\n"
                    "Если этот пользователь тоже лайкнет тебя - вы получите уведомление о совпадении!",
                    reply_markup=reply_markup
                )

    except Exception as e:
        logger.error(f"Ошибка при сохранении лайка: {e}")
        try:
            await query.edit_message_text("😔 Произошла ошибка при отправке лайка.")
        except BadRequest:
            await query.message.reply_text("😔 Произошла ошибка при отправке лайка.")

    finally:
        conn.close()

async def view_anonymous_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        anonymous_user_id = int(query.data.replace('view_anonymous_', ''))
    except ValueError:
        await query.answer("Ошибка: неверный ID пользователя")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT first_name, last_name, class, interests, about_me, gender, photo_path, favorite_subject, hobby, dream FROM users WHERE user_id = ?",
        (anonymous_user_id,)
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        await query.answer("Анкета не найдена!")
        return

    profile_text = (
        f"👤 Анонимная анкета:\n\n"
        f"🏫 Класс: {user[2]}\n"
        f"⚧ Пол: {user[5]}\n"
        f"🎯 Интересы: {user[3]}\n"
        f"📚 Любимый предмет: {user[7] or 'Не указано'}\n"
        f"🎨 Хобби: {user[8] or 'Не указано'}\n"
        f"💫 Мечта: {user[9] or 'Не указано'}\n"
        f"📝 О себе: {user[4]}\n\n"
        f"💖 Поставь лайк этой анкете, и если это взаимно - узнаешь кто это!"
    )

    keyboard = [
        [InlineKeyboardButton("💖 Лайкнуть эту анкету", callback_data=f"like_anonymous_{anonymous_user_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="my_likes")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    has_photo = user[6] and os.path.exists(user[6])

    try:
        if has_photo:
            with open(user[6], 'rb') as photo:
                try:
                    await query.edit_message_media(
                        media=InputMediaPhoto(media=photo, caption=profile_text),
                        reply_markup=reply_markup
                    )
                except BadRequest:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=profile_text,
                        reply_markup=reply_markup
                    )
        else:
            await query.edit_message_text(profile_text, reply_markup=reply_markup)
    except BadRequest:
        if has_photo:
            with open(user[6], 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=profile_text,
                    reply_markup=reply_markup
                )
        else:
            await query.message.reply_text(profile_text, reply_markup=reply_markup)

async def like_anonymous_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        anonymous_user_id = int(query.data.replace('like_anonymous_', ''))
    except ValueError:
        await query.answer("Ошибка: неверный ID пользователя")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT id FROM likes 
            WHERE from_user_id = ? AND to_user_id = ?
        ''', (user_id, anonymous_user_id))
        existing_like = cursor.fetchone()

        if existing_like:
            keyboard = [
                [InlineKeyboardButton("💝 Мои лайки", callback_data="my_likes")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.edit_message_text(
                    "❌ Ты уже лайкал эту анкету ранее!",
                    reply_markup=reply_markup
                )
            except BadRequest:
                await query.message.reply_text(
                    "❌ Ты уже лайкал эту анкету ранее!",
                    reply_markup=reply_markup
                )
            return

        cursor.execute('''
            INSERT INTO likes (from_user_id, to_user_id, liked_at)
            VALUES (?, ?, ?)
        ''', (user_id, anonymous_user_id, datetime.now()))

        cursor.execute('''
            SELECT id FROM likes 
            WHERE from_user_id = ? AND to_user_id = ?
        ''', (anonymous_user_id, user_id))
        mutual_like = cursor.fetchone()

        if mutual_like:
            cursor.execute('''
                INSERT INTO matches (user1_id, user2_id, matched_at)
                VALUES (?, ?, ?)
            ''', (min(user_id, anonymous_user_id), max(user_id, anonymous_user_id), datetime.now()))

            cursor.execute("SELECT username, first_name, last_name FROM users WHERE user_id = ?", (anonymous_user_id,))
            matched_user = cursor.fetchone()

            conn.commit()

            keyboard = [
                [InlineKeyboardButton("👀 Посмотреть анкету", callback_data=f"view_match_{anonymous_user_id}")],
                [InlineKeyboardButton("💝 Мои совпадения", callback_data="my_matches")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(
                    f"🎉 У вас взаимная симпатия с {matched_user[1]} {matched_user[2] or ''} (@{matched_user[0] or 'без username'})!\n\n"
                    "Теперь вы можете написать друг другу!",
                    reply_markup=reply_markup
                )
            except BadRequest:
                await query.message.reply_text(
                    f"🎉 У вас взаимная симпатия с {matched_user[1]} {matched_user[2] or ''} (@{matched_user[0] or 'без username'})!\n\n"
                    "Теперь вы можете написать друг другу!",
                    reply_markup=reply_markup
                )

            cursor.execute("SELECT first_name, last_name, username FROM users WHERE user_id = ?", (user_id,))
            current_user = cursor.fetchone()

            mutual_notification = (
                f"🎉 У вас взаимная симпатия с {current_user[0]} {current_user[1] or ''} "
                f"(@{current_user[2] or 'без username'})!\n\n"
                "Теперь вы можете написать друг другу!"
            )

            mutual_keyboard = [
                [InlineKeyboardButton("👀 Посмотреть анкету", callback_data=f"view_match_{user_id}")],
                [InlineKeyboardButton("💝 Мои совпадения", callback_data="my_matches")]
            ]
            mutual_reply_markup = InlineKeyboardMarkup(mutual_keyboard)

            try:
                await context.bot.send_message(
                    chat_id=anonymous_user_id,
                    text=mutual_notification,
                    reply_markup=mutual_reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о взаимном лайке: {e}")

        else:
            conn.commit()

            keyboard = [
                [InlineKeyboardButton("💝 Мои лайки", callback_data="my_likes")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            try:
                await query.edit_message_text(
                    "💖 Твой лайк отправлен!\n"
                    "Если этот пользователь тоже лайкнет тебя - вы получите уведомление о совпадении!",
                    reply_markup=reply_markup
                )
            except BadRequest:
                await query.message.reply_text(
                    "💖 Твой лайк отправлен!\n"
                    "Если этот пользователь тоже лайкнет тебя - вы получите уведомление о совпадении!",
                    reply_markup=reply_markup
                )

    except Exception as e:
        logger.error(f"Ошибка при сохранении лайка: {e}")
        try:
            await query.edit_message_text("😔 Произошла ошибка при отправке лайка.")
        except BadRequest:
            await query.message.reply_text("😔 Произошла ошибка при отправке лайка.")
    finally:
        conn.close()

async def my_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, u.last_name, u.class, m.matched_at
        FROM matches m
        JOIN users u ON (u.user_id = m.user1_id OR u.user_id = m.user2_id) AND u.user_id != ?
        WHERE (m.user1_id = ? OR m.user2_id = ?) AND m.status = 'active'
        ORDER BY m.matched_at DESC
    ''', (user_id, user_id, user_id))

    matches = cursor.fetchall()
    conn.close()

    if not matches:
        keyboard = [
            [InlineKeyboardButton("👀 Найти собеседника", callback_data="find_match")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "😔 У тебя пока нет совпадений.\n"
            "Продолжай ставить лайки и скоро найдутся взаимные симпатии!",
            reply_markup=reply_markup
        )
        return

    matches_text = "💝 Твои совпадения:\n\n"
    keyboard = []

    for match in matches:
        matches_text += f"👤 {match[2]} {match[3] or ''} (@{match[1] or 'без username'})\n🏫 {match[4]}\n\n"
        keyboard.append([InlineKeyboardButton(
            f"👤 {match[2]}",
            callback_data=f"view_match_{match[0]}"
        )])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(matches_text, reply_markup=reply_markup)

async def view_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        match_user_id = int(query.data.replace('view_match_', ''))
    except ValueError:
        await query.answer("Ошибка: неверный ID пользователя")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, first_name, last_name, class, interests, about_me, gender, photo_path, favorite_subject, hobby, dream FROM users WHERE user_id = ?",
        (match_user_id,)
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        await query.answer("Пользователь не найден!")
        return

    profile_text = (
        f"👤 {user[1]} {user[2] or ''}\n"
        f"📱 @{user[0] or 'без username'}\n"
        f"🏫 Класс: {user[3]}\n"
        f"⚧ Пол: {user[6]}\n"
        f"🎯 Интересы: {user[4]}\n"
        f"📚 Любимый предмет: {user[8] or 'Не указано'}\n"
        f"🎨 Хобби: {user[9] or 'Не указано'}\n"
        f"💫 Мечта: {user[10] or 'Не указано'}\n"
        f"📝 О себе: {user[5]}\n"
    )

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="my_matches")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    has_photo = user[7] and os.path.exists(user[7])

    if has_photo:
        with open(user[7], 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=profile_text,
                reply_markup=reply_markup
            )
        await query.delete_message()
    else:
        try:
            await query.edit_message_text(profile_text, reply_markup=reply_markup)
        except BadRequest:
            await query.message.reply_text(profile_text, reply_markup=reply_markup)

async def report_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🚨 Пожаловаться на пользователя", callback_data="start_report")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🚨 Система жалоб\n\n"
        "Если кто-то нарушает правила, вы можете пожаловаться на этого пользователя.\n"
        "Жалобы анонимны и рассматриваются модераторами.\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['awaiting_report_id'] = True

    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="report_user_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Введите ID пользователя, на которого хотите пожаловаться:\n\n"
        "ID можно узнать, если пользователь отправил вам сообщение "
        "или в случае взаимного лайка.",
        reply_markup=reply_markup
    )

async def report_current_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current_match_id = context.user_data.get('current_match_id')

    if not current_match_id:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="find_match")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Сначала найдите пользователя, на которого хотите пожаловаться.",
            reply_markup=reply_markup
        )
        return

    context.user_data['report_target_id'] = current_match_id
    context.user_data['awaiting_report_reason'] = True

    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data="find_match")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Укажите причину жалобы на этого пользователя:\n\n"
        "Примеры причин:\n"
        "• Неприемлемый контент\n"
        "• Оскорбления\n"
        "• Подозрительное поведение\n"
        "• Нарушение правил",
        reply_markup=reply_markup
    )

async def handle_user_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if context.user_data.get('awaiting_report_id'):
        try:
            reported_user_id = int(text)
            context.user_data['report_target_id'] = reported_user_id
            context.user_data.pop('awaiting_report_id', None)
            context.user_data['awaiting_report_reason'] = True

            await update.message.reply_text(
                "Теперь укажите причину жалобы на этого пользователя:"
            )
            return
        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите правильный ID пользователя (только цифры)."
            )
            return

    elif context.user_data.get('awaiting_report_reason'):
        reason = text
        reported_user_id = context.user_data.get('report_target_id')

        if not reported_user_id:
            await update.message.reply_text("Ошибка: пользователь не найден.")
            return

        conn = sqlite3.connect('school_dating.db', check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (reported_user_id,))
        user_exists = cursor.fetchone()

        if not user_exists:
            conn.close()
            await update.message.reply_text(
                "Пользователь с таким ID не найден в системе."
            )
            context.user_data.clear()
            return

        cursor.execute('''
            SELECT id FROM reports 
            WHERE reporter_id = ? AND reported_user_id = ? AND status = 'pending'
        ''', (user_id, reported_user_id))

        existing_report = cursor.fetchone()

        if existing_report:
            conn.close()
            await update.message.reply_text(
                "Вы уже отправляли жалобу на этого пользователя. "
                "Дождитесь ее рассмотрения модераторами."
            )
            context.user_data.clear()
            return

        try:
            cursor.execute('''
                INSERT INTO reports (reporter_id, reported_user_id, reason, reported_at, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, reported_user_id, reason, datetime.now(), 'pending'))

            conn.commit()

            cursor.execute('''
                UPDATE users 
                SET reported_count = reported_count + 1, last_reported = ?
                WHERE user_id = ?
            ''', (datetime.now(), reported_user_id))

            conn.commit()

            cursor.execute("SELECT first_name, last_name, class FROM users WHERE user_id = ?", (reported_user_id,))
            reported_user = cursor.fetchone()

            reported_name = f"{reported_user[0]} {reported_user[1] or ''}" if reported_user else f"Пользователь {reported_user_id}"
            reported_class = reported_user[2] if reported_user else "неизвестно"

            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"🚨 Новая жалоба!\n\n"
                             f"👤 На пользователя: {reported_name}\n"
                             f"🏫 Класс: {reported_class}\n"
                             f"🆔 ID: {reported_user_id}\n"
                             f"📝 Причина: {reason}\n\n"
                             f"Используйте панель модерации для проверки."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")

            conn.close()

            context.user_data.pop('awaiting_report_reason', None)
            context.user_data.pop('report_target_id', None)

            keyboard = [[InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "✅ Ваша жалоба отправлена модераторам!\n\n"
                "Мы рассмотрим ее в ближайшее время.\n"
                "Спасибо за помощь в поддержании порядка!",
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Ошибка при сохранении жалобы: {e}")
            conn.close()
            await update.message.reply_text(
                "😔 Произошла ошибка при отправке жалобы. Попробуйте позже."
            )

async def debug_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if hasattr(update, 'callback_query') else None
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()
    columns_info = "Структура таблицы users:\n"
    for col in columns:
        columns_info += f"• {col[1]} ({col[2]})\n"

    cursor.execute(
        "SELECT user_id, is_under_review, is_approved, first_name, class FROM users WHERE is_under_review = 1")
    pending_profiles = cursor.fetchall()

    pending_info = f"\nАнкеты на модерации (is_under_review=1): {len(pending_profiles)}\n"
    for profile in pending_profiles:
        pending_info += f"• ID: {profile[0]}, Имя: {profile[3]}, Класс: {profile[4]}, review: {profile[1]}, approved: {profile[2]}\n"

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute(
        "SELECT user_id, is_under_review, is_approved, is_active, first_name FROM users ORDER BY user_id DESC LIMIT 10")
    recent_profiles = cursor.fetchall()

    recent_info = f"\nПоследние 10 анкет (всего: {total_users}):\n"
    for profile in recent_profiles:
        recent_info += f"• ID: {profile[0]}, Имя: {profile[4]}, review: {profile[1]}, approved: {profile[2]}, active: {profile[3]}\n"

    debug_text = columns_info + pending_info + recent_info
    conn.close()

    keyboard = [
        [InlineKeyboardButton("🔧 Исправить проблемы", callback_data="fix_moderation")],
        [InlineKeyboardButton("📋 Анкеты на модерации", callback_data="review_profiles")],
        [InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(f"<pre>{debug_text}</pre>", reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(f"<pre>{debug_text}</pre>", reply_markup=reply_markup, parse_mode='HTML')

async def fix_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if hasattr(update, 'callback_query') else None
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]

    fix_log = "Исправление проблем с модерацией:\n\n"

    if 'is_under_review' not in columns:
        fix_log += "❌ Колонка is_under_review отсутствует!\n"
        cursor.execute("ALTER TABLE users ADD COLUMN is_under_review BOOLEAN DEFAULT FALSE")
        fix_log += "✅ Колонка is_under_review добавлена\n"

    cursor.execute(
        "UPDATE users SET is_under_review = 1 WHERE is_approved = 0 AND (is_under_review = 0 OR is_under_review IS NULL)")
    fixed_count = cursor.rowcount
    fix_log += f"✅ Обновлено {fixed_count} анкет с is_under_review = 1\n"

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_under_review = 1")
    pending_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_approved = 1 AND is_under_review = 1")
    wrong_state = cursor.fetchone()[0]
    if wrong_state > 0:
        cursor.execute("UPDATE users SET is_under_review = 0 WHERE is_approved = 1 AND is_under_review = 1")
        fix_log += f"✅ Исправлено {wrong_state} одобренных анкет с is_under_review = 1\n"

    fix_log += f"\nТекущее состояние:\n"
    fix_log += f"• Анкет на модерации: {pending_count}\n"

    conn.commit()
    conn.close()

    keyboard = [
        [InlineKeyboardButton("🔄 Проверить снова", callback_data="debug_moderation")],
        [InlineKeyboardButton("📋 Анкеты на модерации", callback_data="review_profiles")],
        [InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(fix_log, reply_markup=reply_markup)
    else:
        await update.message.reply_text(fix_log, reply_markup=reply_markup)

async def moderation_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if hasattr(update, 'callback_query') else None

    user_id = update.effective_user.id if query else update.message.from_user.id

    if not is_admin(user_id):
        if query:
            await query.answer("У вас нет прав для этого действия!")
        else:
            await update.message.reply_text("У вас нет прав для этого действия!")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'is_under_review' not in columns:
            stats_text = (
                "🛠️ Панель модерации\n\n"
                "⚠️ Внимание: обнаружены проблемы с базой данных!\n"
                "Колонка is_under_review отсутствует.\n\n"
                "Нажмите 'Исправить проблемы' для автоматического исправления."
            )

            keyboard = [
                [InlineKeyboardButton("🔧 Исправить проблемы", callback_data="fix_moderation")],
                [InlineKeyboardButton("🔍 Отладка", callback_data="debug_moderation")],
                [InlineKeyboardButton("📋 Анкеты на модерации", callback_data="review_profiles")],
                [InlineKeyboardButton("🚨 Жалобы", callback_data="review_reports")],
                [InlineKeyboardButton("📊 Статистика", callback_data="moderation_stats")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
        else:
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_under_review = 1")
            pending_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
            reports_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE is_approved = 1")
            approved_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 0")
            banned_users = cursor.fetchone()[0]

            stats_text = (
                "🛠️ Панель модерации\n\n"
                f"📊 Статистика:\n"
                f"• Анкеты на модерации: {pending_count}\n"
                f"• Жалобы на рассмотрении: {reports_count}\n"
                f"• Одобренных пользователей: {approved_users}\n"
                f"• Заблокированных пользователей: {banned_users}\n"
            )

            keyboard = [
                [InlineKeyboardButton("📋 Анкеты на модерации", callback_data="review_profiles")],
                [InlineKeyboardButton("🚨 Жалобы", callback_data="review_reports")],
                [InlineKeyboardButton("📊 Статистика", callback_data="moderation_stats")],
                [InlineKeyboardButton("🔍 Отладка", callback_data="debug_moderation")],
                [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
            ]
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        stats_text = "🛠️ Панель модерации\n\n⚠️ Ошибка при получении данных."

        keyboard = [
            [InlineKeyboardButton("🔧 Исправить проблемы", callback_data="fix_moderation")],
            [InlineKeyboardButton("🔍 Отладка", callback_data="debug_moderation")],
            [InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")]
        ]

    conn.close()

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        try:
            await query.edit_message_text(stats_text, reply_markup=reply_markup)
        except BadRequest:
            await query.message.reply_text(stats_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(stats_text, reply_markup=reply_markup)

async def review_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("У вас нет прав для этого действия!")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'is_under_review' not in columns:
            conn.close()
            keyboard = [
                [InlineKeyboardButton("🔧 Исправить проблемы", callback_data="fix_moderation")],
                [InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "❌ Ошибка: колонка is_under_review отсутствует в базе данных!\n\n"
                "Нажмите кнопку ниже для автоматического исправления.",
                reply_markup=reply_markup
            )
            return

        cursor.execute('''
            SELECT user_id, username, first_name, last_name, class, 
                   interests, about_me, gender, favorite_subject, hobby, dream,
                   registered_at, photo_path, is_under_review
            FROM users 
            WHERE is_under_review = 1 
            ORDER BY registered_at ASC 
            LIMIT 1
        ''')

        profile = cursor.fetchone()
    except Exception as e:
        logger.error(f"Ошибка при получении анкет на модерации: {e}")
        profile = None

    conn.close()

    if not profile:
        keyboard = [
            [InlineKeyboardButton("🔍 Отладка", callback_data="debug_moderation")],
            [InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "✅ Все анкеты проверены! Нет анкет на модерации.\n\n"
            "Если вы ожидали анкеты, нажмите 'Отладка' для проверки.",
            reply_markup=reply_markup
        )
        return

    context.user_data['current_moderation_id'] = profile[0]

    profile_text = (
        f"📋 Анкета на модерации:\n\n"
        f"👤 Пользователь: {profile[2]} {profile[3] or ''}\n"
        f"📱 @{profile[1] or 'без username'}\n"
        f"🏫 Класс: {profile[4]}\n"
        f"⚧ Пол: {profile[7]}\n"
        f"🎯 Интересы: {profile[5]}\n"
        f"📚 Любимый предмет: {profile[8] or 'Не указано'}\n"
        f"🎨 Хобби: {profile[9] or 'Не указано'}\n"
        f"💫 Мечта: {profile[10] or 'Не указано'}\n"
        f"📝 О себе: {profile[6]}\n"
        f"📅 Дата регистрации: {profile[11]}\n"
        f"🆔 ID: {profile[0]}"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data="approve_profile"),
            InlineKeyboardButton("❌ Отклонить", callback_data="reject_profile")
        ],
        [
            InlineKeyboardButton("🚫 Заблокировать", callback_data="ban_profile"),
            InlineKeyboardButton("➡️ Пропустить", callback_data="skip_profile")
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    has_photo = profile[12] and os.path.exists(profile[12])

    if has_photo:
        with open(profile[12], 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=profile_text,
                reply_markup=reply_markup
            )
        await query.delete_message()
    else:
        await query.edit_message_text(profile_text, reply_markup=reply_markup)

async def approve_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    target_user_id = context.user_data.get('current_moderation_id')

    if not target_user_id:
        await query.edit_message_text("Ошибка: анкета не найдена.")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE users SET is_approved = 1, is_under_review = 0 WHERE user_id = ?", (target_user_id,))

        cursor.execute('''
            INSERT INTO admin_actions (admin_id, action, target_user_id, details, action_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 'approve', target_user_id, 'Анкета одобрена', datetime.now()))

        conn.commit()

        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="🎉 Твоя анкета одобрена модераторами!\n\n"
                     "Теперь ты можешь пользоваться ботом полностью!\n"
                     "Используй команду /start для начала работы."
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {target_user_id}: {e}")

        await query.answer("✅ Анкета одобрена!")

        await review_profiles(update, context)

    except Exception as e:
        logger.error(f"Ошибка при одобрении анкеты: {e}")
        await query.answer("❌ Ошибка при одобрении анкеты!")
        await query.edit_message_text("Произошла ошибка при одобрении анкеты.")

    finally:
        conn.close()

async def reject_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    context.user_data['awaiting_reject_reason'] = True
    context.user_data['moderation_target_id'] = context.user_data.get('current_moderation_id')

    await query.edit_message_text(
        "Укажите причину отклонения анкеты:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="review_profiles")]])
    )

async def ban_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    context.user_data['awaiting_ban_reason'] = True
    context.user_data['moderation_target_id'] = context.user_data.get('current_moderation_id')

    await query.edit_message_text(
        "Укажите причину блокировки пользователя:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data="review_profiles")]])
    )

async def handle_moderation_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reason = update.message.text
    target_user_id = context.user_data.get('moderation_target_id')

    if not target_user_id or not reason:
        await update.message.reply_text("Ошибка обработки.")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        action_type = 'reject' if context.user_data.get('awaiting_reject_reason') else 'ban'

        if action_type == 'reject':
            cursor.execute("DELETE FROM users WHERE user_id = ?", (target_user_id,))
            cursor.execute("DELETE FROM likes WHERE from_user_id = ? OR to_user_id = ?",
                           (target_user_id, target_user_id))
            cursor.execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", (target_user_id, target_user_id))
            action_text = "отклонена"
        else:
            cursor.execute("UPDATE users SET is_active = 0, is_approved = 0, is_under_review = 0 WHERE user_id = ?",
                           (target_user_id,))
            action_text = "заблокирована"

        cursor.execute('''
            INSERT INTO admin_actions (admin_id, action, target_user_id, details, action_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, action_type, target_user_id, f"Причина: {reason}", datetime.now()))

        conn.commit()

        try:
            if action_type == 'reject':
                message_text = (
                    f"❌ Твоя анкета отклонена модераторами.\n\n"
                    f"Причина: {reason}\n\n"
                    f"Ты можешь создать новую анкету, соблюдая правила."
                )
            else:
                message_text = (
                    f"🚫 Твоя анкета заблокирована.\n\n"
                    f"Причина: {reason}\n\n"
                    f"Для разблокировки обратись к администраторам."
                )

            await context.bot.send_message(chat_id=target_user_id, text=message_text)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления: {e}")

        context.user_data.pop('awaiting_reject_reason', None)
        context.user_data.pop('awaiting_ban_reason', None)
        context.user_data.pop('moderation_target_id', None)

        await update.message.reply_text(f"✅ Анкета {action_text}!")

        keyboard = [[InlineKeyboardButton("🔙 К модерации", callback_data="review_profiles")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("Что дальше?", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при обработке модерации: {e}")
        await update.message.reply_text("❌ Ошибка при обработке!")

    finally:
        conn.close()

async def skip_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await review_profiles(update, context)

async def review_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT r.id, r.reporter_id, r.reported_user_id, r.reason, r.reported_at, 
                   u1.first_name as reporter_name, u2.first_name as reported_name
            FROM reports r
            LEFT JOIN users u1 ON r.reporter_id = u1.user_id
            LEFT JOIN users u2 ON r.reported_user_id = u2.user_id
            WHERE r.status = 'pending'
            ORDER BY r.reported_at ASC
            LIMIT 1
        ''')

        report = cursor.fetchone()
    except Exception as e:
        logger.error(f"Ошибка при получении жалоб: {e}")
        report = None

    conn.close()

    if not report:
        await query.edit_message_text(
            "✅ Все жалобы обработаны!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]])
        )
        return

    context.user_data['current_report_id'] = report[0]

    report_text = (
        f"🚨 Жалоба #{report[0]}\n\n"
        f"👤 Жалоба от: {report[5] or 'Пользователь'} (ID: {report[1]})\n"
        f"👤 На пользователя: {report[6] or 'Пользователь'} (ID: {report[2]})\n"
        f"📅 Дата: {report[4]}\n"
        f"📝 Причина: {report[3]}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Принять жалобу", callback_data="accept_report"),
            InlineKeyboardButton("❌ Отклонить жалобу", callback_data="dismiss_report")
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(report_text, reply_markup=reply_markup)

async def accept_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    report_id = context.user_data.get('current_report_id')

    if not report_id:
        await query.answer("Ошибка: жалоба не найдена.")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE reports SET status = 'accepted', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                       (user_id, datetime.now(), report_id))

        cursor.execute('''
            SELECT reported_user_id FROM reports WHERE id = ?
        ''', (report_id,))

        reported_user_id = cursor.fetchone()[0]

        cursor.execute('''
            UPDATE users SET reported_count = reported_count + 1, last_reported = ? WHERE user_id = ?
        ''', (datetime.now(), reported_user_id))

        cursor.execute('''
            INSERT INTO admin_actions (admin_id, action, target_user_id, details, action_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 'accept_report', reported_user_id, f'Жалоба #{report_id} принята', datetime.now()))

        conn.commit()

        await query.answer("✅ Жалоба принята!")
        await review_reports(update, context)

    except Exception as e:
        logger.error(f"Ошибка при принятии жалобы: {e}")
        await query.answer("❌ Ошибка при обработке жалобы!")

    finally:
        conn.close()

async def dismiss_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    report_id = context.user_data.get('current_report_id')

    if not report_id:
        await query.answer("Ошибка: жалоба не найдена.")
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE reports SET status = 'dismissed', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                       (user_id, datetime.now(), report_id))

        cursor.execute('''
            INSERT INTO admin_actions (admin_id, action, target_user_id, details, action_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, 'dismiss_report', 0, f'Жалоба #{report_id} отклонена', datetime.now()))

        conn.commit()

        await query.answer("✅ Жалоба отклонена!")
        await review_reports(update, context)

    except Exception as e:
        logger.error(f"Ошибка при отклонении жалобы: {e}")
        await query.answer("❌ Ошибка при обработке жалобы!")

    finally:
        conn.close()

async def moderation_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    conn = sqlite3.connect('school_dating.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_approved = 1")
        approved_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 0")
        banned_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_under_review = 1")
        pending_review = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM matches")
        total_matches = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM likes")
        total_likes = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'accepted'")
        accepted_reports = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
        pending_reports = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM admin_actions")
        total_actions = cursor.fetchone()[0]

        stats_text = (
            "📊 Детальная статистика модерации:\n\n"
            f"👥 Пользователи:\n"
            f"• Всего зарегистрировано: {total_users}\n"
            f"• Одобренных анкет: {approved_users}\n"
            f"• Заблокированных: {banned_users}\n"
            f"• На модерации: {pending_review}\n\n"

            f"💝 Взаимодействия:\n"
            f"• Всего лайков: {total_likes}\n"
            f"• Совпадений: {total_matches}\n\n"

            f"🚨 Жалобы:\n"
            f"• Принято: {accepted_reports}\n"
            f"• На рассмотрении: {pending_reports}\n\n"

            f"⚙️ Действия модераторов:\n"
            f"• Всего действий: {total_actions}\n"
        )
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        stats_text = "📊 Статистика\n\nНе удалось получить данные статистики."

    conn.close()

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="moderation_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(stats_text, reply_markup=reply_markup)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)

def main():
    init_db()

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))

    application.add_handler(CallbackQueryHandler(create_profile, pattern="^create_profile$"))
    application.add_handler(CallbackQueryHandler(view_my_profile, pattern="^view_my_profile$"))
    application.add_handler(CallbackQueryHandler(edit_profile, pattern="^edit_profile$"))
    application.add_handler(CallbackQueryHandler(add_photo, pattern="^add_photo$"))
    application.add_handler(CallbackQueryHandler(delete_profile, pattern="^delete_profile$"))
    application.add_handler(CallbackQueryHandler(confirm_delete, pattern="^confirm_delete$"))
    application.add_handler(CallbackQueryHandler(my_likes, pattern="^my_likes$"))
    application.add_handler(CallbackQueryHandler(find_match, pattern="^find_match$"))
    application.add_handler(CallbackQueryHandler(next_match, pattern="^next_match$"))
    application.add_handler(CallbackQueryHandler(like_user, pattern="^like_user$"))
    application.add_handler(CallbackQueryHandler(view_anonymous_profile, pattern="^view_anonymous_"))
    application.add_handler(CallbackQueryHandler(like_anonymous_user, pattern="^like_anonymous_"))
    application.add_handler(CallbackQueryHandler(my_matches, pattern="^my_matches$"))
    application.add_handler(CallbackQueryHandler(view_match, pattern="^view_match_"))

    application.add_handler(CallbackQueryHandler(moderation_panel, pattern="^moderation_panel$"))
    application.add_handler(CallbackQueryHandler(review_profiles, pattern="^review_profiles$"))
    application.add_handler(CallbackQueryHandler(approve_profile, pattern="^approve_profile$"))
    application.add_handler(CallbackQueryHandler(reject_profile, pattern="^reject_profile$"))
    application.add_handler(CallbackQueryHandler(ban_profile, pattern="^ban_profile$"))
    application.add_handler(CallbackQueryHandler(skip_profile, pattern="^skip_profile$"))
    application.add_handler(CallbackQueryHandler(review_reports, pattern="^review_reports$"))
    application.add_handler(CallbackQueryHandler(accept_report, pattern="^accept_report$"))
    application.add_handler(CallbackQueryHandler(dismiss_report, pattern="^dismiss_report$"))
    application.add_handler(CallbackQueryHandler(moderation_stats, pattern="^moderation_stats$"))
    application.add_handler(CallbackQueryHandler(debug_moderation, pattern="^debug_moderation$"))
    application.add_handler(CallbackQueryHandler(fix_moderation, pattern="^fix_moderation$"))
    application.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

    application.add_handler(CallbackQueryHandler(report_user_menu, pattern="^report_user_menu$"))
    application.add_handler(CallbackQueryHandler(start_report, pattern="^start_report$"))
    application.add_handler(CallbackQueryHandler(report_current_match, pattern="^report_current_match$"))

    application.add_handler(CallbackQueryHandler(handle_gender_selection, pattern="^gender_"))
    application.add_handler(CallbackQueryHandler(handle_search_gender_selection, pattern="^search_"))

    application.add_handler(CallbackQueryHandler(edit_first_name, pattern="^edit_first_name$"))
    application.add_handler(CallbackQueryHandler(edit_last_name, pattern="^edit_last_name$"))
    application.add_handler(CallbackQueryHandler(edit_class, pattern="^edit_class$"))
    application.add_handler(CallbackQueryHandler(edit_interests, pattern="^edit_interests$"))
    application.add_handler(CallbackQueryHandler(edit_favorite_subject, pattern="^edit_favorite_subject$"))
    application.add_handler(CallbackQueryHandler(edit_hobby, pattern="^edit_hobby$"))
    application.add_handler(CallbackQueryHandler(edit_dream, pattern="^edit_dream$"))
    application.add_handler(CallbackQueryHandler(edit_about, pattern="^edit_about$"))
    application.add_handler(CallbackQueryHandler(edit_gender, pattern="^edit_gender$"))
    application.add_handler(CallbackQueryHandler(edit_search, pattern="^edit_search$"))
    application.add_handler(CallbackQueryHandler(update_gender, pattern="^update_gender_"))
    application.add_handler(CallbackQueryHandler(update_search, pattern="^update_search_"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_creation))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("=" * 50)
    print("🤖 Бот знакомств для школы")
    print("=" * 50)
    print("Бот запущен...")
    print("Flask сервер запущен на порту 8080")
    print("Используйте /start для начала работы")
    print("=" * 50)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':

    main()
