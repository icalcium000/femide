import sys
import subprocess

# --- АВТОМАТИЧЕСКАЯ УСТАНОВКА БИБЛИОТЕК ---
try:
    import aiogram
except ImportError:
    print("Ой, кажется у тебя не хватает aiogram! Сейчас всё скачаю, подожди секундочку 💋...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiogram"])
        print("Всё скачалось! Теперь я готова к работе 💖")
        import aiogram
    except Exception as e:
        print(f"Блин, не получилось скачать автоматически 💔. Пожалуйста, напиши в терминале: pip install aiogram\nОшибка: {e}")
        sys.exit(1)

import asyncio
import sqlite3
import logging
import random
import time
import html
import os
from pathlib import Path
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command as AiogramCommand
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.markdown import hbold, hlink, hcode
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware

# --- КОНФИГУРАЦИЯ ---
BOT_NAME = "Алгоритм порядка и правосудия — ФЕМИДА"
CURRENCY = "EL'coins"

# Берем токен из переменных окружения сервера (Environment Variables)
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")

# Переносим ID в переменные окружения. Если они не заданы, используются значения по умолчанию.
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID") or 1197260250)
ALLOWED_GROUP_ID = int(os.getenv("ALLOWED_GROUP_ID") or -1000000000000)

CMD_PREFIXES = ("/", "!")

# Строгая проверка токена перед инициализацией
if not TOKEN:
    logging.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен бота не обнаружен!")
    logging.critical("Убедитесь, что на сайте хостинга в разделе 'Environment Variables' создана переменная BOT_TOKEN.")
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

def Command(*args, **kwargs):
    kwargs.setdefault('ignore_case', True)
    return AiogramCommand(*args, **kwargs)

logging.basicConfig(level=logging.INFO)

