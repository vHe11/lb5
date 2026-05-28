import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------
# ЗАГРУЗКА ЛОКАЛЬНЫХ JSON
# -------------------------------------------------------------
def load_json(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки {filename}: {e}")
        return None

heroes_data = load_json('heroes.json')
abilities_data = load_json('abilities.json')
aghs_data = load_json('aghs_desc.json')   # это список

if heroes_data is None:
    logger.error("heroes.json не найден!")
    exit(1)

# Приводим heroes_data к словарю {id: hero}
if isinstance(heroes_data, list):
    heroes_by_id = {h['id']: h for h in heroes_data}
else:
    heroes_by_id = {int(k): v for k, v in heroes_data.items()}

# Список героев для пагинации
heroes_list = sorted([(hid, h['localized_name']) for hid, h in heroes_by_id.items()], key=lambda x: x[1])

# Индекс улучшений по hero_id
aghs_by_hero = {}
if aghs_data and isinstance(aghs_data, list):
    for entry in aghs_data:
        hero_id = entry.get('hero_id')
        if hero_id is not None:
            aghs_by_hero[hero_id] = entry

# -------------------------------------------------------------
# ФУНКЦИИ ФИЛЬТРАЦИИ СПОСОБНОСТЕЙ
# -------------------------------------------------------------
def is_main_ability(ab_key, ab_val):
    if not isinstance(ab_val, dict):
        return False
    exclude = ['_talent', '_tooltip', '_custom', '_spell_latent', 'bonus', 'value', 'radius', 'duration', 'cooldown']
    if any(x in ab_key.lower() for x in exclude):
        return False
    dname = ab_val.get('dname', '')
    if dname.startswith('+') or dname.startswith('-'):
        return False
    if ab_val.get('is_aghanims_upgrade') or ab_val.get('is_shard_upgrade'):
        return False
    return bool(dname) and len(ab_key) < 50

def get_hero_abilities(hero_id):
    hero = heroes_by_id.get(hero_id, {})
    hero_eng = hero.get('name', '').replace('npc_dota_hero_', '').lower()
    if not abilities_data:
        return []
    abilities = []
    for ab_key, ab_val in abilities_data.items():
        if hero_eng in ab_key.lower() and is_main_ability(ab_key, ab_val):
            abilities.append({
                "name": ab_val.get('dname', ab_key),
                "desc": ab_val.get('desc', 'Описание отсутствует.'),
                "key": ab_key   # сохраняем оригинальный ключ для поиска улучшений
            })
    return abilities[:7]

# -------------------------------------------------------------
# ПОЛУЧЕНИЕ УЛУЧШЕНИЙ ДЛЯ СПОСОБНОСТИ
# -------------------------------------------------------------
def get_upgrades_for_ability(hero_id, ability_key, ability_name):
    """Возвращает (aghs_desc, shard_desc) для способности героя."""
    hero_upgrades = aghs_by_hero.get(hero_id)
    if not hero_upgrades:
        return ("", "")
    aghs = ""
    shard = ""
    # Сравниваем ability_key (оригинальный ключ из abilities.json) или ability_name (локализованное имя)
    # с полями scepter_skill_name и shard_skill_name.
    # В aghs_desc.json эти поля содержат английские названия способностей (как в abilities.json).
    scepter_skill = hero_upgrades.get('scepter_skill_name', '')
    shard_skill = hero_upgrades.get('shard_skill_name', '')
    # Проверяем совпадение (без учёта регистра, убираем возможные суффиксы)
    if scepter_skill and (scepter_skill.lower() == ability_key.lower() or scepter_skill.lower() in ability_key.lower()):
        aghs = hero_upgrades.get('scepter_desc', '')
    if shard_skill and (shard_skill.lower() == ability_key.lower() or shard_skill.lower() in ability_key.lower()):
        shard = hero_upgrades.get('shard_desc', '')
    return (aghs, shard)

# -------------------------------------------------------------
# ФОРМИРОВАНИЕ СООБЩЕНИЙ
# -------------------------------------------------------------
def get_hero_stats(hero_id):
    h = heroes_by_id.get(hero_id, {})
    return {
        "base_str": h.get('base_str', 0),
        "base_agi": h.get('base_agi', 0),
        "base_int": h.get('base_int', 0),
        "str_gain": h.get('str_gain', 0.0),
        "agi_gain": h.get('agi_gain', 0.0),
        "int_gain": h.get('int_gain', 0.0),
        "primary_attr": h.get('primary_attr', 'str')
    }

async def send_hero_attributes(message, hero_id):
    hero = heroes_by_id.get(hero_id)
    if not hero:
        await message.reply_text("Герой не найден.")
        return
    name = hero.get('localized_name', 'Неизвестный')
    stats = get_hero_stats(hero_id)
    text = f"🎭 *{name}*\n"
    text += f"⚔️ Атрибут: {stats['primary_attr'].capitalize()}\n"
    text += f"💪 Сила: {stats['base_str']} +{stats['str_gain']}/ур\n"
    text += f"🏃 Ловкость: {stats['base_agi']} +{stats['agi_gain']}/ур\n"
    text += f"🧠 Интеллект: {stats['base_int']} +{stats['int_gain']}/ур"
    await message.reply_text(text, parse_mode="Markdown")

async def send_hero_abilities(message, hero_id):
    hero = heroes_by_id.get(hero_id)
    if not hero:
        await message.reply_text("Герой не найден.")
        return
    name = hero.get('localized_name', 'Неизвестный')
    abilities = get_hero_abilities(hero_id)
    if not abilities:
        await message.reply_text(f"Способности для {name} не найдены.")
        return
    text = f"🎭 *{name}* — способности:\n\n"
    for ab in abilities:
        text += f"▫️ *{ab['name']}*\n{ab['desc']}\n"
        aghs, shard = get_upgrades_for_ability(hero_id, ab['key'], ab['name'])
        if aghs:
            text += f"   👑 *Аганим:* {aghs}\n"
        if shard:
            text += f"   🧩 *Осколок:* {shard}\n"
        text += "\n"
    if len(text) > 4000:
        text = text[:3900] + "\n\n...(обрезано)"
    await message.reply_text(text, parse_mode="Markdown")

# -------------------------------------------------------------
# КЛАВИАТУРЫ И ПАГИНАЦИЯ
# -------------------------------------------------------------
ITEMS_PER_PAGE = 5

def heroes_keyboard(page=0):
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    buttons = []
    for hid, name in heroes_list[start:end]:
        buttons.append([InlineKeyboardButton(name, callback_data=f"hero_{hid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Назад", callback_data=f"hero_page_{page-1}"))
    if end < len(heroes_list):
        nav.append(InlineKeyboardButton("Вперёд ▶", callback_data=f"hero_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def hero_action_keyboard(hero_id):
    buttons = [
        [InlineKeyboardButton("📊 Атрибуты", callback_data=f"attr_{hero_id}")],
        [InlineKeyboardButton("🪄 Способности + улучшения", callback_data=f"abils_{hero_id}")],
        [InlineKeyboardButton("◀ К списку героев", callback_data="back_to_heroes")]
    ]
    return InlineKeyboardMarkup(buttons)

def main_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Выбрать героя", callback_data="choose_hero")]])

# -------------------------------------------------------------
# ОБРАБОТЧИКИ
# -------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔮 *Dota 2 Hero Bot*\nВыбери героя и получи информацию о его атрибутах, способностях и улучшениях от Аганима/Осколка.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())
        return

    if data == "choose_hero":
        context.user_data['hero_page'] = 0
        await query.edit_message_text("Выберите героя:", reply_markup=heroes_keyboard(0))
        return

    if data == "back_to_heroes":
        page = context.user_data.get('hero_page', 0)
        await query.edit_message_text("Выберите героя:", reply_markup=heroes_keyboard(page))
        return

    if data.startswith("hero_page_"):
        page = int(data.split("_")[2])
        context.user_data['hero_page'] = page
        await query.edit_message_text("Выберите героя:", reply_markup=heroes_keyboard(page))
        return

    if data.startswith("hero_"):
        hero_id = int(data.split("_")[1])
        context.user_data['selected_hero'] = hero_id
        hero_name = heroes_by_id[hero_id]['localized_name']
        await query.edit_message_text(
            f"Выбран: *{hero_name}*\nЧто хотите узнать?",
            reply_markup=hero_action_keyboard(hero_id),
            parse_mode="Markdown"
        )
        return

    if data.startswith("attr_"):
        hero_id = int(data.split("_")[1])
        await send_hero_attributes(query.message, hero_id)
        hero_name = heroes_by_id[hero_id]['localized_name']
        await query.message.reply_text(
            f"Что ещё по *{hero_name}*?",
            reply_markup=hero_action_keyboard(hero_id),
            parse_mode="Markdown"
        )
        return

    if data.startswith("abils_"):
        hero_id = int(data.split("_")[1])
        await send_hero_abilities(query.message, hero_id)
        hero_name = heroes_by_id[hero_id]['localized_name']
        await query.message.reply_text(
            f"Что ещё по *{hero_name}*?",
            reply_markup=hero_action_keyboard(hero_id),
            parse_mode="Markdown"
        )
        return

    await query.edit_message_text("Неизвестная команда", reply_markup=main_menu_keyboard())

# -------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------
def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не найден в .env")
        return
    # Проверка файлов
    required = ['heroes.json', 'abilities.json', 'aghs_desc.json']
    missing = [f for f in required if not os.path.exists(f)]
    if missing:
        logger.warning(f"Отсутствуют файлы: {missing}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    logger.info("Бот запущен. Проверьте способности героев с улучшениями.")
    app.run_polling()

if __name__ == "__main__":
    main()