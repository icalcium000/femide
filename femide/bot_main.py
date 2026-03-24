import asyncio
import sqlite3
import logging
import random
import time
import html
import os
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
TOKEN = ""  # ВСТАВЬТЕ ВАШ ТОКЕН СЮДА
SUPER_ADMIN_ID = 1197260250   # Ваш Telegram ID
DB_NAME = 'Femide.db'

CMD_PREFIXES = ("/", "!")

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

# --- БАЗА ДАННЫХ (SQLITE) ---
def ensure_column(cursor, table, column, col_type):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

def init_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
bot = Bot(token=TOKEN if TOKEN else "PASTE_YOUR_TOKEN_HERE", default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

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
        ]
        await message.answer(random.choice(phrases))

@dp.message(F.left_chat_member)
async def goodbye_member(message: Message):
    member = message.left_chat_member
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
        f"<b>Игры:</b> <code>!крутка</code> [от] [до], <code>!крутить</code> (рулетка имен), <code>!список_имен</code>\n"
        f"<b>Инструменты БД:</b> <code>!скачать_бд</code>, <code>!загрузить_бд</code>\n"
        f"<b>Топы:</b> <code>!топ</code>, <code>!топнеделя</code>, <code>!топдень</code>, <code>!топчас</code>\n"
    )
    await message.answer(text)

# --- НАСТРОЙКИ АДМИНА ---
async def set_setting(message: Message, key: str, bot: Bot):
    if not await is_admin(message, bot): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.answer(f"А текст-то где, милый? {e('kiss', '💋')}")
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