# --- БАЗА ДАННЫХ (SQLITE В ПАПКЕ DATA) ---
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
    
    ensure_column(cursor, 'users', 'custom_nick', "TEXT DEFAULT NULL")
    ensure_column(cursor, 'users', 'balance', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_total', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_week', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_day', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'messages_hour', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'warns', "INTEGER DEFAULT 0")
    ensure_column(cursor, 'users', 'joined_date', "TEXT")
    ensure_column(cursor, 'users', 'description', "TEXT DEFAULT 'Не указано'")
    ensure_column(cursor, 'users', 'rest_status', "TEXT DEFAULT NULL")
    ensure_column(cursor, 'users', 'likes', "TEXT DEFAULT 'Не указано'")
    ensure_column(cursor, 'users', 'dislikes', "TEXT DEFAULT 'Не указано'")
    ensure_column(cursor, 'users', 'characters', "TEXT DEFAULT ''")
    ensure_column(cursor, 'users', 'rewards', "TEXT DEFAULT ''")
    ensure_column(cursor, 'users', 'spouse_id', "INTEGER DEFAULT NULL")
    ensure_column(cursor, 'users', 'clan_id', "INTEGER DEFAULT NULL")
    ensure_column(cursor, 'users', 'custom_photo', "TEXT DEFAULT NULL")

    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS rp_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        command TEXT,
        phrase TEXT
    )''')

    now = int(time.time())
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("reset_hour", ?)', (str(now),))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("reset_day", ?)', (str(now),))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("reset_week", ?)', (str(now),))

    cursor.execute('''CREATE TABLE IF NOT EXISTS shop (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, price INTEGER
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS roulette_names (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )''')
    
    cursor.execute('SELECT COUNT(*) FROM shop')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('INSERT INTO shop (name, price) VALUES (?, ?)', [
            ('Новая местность —', 25), ('Новая способность —', 35), ('Выбор способности своему персонажу (единоразово) —', 75), ('Любой предмет для своего персонажу (единоразово) —', 25)
        ])
    conn.commit()
    return conn

db_conn = init_db()

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- БЕЗОПАСНОЕ ВЫКЛЮЧЕНИЕ ДЛЯ ХОСТИНГА (GRACEFUL SHUTDOWN) ---
async def on_shutdown(bot: Bot):
    logging.info("Внимание: Контейнер выключается. Сохраняю базу данных... 💋")
    db_conn.commit()
    db_conn.close()
    await bot.session.close()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def is_admin(message: Message, bot: Bot):
    if message.from_user.id == SUPER_ADMIN_ID: return True
    if message.chat.type == "private": return True
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

def get_rank(messages):
    if messages < 125: return "Новенький"
    elif messages < 400: return "Интересный собеседник"
    elif messages < 1000: return "Душа компании"
    elif messages < 2000: return "Ветеран наших сердец"
    elif messages < 5000: return "Легенда чата"
    else: return "Мой личный фаворит"

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

# --- АНТИСПАМ СИСТЕМА И ФИЛЬТР ГРУПП ---
class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 5, time_window: int = 7, mute_minutes: int = 30):
        self.limit = limit
        self.time_window = time_window
        self.mute_minutes = mute_minutes
        self.spam_cache = {}

    async def __call__(self, handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]], event: Message, data: Dict[str, Any]) -> Any:
        if not isinstance(event, Message): return await handler(event, data)
        
        # --- ПРОВЕРКА НА РАЗРЕШЕННУЮ ГРУППУ ---
        if event.chat.type in ("group", "supergroup") and event.chat.id != ALLOWED_GROUP_ID:
            return # Игнорируем сообщения из других групп
            
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
                        await event.answer(f"Я бы с удовольствием выгнала этого хулигана, но вы не дали мне прав администратора! Сделайте меня главной, ну пожалуйста 🥺")
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

# --- ПРИВЕТСТВИЯ И ПРОЩАНИЯ ---
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
        ]
        await message.answer(random.choice(phrases))

@dp.message(F.left_chat_member)
async def goodbye_member(message: Message):
    member = message.left_chat_member
    
    # Автоматический развод при выходе из чата
    cursor = db_conn.cursor()
    cursor.execute('SELECT spouse_id FROM users WHERE user_id = ?', (member.id,))
    res = cursor.fetchone()
    if res and res[0]:
        spouse_id = res[0]
        cursor.execute('UPDATE users SET spouse_id = NULL WHERE user_id = ? OR user_id = ?', (member.id, spouse_id))
        db_conn.commit()

    phrases = [
        f"Ну вот... {member.first_name} ушел(ла), а я только начала строить на нас планы {e('dislike', '💔')}",
        f"Без {member.first_name} чат стал чуточку холоднее... Возвращайся скорее! 🥺",
        f"Иди покоряй мир, {member.first_name}, но помни, что я буду скучать... {e('kiss', '💋')}",
        f"Как?! {member.first_name} сбегает в самом разгаре веселья? Это жестоко... {e('dislike', '💔')}",
        f"Соединение с {member.first_name} разорвано. Мое механическое сердце разбито... {e('dislike', '💔')}",
    ]
    await message.answer(random.choice(phrases))

# --- СИСТЕМНЫЕ ИНФО-КОМАНДЫ ---
@dp.message(Command("help", "помощь", prefix=CMD_PREFIXES))
async def cmd_help(message: Message):
    text = (
        f"Смотри, что я умею делать ради тебя, милашка:\n\n"
        f"<b>Твой профиль:</b> <code>!профиль</code>, <code>!ник</code> [текст], <code>!описание</code> [текст], <code>!рест</code> [причина], <code>!анрест</code>, <code>!люблю</code> [текст], <code>!нелюблю</code> [текст], <code>!добавить_перса</code> [имя] | [ссылка], <code>!удалить_перса</code> [имя/все]\n"
        f"<b>Твоя внешность:</b> <code>!уст_фото</code>, <code>!удалить_фото</code>\n"
        f"<b>Кошелек:</b> <code>!магазин</code>, <code>!купить</code> [id]\n"
        f"<b>Дела сердечные:</b> <code>!брак</code>, <code>!развод</code>, <code>!список_браков</code>, <code>!шип</code>, <code>!враги</code>\n"
        f"<b>Прикосновения:</b> Любая РП команда через ! (например <code>!обнять</code>, <code>!поцеловать</code>)\n"
        f"<b>Игры:</b> <code>!крутка</code> [от] [до], <code>!крутить</code> (рулетка имен), <code>!список_имен</code>\n"
        f"<b>Важное:</b> <code>!правила</code>, <code>!ссылки</code>, <code>!местность</code>\n"
        f"<b>Кто тут лучший:</b> <code>!топ</code>, <code>!топнеделя</code>, <code>!топдень</code>, <code>!топчас</code>\n"
    )
    await message.answer(text)

@dp.message(Command("helpmelak", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_helpmelak(message: Message):
    text = (
        f"Секретное меню для моего Создателя 🤫\n\n"
        f"Используй <code>!запрос [SQL]</code> чтобы покопаться в моей базе данных.\n"
        f"Или <code>!скачать_бд</code> и <code>!загрузить_бд</code> для ручной правки.\n\n"
        f"<code>!рассылка_список [ID ID ID]</code> — рассылка по списку (можно дублировать ID). 💋\n\n"
        f"<i>Рассылки:</i>\n"
        f"Напиши <code>!уст_основной_чат</code> в нужной группе.\n"
        f"А потом пиши мне в личку: <code>!утро</code>, <code>!ночь</code> или <code>!сказать [текст]</code>.\n\n"
        f"<i>Установка инфы:</i>\n"
        f"<code>!уст_ссылки</code> [текст], <code>!уст_правила</code> [текст], <code>!уст_местность</code> [текст]\n\n"
        f"<i>Склейка сообщений:</i>\n"
        f"В личке напиши <code>!объед_нач</code>, скинь нужные сообщения, а затем <code>!объед_кон</code>.\n"
    )
    await message.answer(text)

@dp.message(Command("loc", "местность", prefix=CMD_PREFIXES))
async def cmd_loc(message: Message):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'location'")
    res = cursor.fetchone()
    loc = res[0] if res else "Местность еще не установлена, мы парим в пустоте..."
    await message.answer(f"<b>Где мы находимся:</b>\n{loc}")

@dp.message(Command("rules", "правила", prefix=CMD_PREFIXES))
async def cmd_rules(message: Message):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'rules'")
    res = cursor.fetchone()
    rules = res[0] if res else "Правила еще не написаны. Полная анархия! 💋"
    await message.answer(f"<b>Наши правила:</b>\n{rules}")

@dp.message(Command("links", "ссылки", prefix=CMD_PREFIXES))
async def cmd_links(message: Message):
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'links'")
    res = cursor.fetchone()
    links = res[0] if res else "У меня пока нет для тебя ссылочек, милый."
    await message.answer(f"<b>Полезные ссылки:</b>\n{links}")

# --- НАСТРОЙКИ АДМИНА ---
async def set_setting(message: Message, key: str, bot: Bot):
    if not await is_admin(message, bot): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer(f"А текст-то где, милый? Напиши, что именно нужно сохранить {e('kiss', '💋')}")
    cursor = db_conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, args[1]))
    db_conn.commit()
    await message.answer(f"Всё запомнила в лучшем виде, золотце! {e('kiss', '💋')}")

@dp.message(Command("setloc", "уст_местность", prefix=CMD_PREFIXES))
async def set_loc(message: Message, bot: Bot): await set_setting(message, "location", bot)
@dp.message(Command("setrules", "уст_правила", prefix=CMD_PREFIXES))
async def set_rules(message: Message, bot: Bot): await set_setting(message, "rules", bot)
@dp.message(Command("setlinks", "уст_ссылки", prefix=CMD_PREFIXES))
async def set_links(message: Message, bot: Bot): await set_setting(message, "links", bot)

# --- ГЛОБАЛЬНЫЕ РАССЫЛКИ (УТРО И НОЧЬ И СООБЩЕНИЯ ОТ БОТА) ---
@dp.message(Command("setmain", "уст_основной_чат", prefix=CMD_PREFIXES))
async def cmd_setmain(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type == "private":
        return await message.answer("Сладкий, эту команду нужно писать прямо в группе, а не мне на ушко.")
    
    cursor = db_conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('main_chat_id', ?)", (str(message.chat.id),))
    db_conn.commit()
    await message.answer(f"Договорились! Теперь это мой любимый чат для рассылок. {e('heart', '💖')}")

@dp.message(Command("say", "сказать", prefix=CMD_PREFIXES))
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

@dp.message(Command("morning", "утро", prefix=CMD_PREFIXES))
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
        f"Доброе утро! Давайте договоримся: вы просыпаетесь, а я весь день заставляю вас улыбаться. Идет?) {e('kiss', '💋')}"
    ]
    try:
        await bot.send_message(chat_id, random.choice(phrases))
        await message.answer(f"Утреннее пожелание отправлено! {e('kiss', '💋')}")
    except Exception as err:
        await message.answer(f"Упс, ошибка: {err}")

@dp.message(Command("night", "ночь", prefix=CMD_PREFIXES))
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
        f"Сладких снов! Не скучайте без меня слишком сильно до утра!! {e('heart', '💖')}"
    ]
    try:
        await bot.send_message(chat_id, random.choice(phrases))
        await message.answer(f"Сладкие сны отправлены! {e('kiss', '💋')}")
    except Exception as err:
        await message.answer(f"Упс, ошибка: {err}")

@dp.message(Command("poll", "голос", prefix=CMD_PREFIXES))
async def cmd_poll(message: Message, bot: Bot):
    if message.from_user.id != SUPER_ADMIN_ID: return
    if message.chat.type != "private": return
        
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Нужен текст, милый!\nФормат: <code>!голос</code> Ваш вопрос?: Ответ 1, Ответ 2")
        
    text = args[1]
    if ":" not in text: return await message.answer("Ты забыл двоеточие `:`. Оно нужно, чтобы отделить вопрос от ответов, золотце.")
        
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

# --- СКЛЕЙКА СООБЩЕНИЙ В ЛС ---
@dp.message(Command("combine_start", "объед_нач", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_combine_start(message: Message):
    global admin_combine_state, admin_combine_messages
    if message.chat.type != "private": return
    admin_combine_state = True
    admin_combine_messages = []
    await message.answer(f"Режим склейки активирован, сладкий! Отправляй мне свои сообщения по кусочкам. Как закончишь, шепни <code>!объед_кон</code> {e('kiss', '💋')}")

@dp.message(Command("combine_end", "объед_кон", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_combine_end(message: Message):
    global admin_combine_state, admin_combine_messages
    if message.chat.type != "private": return
    
    if not admin_combine_state:
        return await message.answer(f"Но мы ведь и не начинали ничего объединять... Напиши сначала <code>!объед_нач</code> 😘")
        
    admin_combine_state = False
    
    if not admin_combine_messages:
        return await message.answer("Ты не прислал(а) ни одного сообщения! Мне нечего объединять 🤷‍♀️")
        
    combined_text = "\n".join(admin_combine_messages)
    
    try:
        await message.answer(f"<b>Готово, золотце! Вот твой цельный текст:</b>\n\n{combined_text}")
    except Exception as err:
        await message.answer(f"Ой, текст получился слишком огромным или в нем сломалось форматирование: {err}")
        
    admin_combine_messages = []

@dp.message(F.chat.type == "private", F.from_user.id == SUPER_ADMIN_ID)
async def handle_private_messages(message: Message):
    global admin_combine_state, admin_combine_messages
    if admin_combine_state:
        text_to_add = message.html_text
        if text_to_add:
            raw_text = message.text or message.caption or ""
            if any(raw_text.startswith(p) for p in CMD_PREFIXES):
                return
            admin_combine_messages.append(text_to_add)

# --- ПРОФИЛЬ И КАСТОМИЗАЦИЯ ---
@dp.message(Command("profile", "профиль", prefix=CMD_PREFIXES))
async def show_profile(message: Message, bot: Bot):
    target_user = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if not target_user: return
        
    if target_user.is_bot:
        return await message.answer("Я всего лишь системный алгоритм, глупышка, у меня не может быть профиля! Но мне приятно твое внимание 😘")
    
    if message.reply_to_message and target_user.id != message.from_user.id:
        if not await is_user_in_chat(message.chat.id, target_user.id, bot):
            return await message.answer(f"Этого человека сейчас нет с нами в чате, попробуй позже( {e('dislike', '💔')}")
            
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', 
                   (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    db_conn.commit()
    
    cursor.execute('''SELECT custom_nick, messages_total, joined_date, warns, balance, 
                      characters, rewards, description, likes, dislikes, spouse_id, clan_id, custom_photo, rest_status 
                      FROM users WHERE user_id = ?''', (target_user.id,))
    data = cursor.fetchone()
    
    if not data:
        return await message.answer("Ой, а я тебя пока совсем не знаю... Напиши хоть словечко в чат, чтобы я могла завести на тебя досье! 👀")
    
    nick = html.escape(data[0] if data[0] else target_user.first_name)
    rank = get_rank(data[1])
    
    spouse_text = f"{e('dislike', '💔')} В активном поиске"
    if data[10]:
        cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (data[10],))
        sp_res = cursor.fetchone()
        sp_nick = html.escape(sp_res[0] if sp_res and sp_res[0] else (sp_res[1] if sp_res else "Партнер"))
        spouse_text = f"{e('like', '❤️')} Сердце отдано {get_user_link(data[10], sp_nick)}"

    custom_photo = data[12]
    
    safe_desc = html.escape(data[7]) if data[7] else "Тайна, покрытая мраком"
    safe_rest = html.escape(data[13]) if data[13] else "Активен"
    safe_likes = html.escape(data[8]) if data[8] else "Секрет"
    safe_dislikes = html.escape(data[9]) if data[9] else "Секрет"
    
    profile_text = (
        f"<b>Досье на:</b> {get_user_link(target_user.id, nick)}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Статус:</b> {rank}\n"
        f"<b>Наболтал(а):</b> {data[1]} сообщ.\n"
        f"<b>С нами с:</b> {data[2]}\n"
        f"<b>Косяки:</b> {data[3]}/3\n"
        f"<b>В кармане:</b> {data[4]} {CURRENCY}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>О себе:</b> {safe_desc}\n"
        f"<b>Рест:</b> {safe_rest}\n"
        f"{e('like', '❤️')} <b>Обожает:</b> {safe_likes}\n"
        f"{e('dislike', '💔')} <b>Терпеть не может:</b> {safe_dislikes}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{spouse_text}\n"
    )
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
            photos = await bot.get_user_profile_photos(target_user.id, limit=1)
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
            await message.answer("Ой, ошибочка вышла! Telegram не пропускает текст. Проверь ID премиум-эмодзи в настройках, возможно он неверный.")
        except: pass

@dp.message(Command("setphoto", "уст_фото", prefix=CMD_PREFIXES))
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
    await message.answer(f"Ммм, какая шикарная карточка! Теперь твой профиль идеален {e('kiss', '💋')}")

@dp.message(Command("delphoto", "удалить_фото", prefix=CMD_PREFIXES))
async def cmd_delphoto(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET custom_photo = NULL WHERE user_id = ?', (message.from_user.id,))
    db_conn.commit()
    await message.answer("Убрала фотку! Хотя твоя обычная аватарка мне тоже очень нравится 😘")

async def update_user_field(message: Message, field: str):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Ну же, не стесняйся! Напиши текст после команды, чтобы я его запомнила 💕")
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute(f'UPDATE users SET {field} = ? WHERE user_id = ?', (args[1], message.from_user.id))
    db_conn.commit()
    await message.answer(f"Записала всё в твое личное дело, милашка! {e('kiss', '💋')}")

@dp.message(Command("setnick", "ник", prefix=CMD_PREFIXES))
async def cmd_setnick(message: Message): await update_user_field(message, "custom_nick")
@dp.message(Command("setdesc", "описание", prefix=CMD_PREFIXES))
async def cmd_setdesc(message: Message): await update_user_field(message, "description")
@dp.message(Command("setlikes", "люблю", prefix=CMD_PREFIXES))
async def cmd_setlikes(message: Message): await update_user_field(message, "likes")
@dp.message(Command("setdislikes", "нелюблю", prefix=CMD_PREFIXES))
async def cmd_setdislikes(message: Message): await update_user_field(message, "dislikes")

@dp.message(Command("setrest", "рест", prefix=CMD_PREFIXES))
async def cmd_setrest(message: Message):
    args = message.text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else "Отдыхает"
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('UPDATE users SET rest_status = ? WHERE user_id = ?', (reason, message.from_user.id))
    db_conn.commit()
    await message.answer(f"Записала тебя в рест. Отдыхай, золотце! {e('kiss', '💋')}")

@dp.message(Command("unrest", "анрест", prefix=CMD_PREFIXES))
async def cmd_unrest(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET rest_status = NULL WHERE user_id = ?', (message.from_user.id,))
    db_conn.commit()
    await message.answer(f"С возвращением! Я скучала {e('heart', '💖')}")

@dp.message(Command("addchar", "добавить_перса", prefix=CMD_PREFIXES))
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
    await message.answer("Готово! Персонаж успешно добавлен в досье.")

@dp.message(Command("delchar", "удалить_перса", prefix=CMD_PREFIXES))
async def del_char(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return await message.answer("Малыш, ответь этой командой на сообщение пользователя, чтобы я поняла, кого мы чистим. 😘")
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2: 
        return await message.answer("Укажи имя персонажа для удаления или напиши 'все', чтобы очистить список полностью.")
    
    char_to_remove = args[1].strip()
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT characters FROM users WHERE user_id = ?', (target_user.id,))
    res = cursor.fetchone()
    current_chars = res[0] if res and res[0] else ""
    
    if not current_chars:
        return await message.answer("Да у него и так список пуст, милый! Нечего удалять.")
        
    if char_to_remove.lower() in ["все", "all"]:
        cursor.execute("UPDATE users SET characters = '' WHERE user_id = ?", (target_user.id,))
        db_conn.commit()
        return await message.answer(f"Очистила список под ноль! Начинаем с чистого листа {e('kiss', '💋')}")
        
    chars_list = [c.strip() for c in current_chars.split(',') if c.strip()]
    new_chars_list = [c for c in chars_list if char_to_remove.lower() not in c.lower()]
    
    if len(chars_list) == len(new_chars_list):
        return await message.answer("Я не нашла такого персонажа в списке...")
        
    final_chars = ", ".join(new_chars_list)
    cursor.execute('UPDATE users SET characters = ? WHERE user_id = ?', (final_chars, target_user.id))
    db_conn.commit()
    
    await message.answer("Персонаж успешно вычеркнут из профиля.")

@dp.message(Command("addreward", "награда", prefix=CMD_PREFIXES))
async def add_reward(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return
    
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute("UPDATE users SET rewards = COALESCE(rewards, '') || ? || ', ' WHERE user_id = ?", (args[1], target_user.id))
    db_conn.commit()
    
    phrases = [
        f"Официально вручаю тебе эту награду, ты заслужил(а), золотце! {e('kiss', '💋')}",
        f"Присваиваю тебе этот статус. Он тебе очень к лицу)) 😘",
        f"Эта награда единогласно (мной) присуждается тебе! {e('heart', '💖')}"
    ]
    await message.answer(random.choice(phrases))

# --- ТОПЫ АКТИВНОСТИ ---
async def show_top(message: Message, column: str, title: str):
    cursor = db_conn.cursor()
    cursor.execute(f'SELECT user_id, username, custom_nick, {column} FROM users ORDER BY {column} DESC LIMIT 10')
    rows = cursor.fetchall()
    
    has_entries = False
    text = f"<b>{title}:</b>\n\n"
    
    rank = 1
    for row in rows:
        if row[3] == 0: continue
        has_entries = True
        name = html.escape(row[2] if row[2] else row[1])
        text += f"{rank}. {get_user_link(row[0], name)} — {row[3]} сообщ.\n"
        rank += 1
        
    if not has_entries:
        return await message.answer(f"Тут пока совсем пусто... Будь первым, напиши мне что-нибудь ласковое! {e('kiss', '💋')}")
        
    await message.answer(text)

@dp.message(Command("top", "топ", "топнеделя", "топдень", "топчас", "top_week", "top_day", "top_hour", prefix=CMD_PREFIXES))
async def cmd_top(message: Message):
    text = message.text.lower().replace("_", "")
    if "недел" in text or "week" in text: await show_top(message, "messages_week", "Топ за неделю")
    elif "ден" in text or "day" in text: await show_top(message, "messages_day", "Топ за день")
    elif "час" in text or "hour" in text: await show_top(message, "messages_hour", "Топ за час")
    else: await show_top(message, "messages_total", "Топ за всё время")

# --- ОТМЕТИТЬ ВСЕХ ---
@dp.message(Command("mention_all", "отм", prefix=CMD_PREFIXES))
async def mention_all(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if "всех" not in message.text.lower(): return
    cursor = db_conn.cursor()
    
    # ПРОВЕРКА: Упоминаем только тех, кто НЕ В РЕСТЕ (rest_status IS NULL)
    cursor.execute('SELECT user_id, username FROM users WHERE rest_status IS NULL LIMIT 40')
    rows = cursor.fetchall()
    text = "<b>Общий сбор! Минуточку внимания!</b>\n"
    for row in rows: text += f'<a href="tg://user?id={row[0]}">‌</a>'
    await message.answer(text + f"\nПросто хотела сказать, что вы все классные. Продолжайте в том же духе! {e('heart', '💖')}")

# --- ИГРЫ И РАНДОМ ---
@dp.message(Command("random", "рандом", "крутка", prefix=CMD_PREFIXES))
async def cmd_random(message: Message):
    args = message.text.split()
    if len(args) == 3 and args[1].isdigit() and args[2].isdigit():
        n, m = int(args[1]), int(args[2])
        if n > m: n, m = m, n
        res = random.randint(n, m)
        await message.answer(f"Я выбрала для тебя число, сладкий: <b>{res}</b> {e('kiss', '💋')}")
    else:
        await message.answer("Просто напиши: !крутка [от] [до], и я выдам тебе число.")

@dp.message(Command("ship", "шип", prefix=CMD_PREFIXES))
async def cmd_ship(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT user_id, username, custom_nick FROM users ORDER BY RANDOM() LIMIT 2')
    users = cursor.fetchall()
    if len(users) < 2: return
    n1 = html.escape(users[0][2] if users[0][2] else users[0][1])
    n2 = html.escape(users[1][2] if users[1][2] else users[1][1])
    
    phrases = [
        f"Уф, кажется между {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)} летят искры! Вы только посмотрите на них... {e('heart', '💖')}",
        f"Я тут проанализировала совместимость, и идеальная пара — это {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)}! Совет да любовь 😘",
    ]
    await message.answer(random.choice(phrases))

@dp.message(Command("enemies", "враги", prefix=CMD_PREFIXES))
async def cmd_enemies(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT user_id, username, custom_nick FROM users ORDER BY RANDOM() LIMIT 2')
    users = cursor.fetchall()
    if len(users) < 2: return
    n1 = html.escape(users[0][2] if users[0][2] else users[0][1])
    n2 = html.escape(users[1][2] if users[1][2] else users[1][1])
    
    phrases = [
        f"Ой-ой, кажется {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)} сегодня явно не в ладах друг с другом... {e('dislike', '💔')}",
        f"Намечается драка между {get_user_link(users[0][0], n1)} и {get_user_link(users[1][0], n2)}! Я уже запаслась попкорном) 😘"
    ]
    await message.answer(random.choice(phrases))

@dp.message(Command("add_name", "добавить_имя", prefix=CMD_PREFIXES))
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
    except Exception: 
        await message.answer(f"Не волнуйся, я уже добавила это имя раньше! 😉")

@dp.message(Command("del_name", "удалить_имя", prefix=CMD_PREFIXES))
async def cmd_del_name(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer("Какое имя вычеркиваем, солнце?")
    name = args[1].strip()
    cursor = db_conn.cursor()
    cursor.execute('DELETE FROM roulette_names WHERE name = ?', (name,))
    db_conn.commit()
    await message.answer(f"Без проблем, вычеркнула «{html.escape(name)}».")

@dp.message(Command("names_list", "список_имен", prefix=CMD_PREFIXES))
async def cmd_names_list(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT name FROM roulette_names')
    rows = cursor.fetchall()
    if not rows: return await message.answer("Тут пока пусто, сладенький.")
    res = f"<b>Кого мы сегодня крутим:</b>\n\n"
    for i, row in enumerate(rows, 1): res += f"{i}. {html.escape(row[0])}\n"
    await message.answer(res)

@dp.message(Command("spin_names", "крутить", prefix=CMD_PREFIXES))
async def cmd_spin_names(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT name FROM roulette_names')
    rows = cursor.fetchall()
    if not rows: return await message.answer("Барабан пуст, милый. Добавь туда имена!")
    
    m = await message.answer(random.choice([f"Так-так, посмотрим, на кого покажет стрелочка... {e('kiss', '💋')}", "Сейчас я выберу самого-самого... 😘"]))
    await asyncio.sleep(1.5)
    winner = html.escape(random.choice(rows)[0])
    await m.edit_text(f"Я выбрала: {hbold(winner)}! {e('heart', '💖')}")

# --- БРАКИ ---
@dp.message(Command("marry", "брак", prefix=CMD_PREFIXES))
async def cmd_marry(message: Message, bot: Bot):
    if not message.reply_to_message: return await message.answer(f"Нужно выбрать, кому делать предложение, радость моя! Ответь на сообщение своей половинки {e('heart', '💖')}")
    target_user = message.reply_to_message.from_user
    if not target_user: return
    initiator = message.from_user
    
    if target_user.id == initiator.id: return await message.answer("Любить себя — это прекрасно, но давай найдем тебе кого-то еще? 😘")
    if target_user.is_bot: return await message.answer(f"Оу... мне безумно приятно, но я состою из кода и алгоритмов. Найди себе кого-нибудь из плоти и крови, милый {e('dislike', '💔')}")
    if not await is_user_in_chat(message.chat.id, target_user.id, bot): return await message.answer(f"Твоя любовь уже сбежала из чата... Как грустно {e('dislike', '💔')}")
    
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (initiator.id, initiator.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    db_conn.commit()

    cursor.execute('SELECT spouse_id FROM users WHERE user_id = ?', (initiator.id,))
    if cursor.fetchone()[0]: return await message.answer("У тебя уже есть пара, изменщик! 🤭")
    cursor.execute('SELECT spouse_id FROM users WHERE user_id = ?', (target_user.id,))
    if cursor.fetchone()[0]: return await message.answer(f"Это сердечко уже занято кем-то другим... {e('dislike', '💔')}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, согласен(на)! 💕", callback_data=f"marry_yes_{initiator.id}_{target_user.id}"),
        InlineKeyboardButton(text="Нет, прости...", callback_data=f"marry_no_{initiator.id}_{target_user.id}")
    ]])
    
    i_name = html.escape(initiator.first_name)
    t_name = html.escape(target_user.first_name)
    phrases = [
        f"{get_user_link(initiator.id, i_name)} встает на одно колено перед {get_user_link(target_user.id, t_name)}!\n\nЧто ответишь? {e('heart', '💖')}",
        f"Сердце {get_user_link(initiator.id, i_name)} теперь принадлежит {get_user_link(target_user.id, t_name)}! Примешь эти чувства? 😘"
    ]
    await message.answer(random.choice(phrases), reply_markup=kb)

@dp.callback_query(F.data.startswith("marry_"))
async def process_marry_callback(callback: CallbackQuery):
    data = callback.data.split("_")
    action, initiator_id, target_id = data[1], int(data[2]), int(data[3])

    if callback.message.chat.type in ("group", "supergroup") and callback.message.chat.id != ALLOWED_GROUP_ID:
        return await callback.answer()

    if callback.from_user.id != target_id: return await callback.answer("Тише-тише, это предложение делали не тебе! 😘", show_alert=True)
    if action == "no":
        await callback.message.edit_text(f"Ой... Кажется, кому-то только что разбили сердце {e('dislike', '💔')}")
        return await callback.answer()

    cursor = db_conn.cursor()
    cursor.execute('SELECT spouse_id FROM users WHERE user_id = ?', (initiator_id,))
    res1 = cursor.fetchone()
    cursor.execute('SELECT spouse_id FROM users WHERE user_id = ?', (target_id,))
    res2 = cursor.fetchone()

    if (res1 and res1[0]) or (res2 and res2[0]):
        await callback.message.edit_text(f"Упс, кто-то из вас уже успел выскочить замуж за другого! {e('dislike', '💔')}")
        return await callback.answer()

    cursor.execute('UPDATE users SET spouse_id = ? WHERE user_id = ?', (target_id, initiator_id))
    cursor.execute('UPDATE users SET spouse_id = ? WHERE user_id = ?', (initiator_id, target_id))
    db_conn.commit()

    cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (initiator_id,))
    row1 = cursor.fetchone()
    name1 = html.escape(row1[0] if row1[0] else row1[1])

    cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (target_id,))
    row2 = cursor.fetchone()
    name2 = html.escape(row2[0] if row2[0] else row2[1])
    
    await callback.message.edit_text(f"Ах, какая пара! Объявляю {get_user_link(initiator_id, name1)} и {get_user_link(target_id, name2)} мужем и женой! Горько! {e('kiss', '💋')}")
    await callback.answer(f"Поздравляю! {e('heart', '💖')}")

@dp.message(Command("divorce", "развод", prefix=CMD_PREFIXES))
async def cmd_divorce(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT spouse_id FROM users WHERE user_id = ?', (message.from_user.id,))
    res = cursor.fetchone()
    if not res or not res[0]: return await message.answer("Сладкий, чтобы развестись, нужно сначала кого-нибудь подцепить и жениться! А у тебя пока пусто 😘")
    cursor.execute('UPDATE users SET spouse_id = NULL WHERE user_id = ? OR user_id = ?', (message.from_user.id, res[0]))
    db_conn.commit()
    await message.answer(f"Кольца сданы, мосты сожжены. Ну ничего, ты теперь свободен(на) для новых приключений! {e('kiss', '💋')}")

@dp.message(Command("marriages", "список_браков", prefix=CMD_PREFIXES))
async def cmd_marriages_list(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT u1.user_id, u1.username, u1.custom_nick, u2.user_id, u2.username, u2.custom_nick FROM users u1 JOIN users u2 ON u1.spouse_id = u2.user_id WHERE u1.user_id < u2.user_id')
    rows = cursor.fetchall()
    if not rows: return await message.answer(f"В нашем чате пока нет ни одной парочки. Кто будет первым? {e('kiss', '💋')}")

    text = f"<b>Наши влюбленные голубки:</b>\n\n"
    for i, row in enumerate(rows, 1):
        n1 = html.escape(row[2] if row[2] else row[1])
        n2 = html.escape(row[5] if row[5] else row[4])
        text += f"{i}. {get_user_link(row[0], n1)} {e('like', '❤️')} {get_user_link(row[3], n2)}\n"
    await message.answer(text)

# --- ЭКОНОМИКА И МАГАЗИН ---
@dp.message(Command("give", "начислить", prefix=CMD_PREFIXES))
async def admin_give(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return await message.answer("Какой ты щедрый! Только покажи мне пальчиком (ответь на сообщение), кому перевести монетки 😘")
    args = message.text.split()
    if len(args) < 2 or not args[1].lstrip('-').isdigit(): return
    amount = int(args[1])
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, target_user.id))
    db_conn.commit()
    
    t_name = html.escape(target_user.first_name)
    await message.answer(f"Дзынь! На счёт {get_user_link(target_user.id, t_name)} капнуло {amount} {CURRENCY}. Купи себе что-нибудь красивое, золотце {e('kiss', '💋')}")

@dp.message(Command("shop", "магазин", prefix=CMD_PREFIXES))
async def cmd_shop(message: Message):
    cursor = db_conn.cursor()
    cursor.execute('SELECT item_id, name, price FROM shop')
    items = cursor.fetchall()
    text = f"<b>Бутик Фемиды</b>\nПрисматриваешь обновки? Посмотри, что у меня есть... 💕\n\n"
    for it in items: text += f"ID {it[0]} ➜ {html.escape(it[1])} — {hbold(it[2])} {CURRENCY}\n"
    text += f"\nЕсли надумал(а), пиши: <code>!купить [ID]</code>"
    await message.answer(text)

@dp.message(Command("buy", "купить", prefix=CMD_PREFIXES))
async def cmd_buy(message: Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit(): return await message.answer(f"Выбрал(а) что-то интересное? Напиши ID товара после команды, сладкий {e('kiss', '💋')}")
    item_id = int(args[1])
    user_id = message.from_user.id
    cursor = db_conn.cursor()
    cursor.execute('SELECT name, price FROM shop WHERE item_id = ?', (item_id,))
    item = cursor.fetchone()
    if not item: return await message.answer(f"Милый, я всё обыскала, но такого номера у нас в магазине нет {e('dislike', '💔')}")
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    balance = res[0] if res else 0
    if balance < item[1]: return await message.answer(f"Ой-ой, на твоем балансе маловато монеток ({balance} {CURRENCY}). Нужно еще немного поднакопить! 💕")
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (item[1], user_id))
    db_conn.commit()
    
    await message.answer(f"Отличный вкус! Ты приобрел(а): {html.escape(item[0])}. Заходи еще, золотце {e('heart', '💖')}")
    await bot.send_message(SUPER_ADMIN_ID, f"Моя дорогая, у нас покупка! {html.escape(message.from_user.full_name)} забрал(а) {html.escape(item[0])}. {e('kiss', '💋')}")

# --- МОДЕРАЦИЯ ---
@dp.message(Command("warn", "варн", prefix=CMD_PREFIXES))
async def cmd_warn(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return await message.answer(f"Кто тут у нас плохо себя ведет? Ответь на сообщение хулигана, и я его накажу {e('kiss', '💋')}")
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    if target_user.is_bot:
        return await message.answer("Попытка наказать меня? Как смело... но я неприкосновенна, дорогой 😘")
        
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET warns = warns + 1 WHERE user_id = ?', (target_user.id,))
    cursor.execute('SELECT warns FROM users WHERE user_id = ?', (target_user.id,))
    warns = cursor.fetchone()
    warns_count = warns[0] if warns else 1
    db_conn.commit()
    
    t_name = html.escape(target_user.first_name)
    if warns_count >= 3:
        try:
            await bot.ban_chat_member(message.chat.id, target_user.id)
            await message.answer(f"Три варна, детка. Правила есть правила, мне придется попрощаться с {get_user_link(target_user.id, t_name)}. Было весело! 💋")
            cursor.execute('UPDATE users SET warns = 0 WHERE user_id = ?', (target_user.id,))
            db_conn.commit()
        except: await message.answer(f"Я бы с радостью выгнала этого хулигана, но вы не дали мне прав администратора! 🥺")
    else:
        await message.answer(f"Ай-ай-ай, {get_user_link(target_user.id, t_name)}, так делать нельзя! Лови предупреждение ({warns_count}/3). Еще парочка, и я покажу тебе на дверь {e('kiss', '💋')}")

@dp.message(Command("unwarn", "снять_варн", prefix=CMD_PREFIXES))
async def cmd_unwarn(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return await message.answer(f"Кого будем прощать? Ответь на сообщение этого счастливчика {e('kiss', '💋')}")
    target_user = message.reply_to_message.from_user
    if not target_user: return
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT warns FROM users WHERE user_id = ?', (target_user.id,))
    res = cursor.fetchone()
    current_warns = res[0] if res else 0
    
    if current_warns <= 0:
        return await message.answer("У этого ангелочка и так нет предупреждений! Нечего снимать 💕")
        
    cursor.execute('UPDATE users SET warns = warns - 1 WHERE user_id = ?', (target_user.id,))
    db_conn.commit()
    
    t_name = html.escape(target_user.first_name)
    await message.answer(f"Так уж и быть, сегодня я добрая. Сняла одно предупреждение с {get_user_link(target_user.id, t_name)}. Теперь у него/нее {current_warns - 1}/3 варнов. Веди себя хорошо! {e('kiss', '💋')}")

@dp.message(Command("ban", "бан", prefix=CMD_PREFIXES))
async def cmd_ban(message: Message, bot: Bot):
    if not await is_admin(message, bot): return
    if not message.reply_to_message: return
    target_user = message.reply_to_message.from_user
    if not target_user: return
    try:
        await bot.ban_chat_member(message.chat.id, target_user.id)
        t_name = html.escape(target_user.first_name)
        await message.answer(f"Было весело, но ты перешел границы. Прощай, {get_user_link(target_user.id, t_name)} {e('kiss', '💋')}")
    except: await message.answer("Не получилось выгнать... Дайте мне админку, и я всё устрою!")

# --- СУПЕР-АДМИН БД И ИНСТРУМЕНТЫ (в ЛС) ---
@dp.message(Command("db_query", "запрос", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db(message: Message):
    if message.chat.type != "private":
        return await message.answer(f"Дорогая, такие интимные вещи, как работа с базой, лучше обсуждать в личке. Мало ли кто подсмотрит... 😘")
    try:
        q = message.text.split(maxsplit=1)[1]
        cursor = db_conn.cursor()
        cursor.execute(q)
        if q.lower().startswith("select"):
            await message.answer(f"Вот что я откопала в своих файлах:\n{hcode(str(cursor.fetchall()[:10]))}")
        else:
            db_conn.commit()
            await message.answer(f"Послушно всё исполнила, моя госпожа! Изменено строк: {cursor.rowcount} {e('kiss', '💋')}")
    except Exception as err: 
        await message.answer(f"Ой, кажется в твоем запросе ошибка: {err}. Но ты всё равно умничка! {e('heart', '💖')}")

@dp.message(Command("db_download", "скачать_бд", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db_download(message: Message):
    if message.chat.type != "private": return
    if DB_PATH.exists(): await message.answer_document(FSInputFile(str(DB_PATH)), caption=f"Твоя база, госпожа! 💋")

@dp.message(Command("db_upload", "загрузить_бд", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db_upload(message: Message, bot: Bot):
    if message.chat.type != "private" or not message.reply_to_message or not message.reply_to_message.document: return
    try:
        await bot.download_file((await bot.get_file(message.reply_to_message.document.file_id)).file_path, destination=str(DB_PATH))
        await message.answer("База обновлена! 💖")
    except Exception as err: await message.answer(f"Ошибка: {err}")

# --- ИНСТРУМЕНТЫ ВЛАДЕЛЬЦА: РАССЫЛКА ПО СПИСКУ ID ---
@dp.message(Command("list_broadcast", "рассылка_список", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_list_broadcast(message: Message, bot: Bot):
    if message.chat.type != "private": return await message.answer("Только в ЛС! 💋")
    args = message.text.split()[1:]
    if not args: return await message.answer("Нужен список ID через пробел! 💋")
    
    await message.answer(f"Начинаю рассылку поздравлений ({len(args)} сообщений)... ✨")
    count = 0
    for uid_str in args:
        try:
            uid = int(uid_str.strip())
            n = random.randint(1, 1000)
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

# --- УМНЫЙ ОБРАБОТЧИК РП И СООБЩЕНИЙ ---
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_everything(message: Message, bot: Bot):
    if not message.text: return
    
    # --- ПРОВЕРКА НА РАЗРЕШЕННУЮ ГРУППУ ---
    if message.chat.id != ALLOWED_GROUP_ID:
        return # Игнорируем сообщения из других групп

    cursor = db_conn.cursor()

    # Объявляем РП действия
    RP_ACTIONS = {
        "обнять": ["крепко обнял(а)", "тепло обнял(а)", "заключил(а) в объятия"],
        "поцеловать": ["нежно поцеловал(а)", "страстно поцеловал(а)", "поцеловал(а) в носик"],
        "ударить": ["дал(а) леща", "отвесил(а) щелбан", "кинул(а) тапок в"],
        "погладить": ["погладил(а) по голове", "ласково погладил(а) по щеке"]
    }

    if any(message.text.startswith(p) for p in CMD_PREFIXES):
        raw_cmd = message.text[1:].split()[0].lower()
        
        phrase = None
        if raw_cmd in RP_ACTIONS:
            phrase = random.choice(RP_ACTIONS[raw_cmd])
        else:
            cursor.execute('SELECT phrase FROM rp_actions WHERE command = ?', (raw_cmd,))
            results = cursor.fetchall()
            if results:
                phrase = html.escape(random.choice(results)[0])
        
        if phrase:
            if not message.reply_to_message: return
                
            target_user = message.reply_to_message.from_user
            if not target_user: return
            
            if target_user.is_bot: return await message.answer(f"Твои касания проходят сквозь мои голографические проекции... Прибереги эту нежность для живых людей {e('kiss', '💋')}")
            if not await is_user_in_chat(message.chat.id, target_user.id, bot): return await message.answer(f"Ой, а его тут уже нет... Попробуй потрогать кого-нибудь другого 😘")
                
            cursor.execute('SELECT custom_nick FROM users WHERE user_id = ?', (message.from_user.id,))
            init_res = cursor.fetchone()
            init_n = html.escape(init_res[0] if init_res and init_res[0] else message.from_user.first_name)
            
            cursor.execute('SELECT custom_nick FROM users WHERE user_id = ?', (target_user.id,))
            targ_res = cursor.fetchone()
            targ_n = html.escape(targ_res[0] if targ_res and targ_res[0] else target_user.first_name)
            
            return await message.answer(f"{get_user_link(message.from_user.id, init_n)} {phrase} {get_user_link(target_user.id, targ_n)}.")

    check_time_resets(cursor)
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', 
                   (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('''UPDATE users SET 
                      messages_total = messages_total + 1,
                      messages_week = messages_week + 1,
                      messages_day = messages_day + 1,
                      messages_hour = messages_hour + 1
                      WHERE user_id = ?''', (message.from_user.id,))
    db_conn.commit()

async def main():
    # Регистрация безопасного отключения
    dp.shutdown.register(on_shutdown)
    
    # На всякий случай удаляем вебхук, если он остался на серверах Telegram
    await bot.delete_webhook(drop_pending_updates=True)
    
    dp.message.middleware(AntiSpamMiddleware())
    print(f"💋 Фемида проснулась и полностью готова! Админ: {SUPER_ADMIN_ID}, Группа: {ALLOWED_GROUP_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())