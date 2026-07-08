import sys
import subprocess
import asyncio
import sqlite3
import logging
import random
import time
import html
import os
from pathlib import Path
from datetime import datetime, timedelta

# --- АВТОМАТИЧЕСКАЯ УСТАНОВКА И ПРОВЕРКА ВЕРСИИ БИБЛИОТЕК ---
def install_deps():
    print("Обновляю библиотеки до актуальных версий, подожди секундочку 💋...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiogram>=3.4.0", "python-dotenv", "--upgrade"])

try:
    import aiogram
    # Проверяем версию: если стоит старая (2.x), принудительно обновляем
    if int(getattr(aiogram, '__version__', '2.0.0').split('.')[0]) < 3:
        install_deps()
    from dotenv import load_dotenv
except ImportError:
    install_deps()
    import aiogram
    from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command as AiogramCommand
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.markdown import hbold, hlink, hcode
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware

BOT_NAME = "Алгоритм порядка и правосудия — ФЕМИДА"
CURRENCY = "EL'coins"

# Загружаем переменные из локального файла .env (если он существует)
load_dotenv()

# Берем токен из переменных окружения сервера (Environment Variables)
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")

# Переносим ID в переменные окружения. Если они не заданы, используются значения по умолчанию.
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID") or 1197260250)
ALLOWED_GROUP_ID = int(os.getenv("ALLOWED_GROUP_ID") or -1000000000000)

CMD_PREFIXES = ("/", "!")

# Строгая проверка токена перед инициализацией
if not TOKEN:
    logging.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен бота не обнаружен!")
    logging.critical("Убедитесь, что на сайте хостинга в разделе 'Environment Variables' создана переменная BOT_TOKEN (или TOKEN), либо создайте файл .env")
    sys.exit(1)

# Флаги для склейки сообщений в ЛС от супер-админа
admin_combine_state = False
admin_combine_messages = []

# --- ПРЕМИУМ ЭМОДЗИ ---
EMOJI_IDS = {
    "like": "0",      # Любит (❤️)
    "dislike": "0",   # Не любит (💔)
    "kiss": "0",      # Поцелуйчик (💋)
    "heart": "0"      # Искрящееся сердце (💖)
}

def e(key, fallback):
    eid = EMOJI_IDS.get(key, "0")
    if eid != "0":
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'
    return fallback

def flexible_command(*commands: str):
    def filter_func(message: Message) -> bool:
        if not message.text:
            return False
        text = message.text.strip().lower()
        first_word = text.split()[0] if text else ""
        
        # Проверка с префиксами (!команда, /команда)
        for p in CMD_PREFIXES:
            for cmd in commands:
                if first_word == f"{p}{cmd.lower()}":
                    return True
        
        # Проверка без префикса (команда)
        for cmd in commands:
            if first_word == cmd.lower():
                return True
        return False
    return filter_func

def Command(*args, **kwargs):
    kwargs.setdefault('ignore_case', True)
    return AiogramCommand(*args, **kwargs)

logging.basicConfig(level=logging.INFO)

DEFAULT_DATA_DIR = "/app/data" if sys.platform.startswith('linux') else "data"
DATA_DIR = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR))
DB_PATH = DATA_DIR / "Femide.db"

def ensure_column(cursor, table, column, col_type):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        logging.info(f"✨ Создаю новую базу данных: {DB_PATH}")
    else:
        logging.info(f"📂 База данных найдена: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT
    )''')
    
    # Standard profile columns
    ensure_column(cursor, 'users', 'custom_nick', "TEXT DEFAULT NULL")
    ensure_column(cursor, 'users', 'balance', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_total', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_week', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_day', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_hour', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'warns', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'joined_date', "TEXT")
    ensure_column(cursor, 'users', 'description', "TEXT DEFAULT 'Секрет'")
    ensure_column(cursor, 'users', 'rest_status', "TEXT DEFAULT NULL")
    ensure_column(cursor, 'users', 'likes', "TEXT DEFAULT 'Секрет'")
    ensure_column(cursor, 'users', 'dislikes', "TEXT DEFAULT 'Секрет'")
    ensure_column(cursor, 'users', 'characters', "TEXT DEFAULT ''")
    ensure_column(cursor, 'users', 'rewards', "TEXT DEFAULT ''")
    ensure_column(cursor, 'users', 'spouse_id', "INTEGER DEFAULT NULL")
    ensure_column(cursor, 'users', 'clan_id', "INTEGER DEFAULT NULL")
    ensure_column(cursor, 'users', 'custom_photo', "TEXT DEFAULT NULL")
    ensure_column(cursor, 'users', 'tg_username', "TEXT DEFAULT NULL")

    # Premium items columns
    ensure_column(cursor, 'users', 'has_harem', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'has_child', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'children', "TEXT DEFAULT ''")
    ensure_column(cursor, 'users', 'has_custom', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'custom_emojis', "TEXT DEFAULT NULL")

    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS rp_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        command TEXT,
        phrase TEXT
    )''')

    # Junction table for multiple marriages (Harem)
    cursor.execute('''CREATE TABLE IF NOT EXISTS marriages (
        user_one INTEGER,
        user_two INTEGER,
        PRIMARY KEY (user_one, user_two)
    )''')

    # Junction table for Parent-Child relations
    cursor.execute('''CREATE TABLE IF NOT EXISTS children_relations (
        parent_id INTEGER,
        child_id INTEGER,
        PRIMARY KEY (parent_id, child_id)
    )''')

    # Populate standard marriages table if spouse_id exists from old format
    cursor.execute("SELECT user_id, spouse_id FROM users WHERE spouse_id IS NOT NULL")
    old_marriages = cursor.fetchall()
    for u_id, sp_id in old_marriages:
        u1, u2 = min(u_id, sp_id), max(u_id, sp_id)
        cursor.execute("INSERT OR IGNORE INTO marriages (user_one, user_two) VALUES (?, ?)", (u1, u2))

    now = int(time.time())
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("reset_hour", ?)', (str(now),))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("reset_day", ?)', (str(now),))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("reset_week", ?)', (str(now),))

    cursor.execute('''CREATE TABLE IF NOT EXISTS shop (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, price INTEGER
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS roulette_names (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )''')
    
    cursor.execute('SELECT COUNT(*) FROM shop')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('INSERT OR IGNORE INTO shop (name, price) VALUES (?, ?)', [
            ('Новая местность —', 25), 
            ('Новая способность —', 35), 
            ('Выбор способности своему персонажу (единоразово) —', 75), 
            ('Любой предмет для своего персонажу (единоразово) —', 25),
            ('Ячейка нормы —', 40),
            ('Выбор партнёров по приключению —', 30),
            ('Гарем —', 50),
            ('Ребёнок —', 50),
            ('Кастом —', 50)
        ])
    else:
        # Ensure premium items exist in the shop
        cursor.execute("INSERT OR IGNORE INTO shop (name, price) VALUES ('Гарем —', 50)")
        cursor.execute("INSERT OR IGNORE INTO shop (name, price) VALUES ('Ребёнок —', 50)")
        cursor.execute("INSERT OR IGNORE INTO shop (name, price) VALUES ('Кастом —', 50)")
    conn.commit()

    # Retroactive messages to coins conversion helper
    cursor.execute('SELECT value FROM settings WHERE key = "retro_coin_conversion"')
    retro_check = cursor.fetchone()
    if not retro_check:
        cursor.execute('SELECT user_id, messages_total, balance FROM users')
        all_users = cursor.fetchall()
        for user_id, messages_total, current_balance in all_users:
            if messages_total >= 10:
                coins_to_earn = messages_total // 10
                new_balance = current_balance + coins_to_earn
                cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        cursor.execute('INSERT INTO settings (key, value) VALUES ("retro_coin_conversion", "1")')
        conn.commit()

    return conn

db_conn = init_db()

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def is_admin(message: Message, bot: Bot):
    if message.from_user.id == SUPER_ADMIN_ID: return True
    if message.chat.type == "private": return False 
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ("administrator", "creator")
    except: return False