# --- СКЛЕЙКА СООБЩЕНИЙ В ЛС ---
@dp.message(Command("combine_start", "объед_нач", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_combine_start(message: Message):
    global admin_combine_state, admin_combine_messages
    if message.chat.type != "private": return
    admin_combine_state = True
    admin_combine_messages = []
    await message.answer(f"Режим склейки активирован, сладкий! Как закончишь, шепни <code>!объед_кон</code> {e('kiss', '💋')}")

@dp.message(Command("combine_end", "объед_кон", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_combine_end(message: Message):
    global admin_combine_state, admin_combine_messages
    if message.chat.type != "private": return
    if not admin_combine_state: return await message.answer(f"Но мы ведь и не начинали... Напиши сначала <code>!объед_нач</code> 😘")
    admin_combine_state = False
    if not admin_combine_messages: return await message.answer("Мне нечего объединять 🤷‍♀️")
    combined_text = "\n".join(admin_combine_messages)
    try: await message.answer(f"<b>Готово! Вот твой текст:</b>\n\n{combined_text}")
    except Exception as err: await message.answer(f"Ошибка форматирования: {err}")
    admin_combine_messages = []

@dp.message(F.chat.type == "private", F.from_user.id == SUPER_ADMIN_ID, F.text)
async def handle_private_messages(message: Message):
    global admin_combine_state, admin_combine_messages
    if admin_combine_state:
        if any(message.text.startswith(p) for p in CMD_PREFIXES): return
        admin_combine_messages.append(message.html_text)

# --- ПРОФИЛЬ ---
@dp.message(Command("profile", "профиль", prefix=CMD_PREFIXES))
async def show_profile(message: Message, bot: Bot):
    target_user = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if not target_user or target_user.is_bot: return 
            
    cursor = db_conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, joined_date) 
                      VALUES (?, ?, ?)''', (target_user.id, target_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    db_conn.commit()
    
    cursor.execute('''SELECT custom_nick, messages_total, joined_date, warns, balance, 
                      characters, rewards, description, likes, dislikes, spouse_id, clan_id, custom_photo, rest_status 
                      FROM users WHERE user_id = ?''', (target_user.id,))
    data = cursor.fetchone()
    
    nick = html.escape(data[0] if data[0] else target_user.first_name)
    spouse_text = f"{e('dislike', '💔')} В активном поиске"
    if data[10]:
        cursor.execute('SELECT custom_nick, username FROM users WHERE user_id = ?', (data[10],))
        sp_res = cursor.fetchone()
        sp_nick = html.escape(sp_res[0] if sp_res and sp_res[0] else (sp_res[1] if sp_res else "Партнер"))
        spouse_text = f"{e('like', '❤️')} Сердце отдано {get_user_link(data[10], sp_nick)}"

    profile_text = (
        f"<b>Досье на:</b> {get_user_link(target_user.id, nick)}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>Статус:</b> {get_rank(data[1])}\n"
        f"<b>Сообщений:</b> {data[1]}\n"
        f"<b>В базе с:</b> {data[2]}\n"
        f"<b>Косяки:</b> {data[3]}/3\n"
        f"<b>Баланс:</b> {data[4]} {CURRENCY}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<b>О себе:</b> {html.escape(data[7]) if data[7] else 'Не указано'}\n"
        f"<b>Рест:</b> {html.escape(data[13]) if data[13] else 'Активен'}\n"
        f"{e('like', '❤️')} <b>Любит:</b> {html.escape(data[8]) if data[8] else 'Не указано'}\n"
        f"{e('dislike', '💔')} <b>Не любит:</b> {html.escape(data[9]) if data[9] else 'Не указано'}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{spouse_text}\n"
    )
    if data[5]: profile_text += f"<b>Персонажи:</b> {data[5]}\n"
    if data[6]: profile_text += f"<b>Награды:</b> {data[6]}\n"

    try:
        if data[12]: await message.answer_photo(photo=data[12], caption=profile_text)
        else: await message.answer(profile_text)
    except: await message.answer(profile_text)

# --- МОДЕРАЦИЯ И БАЗА ---
@dp.message(Command("db_query", "запрос", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db(message: Message):
    if message.chat.type != "private": return
    try:
        q = message.text.split(maxsplit=1)[1]
        cursor = db_conn.cursor()
        cursor.execute(q)
        if q.lower().startswith("select"): await message.answer(f"Нашла:\n{hcode(str(cursor.fetchall()[:10]))}")
        else:
            db_conn.commit()
            await message.answer(f"Исполнено! Изменено: {cursor.rowcount} {e('kiss', '💋')}")
    except Exception as err: await message.answer(f"Ошибка: {err}")

@dp.message(Command("db_download", "скачать_бд", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db_download(message: Message):
    if message.chat.type != "private": return
    if os.path.exists(DB_NAME): await message.answer_document(FSInputFile(DB_NAME), caption=f"Твоя база, госпожа! 💋")

@dp.message(Command("db_upload", "загрузить_бд", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_db_upload(message: Message, bot: Bot):
    if message.chat.type != "private" or not message.reply_to_message or not message.reply_to_message.document: return
    try:
        await bot.download_file((await bot.get_file(message.reply_to_message.document.file_id)).file_path, destination=DB_NAME)
        await message.answer("База обновлена! 💖")
    except Exception as err: await message.answer(f"Ошибка: {err}")

# --- ИНСТРУМЕНТЫ ВЛАДЕЛЬЦА: РАССЫЛКА ПО СПИСКУ ID ---
@dp.message(Command("list_broadcast", "рассылка_список", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_list_broadcast(message: Message, bot: Bot):
    if message.chat.type != "private":
        return await message.answer("Эту команду можно шептать мне только в личные сообщения! 💋")

    args = message.text.split()[1:]
    
    if not args:
        return await message.answer(f"Сладкий, мне нужен список ID через пробел!\nПример: <code>!рассылка_список 12345 12345 67890</code>\n(Если один ID указан дважды, человеку придет два сообщения) 😘")

    await message.answer(f"Начинаю рассылку поздравлений по твоему списку ({len(args)} сообщений)... ✨")
    
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
        except ValueError:
            logging.error(f"Неверный формат ID: {uid_str}")
            continue
        except Exception as e:
            logging.error(f"Ошибка отправки для {uid_str}: {e}")
            continue

    await message.answer(f"Готово, радость моя! Успешно доставлено {count} сообщений. 💋")

@dp.message(Command("helpmelak", prefix=CMD_PREFIXES), F.from_user.id == SUPER_ADMIN_ID)
async def cmd_helpmelak(message: Message):
    text = (
        f"Секретное меню для моего Создателя 🤫\n\n"
        f"<code>!запрос [SQL]</code> — работа с базой.\n"
        f"<code>!скачать_бд</code> / <code>!загрузить_бд</code> — экспорт/импорт файла.\n"
        f"<code>!рассылка_список [ID ID ID]</code> — рассылка по твоему списку (можно дублировать ID). 💋\n\n"
        f"<i>Рассылки в группу:</i>\n"
        f"<code>!уст_основной_чат</code> (в группе).\n"
        f"<code>!утро</code> / <code>!ночь</code> / <code>!сказать [текст]</code> (в ЛС).\n"
    )
    await message.answer(text)

# --- РЕСТ СТАТУС ---
@dp.message(Command("setrest", "рест", prefix=CMD_PREFIXES))
async def cmd_setrest(message: Message):
    args = message.text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else "Отдыхает"
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET rest_status = ? WHERE user_id = ?', (reason, message.from_user.id))
    db_conn.commit()
    await message.answer(f"Записала тебя в рест. Отдыхай, золотце! {e('kiss', '💋')}")

@dp.message(Command("unrest", "анрест", prefix=CMD_PREFIXES))
async def cmd_unrest(message: Message):
    db_conn.execute('UPDATE users SET rest_status = NULL WHERE user_id = ?', (message.from_user.id,))
    db_conn.commit()
    await message.answer(f"С возвращением! Я скучала {e('heart', '💖')}")

# --- УМНЫЙ ОБРАБОТЧИК ---
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_everything(message: Message, bot: Bot):
    if not message.text or message.chat.id != ALLOWED_GROUP_ID: return
    cursor = db_conn.cursor()
    check_time_resets(cursor)
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, joined_date) VALUES (?, ?, ?)', (message.from_user.id, message.from_user.full_name, datetime.now().strftime('%Y-%m-%d')))
    cursor.execute('UPDATE users SET messages_total=messages_total+1, messages_week=messages_week+1, messages_day=messages_day+1, messages_hour=messages_hour+1 WHERE user_id=?', (message.from_user.id,))
    db_conn.commit()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    dp.message.middleware(AntiSpamMiddleware())
    print("Бот алгоритма Фемида запущен (SQLite) 💋")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())