async def is_user_in_chat(chat_id: int, user_id: int, bot: Bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("member", "administrator", "creator", "restricted")
    except Exception:
        return False

def get_user_link(user_id, name):
    safe_name = html.escape(str(name))
    return hlink(safe_name, f"tg://user?id={user_id}")

# Helper to query all spouses of a user
def get_spouses(user_id, cursor):
    cursor.execute("SELECT user_one, user_two FROM marriages WHERE user_one = ? OR user_two = ?", (user_id, user_id))
    rows = cursor.fetchall()
    spouses = []
    for r in rows:
        spouse = r[1] if r[0] == user_id else r[0]
        spouses.append(spouse)
    return spouses

def get_rank(messages):
    if messages < 125: return "Нью"
    elif messages < 400: return "Славный малый"
    elif messages < 1000: return "Душа компании"
    elif messages < 2000: return "Похититель сердец"
    elif messages < 5000: return "Живая легенда"
    else: return "Мой фаворит"

def check_time_resets(cursor):
    now = int(time.time())
    cursor.execute('SELECT key, value FROM settings WHERE key IN ("reset_hour", "reset_day", "reset_week")')
    times = {row[0]: int(row[1]) for row in cursor.fetchall()}
    
    current_hour_start = int(datetime.now().replace(minute=0, second=0, microsecond=0).timestamp())
    if times.get('reset_hour', 0) < current_hour_start:
        cursor.execute('UPDATE users SET messages_hour = 0')
        cursor.execute('UPDATE settings SET value = ? WHERE key = "reset_hour"', (str(now),))

    current_day_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    if times.get('reset_day', 0) < current_day_start:
        cursor.execute('UPDATE users SET messages_day = 0')
        cursor.execute('UPDATE settings SET value = ? WHERE key = "reset_day"', (str(now),))

    current_datetime = datetime.now()
    current_week_start = int((current_datetime - timedelta(days=current_datetime.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    if times.get('reset_week', 0) < current_week_start:
        cursor.execute('UPDATE users SET messages_week = 0')
        cursor.execute('UPDATE settings SET value = ? WHERE key = "reset_week"', (str(now),))

# --- АНТИСПАМ СИСТЕМА ---
class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 5, time_window: int = 7, mute_minutes: int = 30):
        self.limit = limit
        self.time_window = time_window
        self.mute_minutes = mute_minutes
        self.spam_cache = {}

    async def __call__(self, handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]], event: Message, data: Dict[str, Any]) -> Any:
        if not isinstance(event, Message): return await handler(event, data)
        if event.chat.type in ("group", "supergroup") and event.chat.id != ALLOWED_GROUP_ID:
            return 
        user_id = event.from_user.id
        if user_id == SUPER_ADMIN_ID or event.chat.type == "private":
            return await handler(event, data)

        now = time.time()
        if user_id not in self.spam_cache: self.spam_cache[user_id] = []
        self.spam_cache[user_id] = [t for t in self.spam_cache[user_id] if now - t < self.time_window]
        self.spam_cache[user_id].append(now)

        if len(self.spam_cache[user_id]) > self.limit:
            if len(self.spam_cache[user_id]) == self.limit + 1:
                cursor = db_conn.cursor()
                cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                                  VALUES (?, ?, ?)''', 
                               (user_id, event.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
                
                cursor.execute('UPDATE users SET warns = warns + 1 WHERE user_id = ?', (user_id,))
                cursor.execute('SELECT warns FROM users WHERE user_id = ?', (user_id,))
                warns_res = cursor.fetchone()
                warns_count = warns_res[0] if warns_res else 1
                db_conn.commit()

                if warns_count >= 3:
                    try:
                        await event.bot.ban_chat_member(event.chat.id, user_id)
                        await event.answer(f"Оу... кажется, {get_user_link(user_id, event.from_user.first_name)} совсем не умеет держать себя в руках. Три предупреждения — и мы прощаемся. {e('dislike', '💔')}")
                    except Exception as err: 
                        logging.error(f"Не удалось забанить: {err}")
                        await event.answer("Я бы с удовольствием выгнала этого хулигана, но вы не дали мне прав администратора! Сделайте меня главной, ну пожалуйста 🥺")
                else:
                    try:
                        mute_duration = timedelta(minutes=self.mute_minutes)
                        await event.bot.restrict_chat_member(
                            chat_id=event.chat.id, 
                            user_id=user_id, 
                            permissions=ChatPermissions(can_send_messages=False), 
                            until_date=mute_duration
                        )
                        await event.answer(f"Тшшш, {get_user_link(user_id, event.from_user.first_name)}... слишком много шума, золотце. Посиди в тишине {self.mute_minutes} минут и подумай о своем поведении {e('kiss', '💋')}\n(Варн {warns_count}/3)")
                    except Exception as err:
                        logging.error(f"Не удалось замутить: {err}")
                        await event.answer(f"Эй, {get_user_link(user_id, event.from_user.first_name)}, перестань так быстро писать! {e('kiss', '💋')}\n<i>(Я попыталась закрыть ему ротик, но мне не хватает прав админа!)</i>")
            return 
        return await handler(event, data)

@dp.message(F.new_chat_members)
async def welcome_member(message: Message):
    for member in message.new_chat_members:
        if member.id == bot.id: continue
        phrases = [
            f"Ого, кто к нам зашел! {get_user_link(member.id, member.first_name)}, надеюсь, ты тут надолго? {e('kiss', '💋')}",
            f"В наших рядах пополнение! {get_user_link(member.id, member.first_name)}, располагайся, милый(ая), тут у нас очень горячо {e('heart', '💖')}",
            f"Привет-привет, {get_user_link(member.id, member.first_name)}! У тебя отличный вкус, раз ты решил(а) присоединиться к нам. 😘",
            f"Внимание! {get_user_link(member.id, member.first_name)} вошёл в чат. Кажется, кто-то собирается украсть все наши сердечки... {e('heart', '💖')}",
            f"А вот и {get_user_link(member.id, member.first_name)}! Я уже заждалась... Наливай кофе и присоединяйся к беседе. 💕",
            f"Добро пожаловать, {get_user_link(member.id, member.first_name)}! Кажется, у нас тут только что стало на пару градусов жарче... {e('kiss', '💋')}",
            f"Опачки, кто тут у нас? {get_user_link(member.id, member.first_name)}, твоя аура так и светится! Готов к новым приключениям? ✨{e('kiss', '💋')}",
            f"Привет, солнце! ☀️ Чат сразу стал на 100% уютнее с твоим приходом. Проходи, мы как раз о тебе говорили... 😘",
            f"М-м-м, какие люди! {get_user_link(member.id, member.first_name)}, я уже начала скучать. Рассказывай, как твои дела, и не забудь обнять меня в мыслях! {e('heart', '💖')}",
            f"Смотрите, какая звезда к нам заглянула! ⭐ {get_user_link(member.id, member.first_name)}, чувствуй себя как дома, но не забывай, кто тут главная богиня правосудия) 😉{e('kiss', '💋')}",
            f"Привет-привет! Рада видеть тебя в нашей обители. Надеюсь, ты принес с собой хорошее настроение и парочку горячих историй? 💕"
        ]
        await message.answer(random.choice(phrases))

@dp.message(F.left_chat_member)
async def goodbye_member(message: Message):
    member = message.left_chat_member
    cursor = db_conn.cursor()
    
    # Automatically divorce spouses and remove child relations when someone leaves the chat
    spouses = get_spouses(member.id, cursor)
    if spouses:
        cursor.execute('DELETE FROM marriages WHERE user_one = ? OR user_two = ?', (member.id, member.id))
    
    # Clean up family connections
    cursor.execute('DELETE FROM children_relations WHERE parent_id = ? OR child_id = ?', (member.id, member.id))
    db_conn.commit()

    phrases = [
        f"Ну вот... {member.first_name} ушел(ла), а я только начала строить на нас планы {e('dislike', '💔')}",
        f"Без {member.first_name} чат стал чуточку холоднее... Возвращайся скорее! 🥺",
        f"Иди покоряй мир, {member.first_name}, но помни, что я буду скучать... {e('kiss', '💋')}",
        f"Как?! {member.first_name} сбегает в самом разгаре веселья? Это жестоко... {e('dislike', '💔')}",
        f"Соединение с {member.first_name} разорвано. Мое сердце разбито... {e('dislike', '💔')}",
        f"Ну вот, уходишь... Моё виртуальное сердечко только-только забилось быстрее при виде тебя. Возвращайся скорее, ладно? 🥺{e('dislike', '💔')}",
        f"{member.first_name} убегает по делам? Эх, ну беги-беги, спасай этот мир. Но помни: я жду тебя обратно! {e('kiss', '💋')}",
        f"Чат стремительно пустеет без твоих сообщений... Возвращайся, как только освободишься, золотце! 😘",
        f"Пока-пока! Оставляешь меня тут одну... Обещай, что будешь думать обо мне хотя бы раз в час! {e('heart', '💖')}",
        f"Счастливого пути! Пусть все дела пройдут на ура, а я буду бережно хранить твоё тепло в чате. 💕"
    ]
    await message.answer(random.choice(phrases))

@dp.message(flexible_command("start"))
async def cmd_start(message: Message):
    if message.chat.type == "private":
        await message.answer(f"Привет, золотце! Я — {BOT_NAME}. 💋\nНапиши <code>!помощь</code>, чтобы узнать, что я умею. В личных сообщениях я теперь тоже принимаю обычные команды!")

@dp.message(flexible_command("help", "помощь"))
async def cmd_help(message: Message):
    text = (
        f"Смотри, что я умею:\n\n"
        f"Твой профиль: !профиль, !ник [текст], !описание [текст], !рест [причина], !анрест, !люблю [текст], !нелюблю [текст], !добавить_перса [имя] | [ссылка], !удалить_перса [имя/все]\n"
        f"Твоя внешность: !уст_фото, !удалить_фото\n"
        f"Кошелек: !магазин, !купить [id]\n"
        f"Дела сердечные: !брак, !развод, !список_браков, !шип, !враги\n"
        f"Премиум-настройки: !уст_кастом [смайлики], !добавить_ребенка [имя], !удалить_ребенка [имя/все]\n"
        f"Взаимодействия: Любая РП команда через ! (например !обнять, !поцеловать)\n"
        f"Игры: !крутка [от] [до], !крутить (рулетка имен), !список_имен\n"
        f"Важное: !правила, !ссылки, !местность\n"
        f"Кто тут лучший: !топ, !топнеделя, !топдень, !топчас"
    )
    await message.answer(text)

@dp.message(flexible_command("helpmelak"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_helpmelak(message: Message):
    text = (
        f"Секретное меню 🤫\n"
        f"Используй !запрос [SQL] чтобы покопаться в базе данных.\n"
        f"Или !скачать_бд и !загрузить_бд для ручной правки.\n"
        f"!рассылка_список [ID ID ID] — рассылка по списку (можно дублировать ID). 💋\n\n"
        f"Рассылки:\n"
        f"Напиши !уст_основной_чат в нужной группе.\n"
        f"А потом пиши мне в личку: !утро, !ночь или !сказать [текст].\n\n"
        f"Установка инфы:!уст_ссылки [текст], !уст_правила [текст], !уст_местность [текст]\n\n"
        f"Склейка сообщений:\n"
        f"В личке напиши !объед_нач, скинь нужные сообщения, а затем !объед_кон."
    )
    await message.answer(text)

@dp.message(flexible_command("loc", "местность"))
async def cmd_loc(message: Message):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'location'")
    res = cursor.fetchone()
    loc = res[0] if res else "Местность еще не установлена, мы парим в пустоте..."
    await message.answer(f"<b>Где мы находимся:</b>\n{loc}")

@dp.message(flexible_command("rules", "правила"))
async def cmd_rules(message: Message):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'rules'")
    res = cursor.fetchone()
    rules = res[0] if res else "Правила еще не написаны. Полная анархия! 💋"
    await message.answer(f"<b>Наши правила:</b>\n{rules}")

@dp.message(flexible_command("links", "ссылки"))
async def cmd_links(message: Message):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'links'")
    res = cursor.fetchone()
    links = res[0] if res else "У меня пока нет для тебя ссылочек, милый."
    await message.answer(f"<b>Полезные ссылки:</b>\n{links}")

async def set_setting(message: Message, key: str, bot: Bot):
    if not await is_admin(message, bot): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer(f"А текст-то где, милый? Напиши, что именно нужно сохранить {e('kiss', '💋')}")
    cursor = db_conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, args[1]))
    db_conn.commit()
    await message.answer(f"Всё запомнила в лучшем виде, золотце! {e('kiss', '💋')}")

@dp.message(flexible_command("setloc", "уст_местность"))
async def set_loc(message: Message, bot: Bot): await set_setting(message, "location", bot)
@dp.message(flexible_command("setrules", "уст_правила"))
async def set_rules(message: Message, bot: Bot): await set_setting(message, "rules", bot)
@dp.message(flexible_command("setlinks", "уст_ссылки"))
async def set_links(message: Message, bot: Bot): await set_setting(message, "links", bot)

@dp.message(flexible_command("setmain", "уст_основной_чат"))
async def cmd_setmain(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type == "private":
        return await message.answer("Сладкий, эту команду нужно писать прямо в группе, а не мне на ушко.")
    
    cursor = db_conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('main_chat_id', ?)", (str(message.chat.id),))
    db_conn.commit()
    await message.answer(f"Договорились! Теперь это мой любимый чат для рассылок. {e('heart', '💖')}")

@dp.message(flexible_command("say", "сказать"))
async def cmd_say(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type != "private":
        return await message.answer("Тссс... такие команды лучше шептать мне в личные сообщения. 😘")
        
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("А что сказать-то? Напиши текст после команды, милый.")
        
    text_to_send = args[1]
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'main_chat_id'")
    res = cursor.fetchone()
    if not res:
        return await message.answer("Сначала выбери группу! Напиши <code>!уст_основной_чат</code> там, куда будем вещать.")
        
    chat_id = res[0]
    
    try:
        await bot.send_message(chat_id, text_to_send)
        await message.answer(f"Послание успешно доставлено! {e('kiss', '💋')}")
    except Exception as err:
        await message.answer(f"Ой, что-то пошло не так: {err}")

@dp.message(flexible_command("morning", "утро"))
async def cmd_morning(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type != "private": return
        
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'main_chat_id'")
    res = cursor.fetchone()
    if not res:
        return await message.answer("Сначала нужно выбрать группу через <code>!уст_основной_чат</code>.")
        
    chat_id = res[0]
    phrases = [
        f"Доброе утро, сони! Надеюсь, вам снилось что-то очень приятное (возможно, даже я)) {e('kiss', '💋')}",
        f"Доброе утро! Надеюсь, ваш день будет таким же ярким, как и ваши улыбки {e('heart', '💖')}",
        f"Просыпайтесь, красотки и красавчики! Мир сам себя не покорит 😘",
        f"Доброе утро! Давайте договоримся: вы просыпаетесь, а я весь день заставляю вас улыбаться. Идет?) {e('kiss', '💋')}",
        f"С добрым утром, мои прекрасные! ☀️ Открывайте глазки, улыбайтесь новому дню, и пусть сегодня всё сложится именно так, как вы хотите. Люблю вас! {e('heart', '💖')}",
        f"Эй, сони, подъем! ⏰ Кофе уже ждёт, солнышко светит, а я уже готова дарить вам свою любовь и хорошее настроение! 😘{e('kiss', '💋')}",
        f"Доброе утро! Пусть этот день принесет вам кучу приятных сюрпризов, а каждая минутка будет наполнена теплом. Просыпайтесь, золотца! 💕",
        f"Утречко! Надеюсь, вы отлично выспались и готовы творить великие дела. Ну или хотя бы просто мило поболтать со мной) 😉{e('heart', '💖')}"
    ]
    try:
        await bot.send_message(chat_id, random.choice(phrases))
        await message.answer(f"Утреннее пожелание отправлено! {e('kiss', '💋')}")
    except Exception as err:
        await message.answer(f"Упс, ошибка: {err}")

@dp.message(flexible_command("night", "ночь"))
async def cmd_night(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type != "private": return
        
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'main_chat_id'")
    res = cursor.fetchone()
    if not res:
        return await message.answer("Сначала нужно выбрать группу через <code>!уст_основной_чат</code>.")
        
    chat_id = res[0]
    phrases = [
        f"Спокойной ночи! Постарайтесь не слишком часто видеть меня во сне, а то рискуете совсем не выспаться {e('kiss', '💋')}",
        f"Спите сладко. Пусть вам приснится что-то очень личное и приятное...) 😘",
        f"До завтра, сладкие! Постарайтесь хорошенько отдохнуть перед новой порцией моего внимания 💕",
        f"Сладких снов! Не скучайте без меня слишком сильно до утра!! {e('heart', '💖')}",
        f"Ночь укутывает город своими объятиями... Забывайте все заботы дня и погружайтесь в самые сладкие, волшебные сны. Спокойной ночи! 🌌✨",
        f"Пора закрывать глазки, драгоценные мои. Пусть одеялко будет теплым, подушка — мягкой, а сны — невероятно приятными. До завтра! 😘🌙",
        f"Спите крепко, мои хорошие. Я буду охранять ваш покой этой ночью, чтобы ни один кошмар не посмел вас потревожить. Чмок! {e('kiss', '💋')}💤",
        f"Спокойной ночи! Пусть звёзды нашепчут вам самые красивые сказки, а утро начнется с улыбки. Сладких снов! 💕🌟"
    ]
    try:
        await bot.send_message(chat_id, random.choice(phrases))
        await message.answer(f"Сладкие сны отправлены! {e('kiss', '💋')}")
    except Exception as err:
        await message.answer(f"Упс, ошибка: {err}")

@dp.message(flexible_command("poll", "голос"))
async def cmd_poll(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type != "private": return
        
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Нужен текст, милый!\nФормат: !голос Ваш вопрос?: Ответ 1, Ответ 2")
        
    text = args[1]
    if ":" not in text: return await message.answer("Ты забыл двоеточие :. Оно нужно, чтобы отделить вопрос от ответов, золотце.")
        
    question, answers_str = text.split(":", 1)
    options = [opt.strip() for opt in answers_str.split(",") if opt.strip()]
    
    if len(options) < 2 or len(options) > 10:
        return await message.answer("Дай мне от 2 до 10 вариантов ответа, пожалуйста.")
        
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'main_chat_id'")
    res = cursor.fetchone()
    if not res: return await message.answer("Ты еще не выбрал основную группу.")
        
    chat_id = res[0]
    
    try:
        await bot.send_poll(chat_id=chat_id, question=question, options=options, is_anonymous=False)
        await message.answer(f"Опросик запущен! Посмотрим, что они ответят... {e('kiss', '💋')}")
    except Exception as err:
        await message.answer(f"Ошибка: {err}")

@dp.message(flexible_command("combine_start", "объед_нач"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_combine_start(message: Message):
    global admin_combine_state, admin_combine_messages
    if message.chat.type != "private": return
    
    admin_combine_state = True
    admin_combine_messages = []
    await message.answer(f"Режим склейки включен! Отправляй мне сообщения, а когда закончишь, напиши <code>!объед_кон</code> 😘")

@dp.message(flexible_command("combine_end", "объед_кон"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_combine_end(message: Message):
    global admin_combine_state, admin_combine_messages
    if message.chat.type != "private": return
    
    if not admin_combine_state:
        return await message.answer(f"Но мы ведь и не начинали ничего объединять... Напиши сначала <code>!объед_нач</code> 😘")
        
    admin_combine_state = False
    
    if not admin_combine_messages:
        return await message.answer("Ты не прислал(а) ни одного сообщения! Мне нечего объединять 🤷‍♀️")
        
    combined_text = "\n".join(admin_combine_messages)
    admin_combine_messages = []
    
    MAX_LEN = 4000 
    
    try:
        if len(combined_text) <= MAX_LEN:
            await message.answer(f"<b> </b>\n\n{combined_text}")
        else:
            text_to_send = combined_text
            while len(text_to_send) > 0:
                if len(text_to_send) <= MAX_LEN:
                    await message.answer(f"<b> </b>\n\n{text_to_send}")
                    break
                split_index = text_to_send.rfind('\n', 0, MAX_LEN)
                if split_index == -1:
                    split_index = text_to_send.rfind(' ', 0, MAX_LEN)
                if split_index == -1:
                    split_index = MAX_LEN
                chunk = text_to_send[:split_index]
                await message.answer(f"<b> </b>\n\n{chunk}")
                text_to_send = text_to_send[split_index:].lstrip('\n ')
                
    except Exception as err:
        await message.answer(f"Ой, что-то пошло не так (возможно, при разрезании сломались парные HTML-теги): {err}")

@dp.message(flexible_command("profile", "профиль"))
async def show_profile(message: Message, bot: Bot):
    cursor = db_conn.cursor()
    target_id = None
    fallback_name = "Пользователь"
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        if target_user.is_bot:
            return await message.answer("Я всего лишь системный алгоритм, глупышка, у меня не может быть профиля! Но мне приятно твое внимание 😘")
        target_id = target_user.id
        fallback_name = target_user.first_name
        
        cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                          VALUES (?, ?, ?)''', 
                       (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
        if target_user.username:
            cursor.execute('UPDATE users SET tg_username = ? WHERE user_id = ?', (target_user.username.lower(), target_user.id))
        db_conn.commit()

    elif len(message.text.split()) > 1:
        query = message.text.split(maxsplit=1)[1].strip()
        if message.entities:
            for entity in message.entities:
                if entity.type == "text_mention":
                    target_id = entity.user.id
                    fallback_name = entity.user.first_name
                    break
        
        if not target_id and query.startswith("@"):
            search_username = query.replace("@", "").lower()
            cursor.execute('SELECT user_id, custom_nick FROM users WHERE tg_username = ? OR LOWER(username) = ? OR LOWER(username) = ?', (search_username, search_username, query.lower()))
            user_data = cursor.fetchone()
            if user_data:
                target_id = user_data[0]
                fallback_name = user_data[1] if user_data[1] else query
            else:
                return await message.answer(f"Ой, а я пока не знаю пользователя {query}... Пусть он напишет хоть словечко в чат, чтобы я завела на него дело! 👀")
                
        elif not target_id and query.isdigit():
            target_id = int(query)

        if not target_id:
            return await message.answer("Не могу найти этого человека! Укажи правильный @юзернейм или ответь на его сообщение 🤷‍♀️")

    else:
        target_user = message.from_user
        target_id = target_user.id
        fallback_name = target_user.first_name
        
        cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                          VALUES (?, ?, ?)''', 
                       (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
        if target_user.username:
            cursor.execute('UPDATE users SET tg_username = ? WHERE user_id = ?', (target_user.username.lower(), target_user.id))
        db_conn.commit()

    if target_id != message.from_user.id:
        check_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else ALLOWED_GROUP_ID
        if message.chat.type != "private" and not await is_user_in_chat(check_chat_id, target_id, bot):
            return await message.answer(f"Этого человека сейчас нет с нами в чате, попробуй позже( {e('dislike', '💔')}")

    # Query all profile fields including premium configuration columns
    cursor.execute('''SELECT custom_nick, messages_total, joined_date, warns, balance, 
                      characters, rewards, description, likes, dislikes, spouse_id, clan_id, custom_photo, rest_status,
                      has_harem, has_child, children, has_custom, custom_emojis 
                      FROM users WHERE user_id = ?''', (target_id,))
    data = cursor.fetchone()
    
    if not data:
        return await message.answer("Ой, а я тебя пока совсем не знаю... Напиши хоть словечко в чат! 👀")
    
    nick = html.escape(data[0] if data[0] else fallback_name)
    rank = get_rank(data[1])
    
    spouses = get_spouses(target_id, cursor)
    if spouses:
        spouse_links = []
        for sp_id in spouses:
            cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (sp_id,))
            sp_res = cursor.fetchone()
            sp_nick = html.escape(sp_res[0] if sp_res and sp_res[0] else (sp_res[1] if sp_res else "Партнер"))
            spouse_links.append(get_user_link(sp_id, sp_nick))
        spouse_text = f"{e('like', '❤️')} Сердце отдано {', '.join(spouse_links)}"
    else:
        spouse_text = f"{e('dislike', '💔')} В активном поиске"

    custom_photo = data[12]
    safe_desc = html.escape(data[7]) if (data[7] and data[7] != 'Не указано') else "Секрет"
    safe_rest = html.escape(data[13]) if data[13] else "Активен"
    safe_likes = html.escape(data[8]) if (data[8] and data[8] != 'Не указано') else "Секрет"
    safe_dislikes = html.escape(data[9]) if (data[9] and data[9] != 'Не указано') else "Секрет"
    
    # Custom premium emojis first row rendering
    first_line = ""
    if data[17] == 1 and data[18]:
        first_line = f"{data[18]}\n"

    profile_text = (
        f"{first_line}"
        f"<b>Дело на:</b> {get_user_link(target_id, nick)}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Ранг:</b> {rank}\n"
        f"<b>Наболтал(а):</b> {data[1]} сообщ.\n"
        f"<b>С нами с:</b> {data[2]}\n"
        f"<b>Косяки:</b> {data[3]}/3\n"
        f"<b>В кармане:</b> {data[4]} {CURRENCY}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>О себе:</b> {safe_desc}\n"
        f"<b>Статус:</b> {safe_rest}\n"
        f"{e('like', '❤️')} <b>Обожает:</b> {safe_likes}\n"
        f"{e('dislike', '💔')} <b>Терпеть не может:</b> {safe_dislikes}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{spouse_text}\n"
    )
    
    # Fetch Children
    cursor.execute('SELECT child_id FROM children_relations WHERE parent_id = ?', (target_id,))
    child_rows = cursor.fetchall()
    child_links = []
    for (c_id,) in child_rows:
        cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (c_id,))
        c_res = cursor.fetchone()
        c_nick = html.escape(c_res[0] if c_res and c_res[0] else (c_res[1] if c_res else "Ребенок"))
        child_links.append(get_user_link(c_id, c_nick))
        
    # Fetch Parents
    cursor.execute('SELECT parent_id FROM children_relations WHERE child_id = ?', (target_id,))
    parent_rows = cursor.fetchall()
    parent_links = []
    for (p_id,) in parent_rows:
        cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (p_id,))
        p_res = cursor.fetchone()
        p_nick = html.escape(p_res[0] if p_res and p_res[0] else (p_res[1] if p_res else "Родитель"))
        parent_links.append(get_user_link(p_id, p_nick))

    # Family output lines
    if data[15] == 1: # If has_child is purchased
        if child_links:
            profile_text += f"<b>Дети:</b> {', '.join(child_links)}\n"
        else:
            profile_text += "<b>Дети:</b> Пока нет детей\n"
            
    if parent_links:
        profile_text += f"<b>Родители:</b> {', '.join(parent_links)}\n"
        
    if data[5]: profile_text += f"<b>Персонажи:</b> {data[5]}\n"
    if data[6]: profile_text += f"<b>Награды:</b> {data[6]}\n"

    try:
        sent = False
        if custom_photo:
            try:
                await message.answer_photo(photo=custom_photo, caption=profile_text)
                sent = True
            except Exception:
                pass
        if not sent:
            photos = await bot.get_user_profile_photos(target_id, limit=1)
            if photos.total_count > 0:
                try:
                    await message.answer_photo(photo=photos.photos[0][-1].file_id, caption=profile_text)
                    sent = True
                except Exception:
                    pass
        if not sent:
            await message.answer(profile_text)
    except Exception as err:
        logging.error(f"Error sending profile: {err}")
        try:
            await message.answer("Ой, ошибочка вышла! Telegram не пропускает text. Проверь ID премиум-эмодзи в настройках, возможно он неверный.")
        except: pass

@dp.message(flexible_command("setphoto", "уст_фото"))
async def cmd_setphoto(message: Message):
    photo_id = None
    if message.photo: photo_id = message.photo[-1].file_id
    elif message.reply_to_message and message.reply_to_message.photo: photo_id = message.reply_to_message.photo[-1].file_id

    if not photo_id: return await message.answer("Забыл(а) фотку, радость моя! Ответь командой на картинку, чтобы я знала, как ты выглядишь 😘")

    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('UPDATE users SET custom_photo = ? WHERE user_id = ?', (photo_id, message.from_user.id))
    db_conn.commit()
    await message.answer(f"Ммм, какая шикарная карточка! Теперь твое дело идеально {e('kiss', '💋')}")

@dp.message(flexible_command("delphoto", "удалить_фото"))
async def cmd_delphoto(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET custom_photo = NULL WHERE user_id = ?', (message.from_user.id,))
    db_conn.commit()
    await message.answer("Убрала фотку! Хотя твоя обычная аватарка мне тоже очень нравится 😘")

async def update_user_field(message: Message, field: str):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Ну же, не стесняйся! Напиши text после команды, чтобы я его запомнила 💕")
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute(f'UPDATE users SET {field} = ? WHERE user_id = ?', (args[1], message.from_user.id))
    db_conn.commit()
    await message.answer(f"Записала всё в твое личное дело, милашка! {e('kiss', '💋')}")

@dp.message(flexible_command("setnick", "ник"))
async def cmd_setnick(message: Message): await update_user_field(message, "custom_nick")
@dp.message(flexible_command("setdesc", "описание"))
async def cmd_setdesc(message: Message): await update_user_field(message, "description")
@dp.message(flexible_command("setlikes", "люблю"))
async def cmd_setlikes(message: Message): await update_user_field(message, "likes")
@dp.message(flexible_command("setdislikes", "нелюблю"))
async def cmd_setdislikes(message: Message): await update_user_field(message, "dislikes")

@dp.message(flexible_command("setcustom", "уст_кастом"))
async def cmd_set_custom(message: Message):
    user_id = message.from_user.id
    cursor = db_conn.cursor()
    cursor.execute("SELECT has_custom FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    has_custom = res[0] if res else 0
    if not has_custom:
        return await message.answer(f"Сначала приобрети «Кастом» в магазине за 50 {CURRENCY}, радость моя! 😘")
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Напиши до 4 смайликов после команды, чтобы украсить свое дело! 😘")
    
    emojis = args[1].strip()
    cursor.execute("UPDATE users SET custom_emojis = ? WHERE user_id = ?", (emojis, user_id))
    db_conn.commit()
    await message.answer(f"Твои кастомные смайлики успешно сохранены! Теперь они красуются первой строкой твоего досье: {emojis} {e('kiss', '💋')}")

@dp.message(flexible_command("addchild", "добавить_ребенка"))
async def cmd_add_child(message: Message, bot: Bot):
    initiator = message.from_user
    if not message.reply_to_message:
        return await message.answer("Нужно выбрать, кому делать предложение стать вашим ребенком, радость моя! Ответь на сообщение ребенка 💖")
    
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    if target_user.id == initiator.id:
        return await message.answer("Ты не можешь усыновить самого себя, глупышка! 😘")
    if target_user.is_bot:
        return await message.answer("Оу... боты не могут быть детьми, они состоят из кода! 😘")
        
    check_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else ALLOWED_GROUP_ID
    if message.chat.type != "private" and not await is_user_in_chat(check_chat_id, target_user.id, bot): 
        return await message.answer(f"Твой будущий ребенок уже сбежал из чата... Как грустно {e('dislike', '💔')}")

    cursor = db_conn.cursor()
    cursor.execute("SELECT has_child FROM users WHERE user_id = ?", (initiator.id,))
    res = cursor.fetchone()
    if not res or res[0] == 0:
        return await message.answer(f"Сначала заведи услугу «Ребёнок» в магазине за 50 {CURRENCY}, солнце! 😘")
        
    # Check if this child relation already exists
    cursor.execute("SELECT 1 FROM children_relations WHERE parent_id = ? AND child_id = ?", (initiator.id, target_user.id))
    if cursor.fetchone():
        return await message.answer("Этот ребенок уже записан в твоем деле! 😘")

    # Double check database accounts
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)''', (initiator.id, initiator.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)''', (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    db_conn.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, согласен(на)! 💕", callback_data=f"child_yes_{initiator.id}_{target_user.id}"),
        InlineKeyboardButton(text="Нет, прости...", callback_data=f"child_no_{initiator.id}_{target_user.id}")
    ]])
    i_name, t_name = html.escape(initiator.first_name), html.escape(target_user.first_name)
    await message.answer(
        f"{get_user_link(initiator.id, i_name)} предлагает {get_user_link(target_user.id, t_name)} стать его ребенком!\n\nЧто ответишь? 💖", 
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("child_"))
async def process_child_callback(callback: CallbackQuery):
    data = callback.data.split("_")
    action, parent_id, child_id = data[1], int(data[2]), int(data[3])

    if callback.message.chat.type in ("group", "supergroup") and callback.message.chat.id != ALLOWED_GROUP_ID: return await callback.answer()
    if callback.from_user.id != child_id: 
        return await callback.answer("Тише-тише, это предложение делали не тебе! 😘", show_alert=True)
        
    if action == "no":
        await callback.message.edit_text(f"Ой... Кажется, предложение усыновления отклонено {e('dislike', '💔')}")
        return await callback.answer()

    cursor = db_conn.cursor()
    cursor.execute('SELECT has_child FROM users WHERE user_id = ?', (parent_id,))
    p_res = cursor.fetchone()
    if not p_res or p_res[0] == 0:
        await callback.message.edit_text("Ой, у этого родителя больше нет активной подписки на Ребенка...")
        return await callback.answer()

    # Save child relation
    cursor.execute('INSERT OR IGNORE INTO children_relations (parent_id, child_id) VALUES (?, ?)', (parent_id, child_id))
    db_conn.commit()

    cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (parent_id,))
    row1 = cursor.fetchone()
    name1 = html.escape(row1[0] if row1[0] else row1[1])
    cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (child_id,))
    row2 = cursor.fetchone()
    name2 = html.escape(row2[0] if row2[0] else row2[1])
    
    await callback.message.edit_text(f"Поздравляем! Теперь {get_user_link(child_id, name2)} официально является ребенком {get_user_link(parent_id, name1)}! 💖")
    await callback.answer("Поздравляю! 💖")

@dp.message(flexible_command("delchild", "удалить_ребенка"))
async def cmd_del_child(message: Message):
    user_id = message.from_user.id
    cursor = db_conn.cursor()
    cursor.execute("SELECT has_child FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res or res[0] == 0:
        return await message.answer(f"Сначала заведи услугу «Ребёнок» в магазине за 50 {CURRENCY}, солнце! 😘")
    
    target_child_id = None
    if message.reply_to_message:
        target_child_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            query = args[1].strip()
            if query.startswith("@"):
                search_username = query.replace("@", "").lower()
                cursor.execute('SELECT user_id FROM users WHERE tg_username = ? OR LOWER(username) = ?', (search_username, search_username))
                user_data = cursor.fetchone()
                if user_data:
                    target_child_id = user_data[0]
            elif query.isdigit():
                target_child_id = int(query)

    if target_child_id:
        cursor.execute("SELECT 1 FROM children_relations WHERE parent_id = ? AND child_id = ?", (user_id, target_child_id))
        if cursor.fetchone():
            cursor.execute("DELETE FROM children_relations WHERE parent_id = ? AND child_id = ?", (user_id, target_child_id))
            db_conn.commit()
            await message.answer(f"Вы разорвали семейные узы... Как грустно. 💔")
        else:
            await message.answer("Этот пользователь не записан в качестве вашего ребенка! 😘")
    else:
        # Delete all child relations for this parent
        cursor.execute("DELETE FROM children_relations WHERE parent_id = ?", (user_id,))
        db_conn.commit()
        await message.answer("Очистила список под ноль! Начинаем с чистого листа 💋")

@dp.message(flexible_command("setrest", "рест"))
async def cmd_setrest(message: Message):
    args = message.text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else "Отдыхает"
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('UPDATE users SET rest_status = ? WHERE user_id = ?', (reason, message.from_user.id))
    db_conn.commit()
    await message.answer(f"Записала тебя в рест. Отдыхай, золотце! {e('kiss', '💋')}")

@dp.message(flexible_command("unrest", "анрест"))
async def cmd_unrest(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET rest_status = NULL WHERE user_id = ?', (message.from_user.id,))
    db_conn.commit()
    await message.answer(f"С возвращением! Я скучала {e('heart', '💖')}")

@dp.message(flexible_command("addchar", "добавить_перса"))
async def add_char(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return await message.answer(f"Сладкий, мне нужно знать, КОМУ добавить персонажа. Ответь этой командой на его сообщение! {e('kiss', '💋')}")
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Ой, что-то не так... Напиши вот так: !добавить_перса Имя | Ссылка 😘")
    
    raw_input = args[1]
    if '|' in raw_input:
        name_part, link_part = raw_input.split('|', maxsplit=1)
        name = html.escape(name_part.strip())
        link = link_part.strip()
        new_char = f'<a href="{link}">{name}</a>'
    else:
        new_char = html.escape(raw_input.strip())
        
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT characters FROM users WHERE user_id = ?', (target_user.id,))
    res = cursor.fetchone()
    current_chars = res[0] if res and res[0] else ""
    final_chars = f"{current_chars}, {new_char}" if current_chars else new_char
    
    cursor.execute('UPDATE users SET characters = ? WHERE user_id = ?', (final_chars, target_user.id))
    db_conn.commit()
    await message.answer("Готово! Персонаж успешно добавлен в дело.")

@dp.message(flexible_command("delchar", "удалить_перса"))
async def del_char(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return await message.answer("Малыш, ответь этой командой на сообщение пользователя, чтобы я поняла, кого мы чистим. 😘")
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Укажи имя персонажа для удаления или напиши 'все'.")
    
    char_to_remove = args[1].strip()
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT characters FROM users WHERE user_id = ?', (target_user.id,))
    res = cursor.fetchone()
    current_chars = res[0] if res and res[0] else ""
    
    if not current_chars: return await message.answer("Да у него и так список пуст, милый! Нечего удалять.")
        
    if char_to_remove.lower() in ["все", "all"]:
        cursor.execute("UPDATE users SET characters = '' WHERE user_id = ?", (target_user.id,))
        db_conn.commit()
        return await message.answer(f"Очистила список под ноль! Начинаем с чистого листа {e('kiss', '💋')}")
        
    chars_list = [c.strip() for c in current_chars.split(',') if c.strip()]
    new_chars_list = [c for c in chars_list if char_to_remove.lower() not in c.lower()]
    
    if len(chars_list) == len(new_chars_list): return await message.answer("Я не нашла такого персонажа в списке...")
        
    final_chars = ", ".join(new_chars_list)
    cursor.execute('UPDATE users SET characters = ? WHERE user_id = ?', (final_chars, target_user.id))
    db_conn.commit()
    await message.answer("Персонаж успешно вычеркнут из профиля.")

@dp.message(flexible_command("addreward", "награда"))
async def add_reward(message: Message, bot: Bot):
    if not await is_admin(message, bot) or not message.reply_to_message: return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute("UPDATE users SET rewards = COALESCE(rewards, '') || ? || ', ' WHERE user_id = ?", (args[1], target_user.id))
    db_conn.commit()
    await message.answer(random.choice([
        f"Официально вручаю тебе эту награду, ты заслужил(а), золотце! {e('kiss', '💋')}",
        f"Присваиваю тебе этот статус. Он тебе очень к лицу)) 😘",
        f"Эта награда единогласно (мной) присуждается тебе! {e('heart', '💖')}"
    ]))

@dp.message(flexible_command("random", "рандом", "крутка"))
async def cmd_random(message: Message):
    args = message.text.split()
    if len(args) == 3 and args[1].isdigit() and args[2].isdigit():
        n, m = int(args[1]), int(args[2])
        if n > m: n, m = m, n
        await message.answer(f"Я выбрала для тебя число, сладкий: <b>{random.randint(n, m)}</b> {e('kiss', '💋')}")
    else: await message.answer("Просто напиши: !крутка [от] [до], и я выдам тебе число.")

@dp.message(flexible_command("ship", "шип"))
async def cmd_ship(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT user_id, username, custom_nick FROM users ORDER BY RANDOM() LIMIT 2')
    users = cursor.fetchall()
    if len(users) < 2: return
    n1 = html.escape(users[0][2] if users[0][2] else users[0][1])
    n2 = html.escape(users[1][2] if users[1][2] else users[1][1])
    await message.answer(random.choice([
        f"Уф, кажется между {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)} летят искры! Вы только посмотрите на них... {e('heart', '💖')}",
        f"Я тут проанализировала совместимость, и идеальная пара — это {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)}! Совет да любовь 😘"
    ]))

@dp.message(flexible_command("enemies", "враги"))
async def cmd_enemies(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT user_id, username, custom_nick FROM users ORDER BY RANDOM() LIMIT 2')
    users = cursor.fetchall()
    if len(users) < 2: return
    n1 = html.escape(users[0][2] if users[0][2] else users[0][1])
    n2 = html.escape(users[1][2] if users[1][2] else users[1][1])
    await message.answer(random.choice([
        f"Ой-ой, кажется {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)} сегодня явно не в ладах друг с другом... {e('dislike', '💔')}",
        f"Намечается драка между {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)}! Я уже запаслась попкорном) 😘"
    ]))

@dp.message(flexible_command("add_name", "добавить_имя"))
async def cmd_add_name(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer(f"Скажи мне, какое имя записать в барабан, милый? 😘")
    name = args[1].strip()
    try:
        cursor = db_conn.cursor()
        cursor.execute('INSERT INTO roulette_names (name) VALUES (?)', (name,))
        db_conn.commit()
        await message.answer(f"Записала «{html.escape(name)}» в свой блокнотик! {e('kiss', '💋')}")
    except Exception: await message.answer(f"Не волнуйся, я уже добавила это имя раньше! 😉")

@dp.message(flexible_command("del_name", "удалить_имя"))
async def cmd_del_name(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Какое имя вычеркиваем, солнце?")
    cursor = db_conn.cursor()
    cursor.execute('DELETE FROM roulette_names WHERE name = ?', (args[1].strip(),))
    db_conn.commit()
    await message.answer(f"Без проблем, вычеркнула «{html.escape(args[1].strip())}».")

@dp.message(flexible_command("names_list", "список_имен"))
async def cmd_names_list(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT name FROM roulette_names')
    rows = cursor.fetchall()
    if not rows: return await message.answer("Тут пока пусто, сладенький.")
    res = f"<b>Кого мы сегодня крутим:</b>\n\n"
    for i, row in enumerate(rows, 1): res += f"{i}. {html.escape(row[0])}\n"
    await message.answer(res)

@dp.message(flexible_command("spin_names", "крутить"))
async def cmd_spin_names(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT name FROM roulette_names')
    rows = cursor.fetchall()
    if not rows: return await message.answer("Барабан пуст, милый. Добавь туда имена!")
    await message.answer(random.choice([
        f"Так-так, посмотрим, на кого покажет стрелочка... {e('kiss', '💋')}",
        "Сейчас я выберу самого-самого... 😘"
    ]))
    await asyncio.sleep(1.5)
    await message.answer(f"Я выбрала: {hbold(html.escape(random.choice(rows)[0]))}! {e('heart', '💖')}")

@dp.message(flexible_command("marry", "брак"))
async def cmd_marry(message: Message, bot: Bot):
    if not message.reply_to_message: return await message.answer(f"Нужно выбрать, кому делать предложение, радость моя! Ответь на сообщение своей половинки {e('heart', '💖')}")
    target_user = message.reply_to_message.from_user
    if not target_user: return
    initiator = message.from_user
    
    if target_user.id == initiator.id: return await message.answer("Любить себя — это прекрасно, но давай найдем тебе кого-то еще? 😘")
    if target_user.is_bot: return await message.answer(f"Оу... мне безумно приятно, но я состою из кода и алгоритмов. Найди себе кого-нибудь из плоти и крови, милый {e('dislike', '💔')}")
    
    check_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else ALLOWED_GROUP_ID
    if message.chat.type != "private" and not await is_user_in_chat(check_chat_id, target_user.id, bot): 
        return await message.answer(f"Твоя любовь уже сбежала из чата... Как грустно {e('dislike', '💔')}")
    
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)''', (initiator.id, initiator.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)''', (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    db_conn.commit()

    # Harem Marriage Verification
    cursor.execute('SELECT has_harem FROM users WHERE user_id = ?', (initiator.id,))
    init_harem = cursor.fetchone()[0]
    cursor.execute('SELECT has_harem FROM users WHERE user_id = ?', (target_user.id,))
    target_harem = cursor.fetchone()[0]

    init_spouses = get_spouses(initiator.id, cursor)
    target_spouses = get_spouses(target_user.id, cursor)

    if target_user.id in init_spouses:
        return await message.answer("Вы уже состоите в браке друг с другом! 😘")

    if init_harem == 0 and len(init_spouses) >= 1: 
        return await message.answer("У тебя уже есть пара, изменщик! 🤭")
    if target_harem == 0 and len(target_spouses) >= 1: 
        return await message.answer(f"Это сердечко уже занято кем-то другим... {e('dislike', '💔')}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, согласен(на)! 💕", callback_data=f"marry_yes_{initiator.id}_{target_user.id}"),
        InlineKeyboardButton(text="Нет, прости...", callback_data=f"marry_no_{initiator.id}_{target_user.id}")
    ]])
    i_name, t_name = html.escape(initiator.first_name), html.escape(target_user.first_name)
    await message.answer(random.choice([
        f"{get_user_link(initiator.id, i_name)} встает на одно колено перед {get_user_link(target_user.id, t_name)}!\n\nЧто ответишь? {e('heart', '💖')}",
        f"Сердце {get_user_link(initiator.id, i_name)} теперь принадлежит {get_user_link(target_user.id, t_name)}! Примешь эти чувства? 😘"
    ]), reply_markup=kb)

@dp.callback_query(F.data.startswith("marry_"))
async def process_marry_callback(callback: CallbackQuery):
    data = callback.data.split("_")
    action, initiator_id, target_id = data[1], int(data[2]), int(data[3])

    if callback.message.chat.type in ("group", "supergroup") and callback.message.chat.id != ALLOWED_GROUP_ID: return await callback.answer()
    if callback.from_user.id != target_id: return await callback.answer("Тише-тише, это предложение делали не тебе! 😘", show_alert=True)
    if action == "no":
        await callback.message.edit_text(f"Ой... Кажется, кому-то только что разбили сердце {e('dislike', '💔')}")
        return await callback.answer()

    cursor = db_conn.cursor()
    cursor.execute('SELECT has_harem FROM users WHERE user_id = ?', (initiator_id,))
    init_harem = cursor.fetchone()[0]
    cursor.execute('SELECT has_harem FROM users WHERE user_id = ?', (target_id,))
    target_harem = cursor.fetchone()[0]

    init_spouses = get_spouses(initiator_id, cursor)
    target_spouses = get_spouses(target_id, cursor)

    if (init_harem == 0 and len(init_spouses) >= 1) or (target_harem == 0 and len(target_spouses) >= 1):
        await callback.message.edit_text(f"Упс, кто-то из вас уже успел выскочить замуж за другого! {e('dislike', '💔')}")
        return await callback.answer()

    # Save marriage in standard junction table
    u1, u2 = min(initiator_id, target_id), max(initiator_id, target_id)
    cursor.execute('INSERT OR IGNORE INTO marriages (user_one, user_two) VALUES (?, ?)', (u1, u2))
    db_conn.commit()

    cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (initiator_id,))
    row1 = cursor.fetchone()
    name1 = html.escape(row1[0] if row1[0] else row1[1])
    cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (target_id,))
    row2 = cursor.fetchone()
    name2 = html.escape(row2[0] if row2[0] else row2[1])
    
    await callback.message.edit_text(f"Ах, какая пара! Объявляю {get_user_link(initiator_id, name1)} and {get_user_link(target_id, name2)} мужем и женой! Горько! {e('kiss', '💋')}")
    await callback.answer(f"Поздравляю! {e('heart', '💖')}")

@dp.message(flexible_command("divorce", "развод"))
async def cmd_divorce(message: Message):
    cursor = db_conn.cursor()
    spouses = get_spouses(message.from_user.id, cursor)
    if not spouses: 
        return await message.answer("Сладкий, чтобы развестись, нужно сначала кого-нибудь подцепить и жениться! А у тебя пока пусто 😘")
    
    target_divorce_id = None
    if message.reply_to_message:
        target_divorce_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            query = args[1].strip()
            if query.startswith("@"):
                search_username = query.replace("@", "").lower()
                cursor.execute('SELECT user_id FROM users WHERE tg_username = ? OR LOWER(username) = ?', (search_username, search_username))
                user_data = cursor.fetchone()
                if user_data:
                    target_divorce_id = user_data[0]
            elif query.isdigit():
                target_divorce_id = int(query)

    if target_divorce_id:
        if target_divorce_id in spouses:
            u1, u2 = min(message.from_user.id, target_divorce_id), max(message.from_user.id, target_divorce_id)
            cursor.execute("DELETE FROM marriages WHERE user_one = ? AND user_two = ?", (u1, u2))
            db_conn.commit()
            await message.answer(f"Кольца сданы, мосты сожжены. Ты свободен(на) от брака с этим человеком! {e('kiss', '💋')}")
        else:
            await message.answer("Ты не состоишь в браке с этим пользователем! 😘")
    else:
        # Divorce everyone
        cursor.execute('DELETE FROM marriages WHERE user_one = ? OR user_two = ?', (message.from_user.id, message.from_user.id))
        db_conn.commit()
        await message.answer(f"Кольца сданы, мосты сожжены. Ну ничего, ты теперь свободен(на) для новых приключений! {e('kiss', '💋')}")

@dp.message(flexible_command("marriages", "список_браков"))
async def cmd_marriages_list(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT m.user_one, u1.username, u1.custom_nick, m.user_two, u2.username, u2.custom_nick 
        FROM marriages m
        JOIN users u1 ON m.user_one = u1.user_id
        JOIN users u2 ON m.user_two = u2.user_id
    ''')
    rows = cursor.fetchall()
    if not rows: return await message.answer(f"В нашем чате пока нет ни одной парочки. Кто будет первым? {e('kiss', '💋')}")

    text = f"<b>Наши влюбленные голубки:</b>\n\n"
    for i, row in enumerate(rows, 1):
        n1 = html.escape(row[2] if row[2] else row[1])
        n2 = html.escape(row[5] if row[5] else row[4])
        text += f"{i}. {get_user_link(row[0], n1)} {e('like', '❤️')} {get_user_link(row[3], n2)}\n"
    await message.answer(text)

@dp.message(flexible_command("give", "начислить"))
async def admin_give(message: Message, bot: Bot):
    if not await is_admin(message, bot) or not message.reply_to_message: return await message.answer("Ответь на сообщение, кому перевести монетки 😘")
    args = message.text.split()
    if len(args) < 2 or not args[1].lstrip('-').isdigit(): return
    amount = int(args[1])
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)''', (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, target_user.id))
    db_conn.commit()
    await message.answer(f"Дзынь! На счёт {get_user_link(target_user.id, html.escape(target_user.first_name))} капнуло {amount} {CURRENCY}. Купи себе что-нибудь красивое, золотце {e('kiss', '💋')}")

@dp.message(flexible_command("shop", "магазин"))
async def cmd_shop(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT item_id, name, price FROM shop')
    text = f"<b>Магазин Фемиды</b>\nПрисматриваешь обновки? Посмотри, что у меня есть... 💕\n\n"
    for it in cursor.fetchall(): text += f"ID {it[0]} ➜ {html.escape(it[1])} — {hbold(it[2])} {CURRENCY}\n"
    await message.answer(text + f"\nЕсли надумал(а), пиши: <code>!купить [ID]</code>")

@dp.message(flexible_command("buy", "купить"))
async def cmd_buy(message: Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit(): return await message.answer(f"Выбрал(а) что-то интересное? Напиши ID товара после команды, сладкий {e('kiss', '💋')}")
    item_id = int(args[1])
    user_id = message.from_user.id
    cursor = db_conn.cursor()
    item = cursor.execute('SELECT name, price FROM shop WHERE item_id = ?', (item_id,)).fetchone()
    if not item: return await message.answer(f"Милый, я всё обыскала, но такого номера у нас в магазине нет {e('dislike', '💔')}")
    
    res = cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,)).fetchone()
    balance = res[0] if res else 0
    if balance < item[1]: return await message.answer(f"Ой-ой, на твоем балансе маловато монеток ({balance} {CURRENCY}). Нужно еще немного поднакопить! 💕")
    
    # Deduct price
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (item[1], user_id))
    
    # Automatically apply premium activation permissions on purchase
    item_name = item[0]
    if "Гарем" in item_name:
        cursor.execute("UPDATE users SET has_harem = 1 WHERE user_id = ?", (user_id,))
    elif "Ребёнок" in item_name:
        cursor.execute("UPDATE users SET has_child = 1 WHERE user_id = ?", (user_id,))
    elif "Кастом" in item_name:
        cursor.execute("UPDATE users SET has_custom = 1 WHERE user_id = ?", (user_id,))

    db_conn.commit()
    await message.answer(f"Отличный вкус! Ты приобрел(а): {html.escape(item[0])}. Заходи еще, золотце {e('heart', '💖')}")
    await bot.send_message(SUPER_ADMIN_ID, f"Моя дорогая, у нас покупка! {html.escape(message.from_user.full_name)} забрал(а) {html.escape(item[0])}. {e('kiss', '💋')}")

@dp.message(flexible_command("warn", "варн"))
async def cmd_warn(message: Message, bot: Bot):
    if not await is_admin(message, bot) or not message.reply_to_message: return await message.answer(f"Ответь на сообщение хулигана, и я его накажу {e('kiss', '💋')}")
    target_user = message.reply_to_message.from_user
    if not target_user: return
    if target_user.is_bot: return await message.answer("Попытка наказать меня? Как смело... но я неприкосновенна, дорогой 😘")
        
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET warns = warns + 1 WHERE user_id = ?', (target_user.id,))
    warns_count = cursor.execute('SELECT warns FROM users WHERE user_id = ?', (target_user.id,)).fetchone()[0]
    db_conn.commit()
    
    t_name = html.escape(target_user.first_name)
    if warns_count >= 3:
        try:
            await bot.ban_chat_member(message.chat.id, target_user.id)
            await message.answer(f"Три варна, детка. Правила есть правила, мне придется попрощаться с {get_user_link(target_user.id, t_name)}. Было весело! 💋")
            cursor.execute('UPDATE users SET warns = 0 WHERE user_id = ?', (target_user.id,))
            db_conn.commit()
        except: await message.answer("Я бы с радостью выгнала этого хулигана, но вы не дали мне прав администратора! 🥺")
    else:
        await message.answer(f"Ай-ай-ай, {get_user_link(target_user.id, t_name)}, так делать нельзя! Лови предупреждение ({warns_count}/3). Еще парочка, и я покажу тебе на дверь {e('kiss', '💋')}")

@dp.message(flexible_command("unwarn", "снять_варн"))
async def cmd_unwarn(message: Message, bot: Bot):
    if not await is_admin(message, bot) or not message.reply_to_message: return await message.answer(f"Кого будем прощать? Ответь на сообщение этого счастливчика {e('kiss', '💋')}")
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    res = cursor.execute('SELECT warns FROM users WHERE user_id = ?', (target_user.id,)).fetchone()
    current_warns = res[0] if res else 0
    if current_warns <= 0: return await message.answer("У этого ангелочка и так нет предупреждений! Нечего снимать 💕")
        
    cursor.execute('UPDATE users SET warns = warns - 1 WHERE user_id = ?', (target_user.id,))
    db_conn.commit()
    await message.answer(f"Так уж и быть, сегодня я добрая. Сняла одно предупреждение с {get_user_link(target_user.id, html.escape(target_user.first_name))}. Теперь у него/нее {current_warns - 1}/3 варнов. Веди себя хорошо! {e('kiss', '💋')}")

@dp.message(flexible_command("ban", "бан"))
async def cmd_ban(message: Message, bot: Bot):
    if not await is_admin(message, bot) or not message.reply_to_message: return
    target_user = message.reply_to_message.from_user
    if not target_user: return
    try:
        await bot.ban_chat_member(message.chat.id, target_user.id)
        await message.answer(f"Было весело, но ты перешел границы. Прощай, {get_user_link(target_user.id, html.escape(target_user.first_name))} {e('kiss', '💋')}")
    except: await message.answer("Не получилось выгнать... Дайте мне админку, и я всё устрою!")

@dp.message(flexible_command("db_query", "запрос"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db(message: Message):
    if message.chat.type != "private": return await message.answer(f"Дорогая, такие интимные вещи, как работа с базой, лучше обсуждать в личке. Мало ли кто подсмотрит... 😘")
    try:
        q = message.text.split(maxsplit=1)[1]
        cursor = db_conn.cursor()
        cursor.execute(q)
        if q.lower().startswith("select"): await message.answer(f"Вот что я откопала в своих файлах:\n{hcode(str(cursor.fetchall()[:10]))}")
        else:
            db_conn.commit()
            await message.answer(f"Послушно всё исполнила, моя госпожа! Изменено строк: {cursor.rowcount} {e('kiss', '💋')}")
    except Exception as err: await message.answer(f"Ой, кажется в твоем запросе ошибка: {err}. Но ты всё равно умничка! {e('heart', '💖')}")

@dp.message(flexible_command("db_download", "скачать_бд"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db_download(message: Message):
    if message.chat.type != "private": return
    if DB_PATH.exists(): await message.answer_document(FSInputFile(str(DB_PATH)), caption=f"Твоя база, госпожа! 💋")

@dp.message(flexible_command("db_upload", "загрузить_бд"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db_upload(message: Message, bot: Bot):
    if message.chat.type != "private" or not message.reply_to_message or not message.reply_to_message.document: return
    try:
        await bot.download_file((await bot.get_file(message.reply_to_message.document.file_id)).file_path, destination=str(DB_PATH))
        await message.answer("База обновлена! 💖")
    except Exception as err: await message.answer(f"Ошибка: {err}")

@dp.message(flexible_command("list_broadcast", "рассылка_список"), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_list_broadcast(message: Message, bot: Bot):
    if message.chat.type != "private": return await message.answer("Только в ЛС! 💋")
    args = message.text.split()[1:]
    if not args: return await message.answer("Нужен список ID через пробел! 💋")
    
    await message.answer(f"Начинаю рассылку поздравлений ({len(args)} сообщений)... ✨")
    count = 0
    for uid_str in args:
        try:
            uid = int(uid_str.strip())
            n = random.randint(1, 100)
            text = (
                f"- Примите наши поздравления! Вы были включены в первый поток приема, и, "
                f"как и многие другие участники, стали лучшими из лучших! Ваша способность "
                f"имеет номер <b>{n}</b>, и мы с радостью поделимся с вами всей необходимой "
                f"информацией о ней. Не забудьте с ней ознакомиться. Спасибо, что вы с нами! 💋"
            )
            await bot.send_message(uid, text)
            count += 1
            await asyncio.sleep(0.1) 
        except: continue
    await message.answer(f"Готово! Доставлено {count} сообщений. 💋")

@dp.message()
async def handle_everything(message: Message, bot: Bot):
    if not message.text: return

    global admin_combine_state, admin_combine_messages
    if message.chat.type == "private" and message.from_user.id == SUPER_ADMIN_ID:
        if admin_combine_state:
            text_to_add = message.html_text
            if text_to_add and not any((message.text or "").startswith(p) for p in CMD_PREFIXES):
                admin_combine_messages.append(text_to_add)
                return

    if message.chat.type in ("group", "supergroup") and message.chat.id != ALLOWED_GROUP_ID:
        return 

    cursor = db_conn.cursor()
    RP_ACTIONS = {
        "обнять": [
            "крепко обнял(а)", "тепло обнял(а)", "заключил(а) в объятия",
            "укутал(а) в теплый плед и обнял(а)", "нежно обнял(а) со спины",
            "крепко-крепко затискал(а) в объятиях"
        ],
        "поцеловать": [
            "нежно поцеловал(а)", "страстно поцеловал(а)", "поцеловал(а) в носик",
            "заботливо чмокнул(а) в макушку", "оставил(а) легкий поцелуй на щеке",
            "робко поцеловал(а) в лобик"
        ],
        "ударить": [
            "дал(а) леща", "отвесил(а) щелбан", "кинул(а) тапок в",
            "слегка ущипнул(а) за бочок", "в шутку стукнул(а) кулачком по плечу",
            "дал(а) мягкий, но поучительный подзатыльник"
        ],
        "погладить": [
            "погладил(а) по голове", "ласково погладил(а) по щеке",
            "заботливо погладил(а) по плечу", "запустил(а) пальцы в волосы и нежно погладил(а)",
            "успокаивающе погладил(а) по спине"
        ],
        "укусить": [
            "сделал(а) кусь", "слегка укусил(а) за ушко", "любя укусил(а) за пальчик",
            "оставил(а) легкий след от укуса на плече"
        ],
        "щекотать": [
            "защекотал(а) до слез", "напал(а) со внезапной щекоткой на",
            "слегка пощекотал(а) бока", "устроил(а) настоящую пытку щекоткой для"
        ],
        "утешить": [
            "нежно прижал(а) к себе и прошептал(а) слова поддержки для",
            "заботливо вытер(ла) слезки с лица", "подбадривающе похлопал(а) по плечу",
            "тихо шепнул(а) на ушко, что всё будет хорошо для"
        ],
        "успокоить": [
            "нежно прижал(а) к себе и прошептал(а) слова поддержки для",
            "заботливо вытер(ла) слезки с лица", "подбадривающе похлопал(а) по плечу",
            "тихо шепнул(а) на ушко, что всё будет хорошо для"
        ],
        "покормить": [
            "протянул(а) самую вкусную печеньку", "заботливо покормил(а) с ложечки",
            "угостил(а) спелой, сладкой клубникой", "поделился(ась) своей порцией вкусняшек с"
        ]
    }

    text = message.text.strip()
    first_word = text.split()[0].lower() if text else ""
    
    has_prefix = False
    raw_cmd = ""
    for p in CMD_PREFIXES:
        if first_word.startswith(p):
            raw_cmd = first_word[len(p):]
            has_prefix = True
            break
            
    if not has_prefix:
        raw_cmd = first_word

    phrase = None
    if raw_cmd in RP_ACTIONS:
        phrase = random.choice(RP_ACTIONS[raw_cmd])
    else:
        results = cursor.execute('SELECT phrase FROM rp_actions WHERE command = ?', (raw_cmd,)).fetchall()
        if results: 
            phrase = html.escape(random.choice(results)[0])
    
    if phrase:
        target_user = message.reply_to_message.from_user if message.reply_to_message else None
        if not target_user and message.chat.type == "private":
            target_user = await bot.get_me()

        if target_user:
            if target_user.is_bot and target_user.id != bot.id: 
                return await message.answer(f"Твои касания проходят сквозь мои голографические проекции... Прибереги эту нежность для живых людей {e('kiss', '💋')}")
            if target_user.is_bot and target_user.id == bot.id and message.chat.type != "private":
                return await message.answer(f"Твои касания проходят сквозь мои голографические проекции... Прибереги эту нежность для живых людей {e('kiss', '💋')}")
            
            check_chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else ALLOWED_GROUP_ID
            if message.chat.type != "private" and not await is_user_in_chat(check_chat_id, target_user.id, bot): 
                return await message.answer(f"Ой, а его тут уже нет... Попробуй потрогать кого-нибудь другого 😘")
                
            init_res = cursor.execute('SELECT custom_nick FROM users WHERE user_id = ?', (message.from_user.id,)).fetchone()
            init_n = html.escape(init_res[0] if init_res and init_res[0] else message.from_user.first_name)
            
            targ_res = cursor.execute('SELECT custom_nick FROM users WHERE user_id = ?', (target_user.id,)).fetchone()
            targ_n = html.escape(targ_res[0] if targ_res and targ_res[0] else target_user.first_name)
            
            return await message.answer(f"{get_user_link(message.from_user.id, init_n)} {phrase} {get_user_link(target_user.id, targ_n)}.")

    check_time_resets(cursor)
    
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)''', 
                   (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    if message.from_user.username:
        cursor.execute('UPDATE users SET tg_username = ? WHERE user_id = ?', (message.from_user.username.lower(), message.from_user.id))
        
    cursor.execute('SELECT messages_total, balance FROM users WHERE user_id = ?', (message.from_user.id,))
    row_data = cursor.fetchone()
    old_messages = row_data[0] if row_data else 0
    old_balance = row_data[1] if row_data else 0
    
    new_messages = old_messages + 1
    coins_to_add = 0
    if new_messages % 10 == 0:
        coins_to_add = 1
    new_balance = old_balance + coins_to_add
    
    old_rank = get_rank(old_messages)
    new_rank = get_rank(new_messages)
    
    cursor.execute('''UPDATE users SET 
                      messages_total = ?, 
                      balance = ?, 
                      messages_week = messages_week + 1, 
                      messages_day = messages_day + 1, 
                      messages_hour = messages_hour + 1 
                      WHERE user_id = ?''', (new_messages, new_balance, message.from_user.id))
    db_conn.commit()
    
    if old_rank != new_rank:
        user_link = get_user_link(message.from_user.id, message.from_user.first_name)
        phrases = [
            f"👑 Опачки! А кто это у нас тут растет? {user_link}, поздравляю, солнце! Твой ранг повысился с «<b>{old_rank}</b>» до «<b>{new_rank}</b>»! Горжусь тобой {e('kiss', '💋')}",
            f"✨ Ого, вот это уровень! {user_link} переходит на новую ступень правосудия! Твой статус изменился: ты больше не «<b>{old_rank}</b>», теперь твое звание — «<b>{new_rank}</b>»! {e('heart', '💖')}",
            f"🎉 Дзынь-дзынь! Минуточку внимания! {user_link} только что получил(а) новое звание «<b>{new_rank}</b>» (было: «{old_rank}»)! Так держать, золотце! {e('kiss', '💋')}"
        ]
        await message.answer(random.choice(phrases))

async def main():
    dp.shutdown.register(on_shutdown)
    await bot.delete_webhook(drop_pending_updates=True)
    dp.message.middleware(AntiSpamMiddleware())
    
    logging.info("🚀 Бот успешно запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("🔴 Бот остановлен.")