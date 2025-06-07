import asyncio
from datetime import datetime, timedelta
import os
import pandas as pd
import numpy as np
import telebot
import telebot.async_telebot
import telebot.types as t
from telebot.formatting import escape_html
from telebot.util import quick_markup
from classes import Proposed
from data import CHANNEL_ID, MANAGER_CHAT_ID, OWNER_ID, OWNER_HANDLE, TOKEN
from utils import UserError

PHRASES_PATH = os.path.join("phrases", "phrases.csv")
PHRASES = pd.read_csv(PHRASES_PATH, dtype={"used": np.bool_})

def update_phrases():
    PHRASES.to_csv(PHRASES_PATH, index=False)

LAST_INSPIRATION: dict[int, tuple[int, str, str, str]] = {} # df_idx, phrase, word_lex_0, word_lex_1
SENT_VIDEOS: dict[int, tuple[int, int]] = {} # chat_id, message_id
PROPOSED: list[Proposed] = []
CURRENT_PROPOSED: dict[str, int | str] = {} # idx, action, prompt_msg_id

class MyExceptionHandler(telebot.ExceptionHandler):
    async def handle(self, exc: Exception):
        message = None
        reply_markup = None
        tb = exc.__traceback__
        while (tb := tb.tb_next):
            # print(tb.tb_frame)
            if 'message' in tb.tb_frame.f_locals:
                message = tb.tb_frame.f_locals['message']
                if isinstance(message, t.Message):
                    break
                message = None
        if not message:
            return False
        contact_note = (message.from_user.id != OWNER_ID)
        handled = False
        if isinstance(exc, UserError):
            error_message = "⚠️ Ошибка!\n" + str(exc)
            handled = True
            reply_markup = exc.reply_markup
            contact_note = contact_note and exc.contact_note
        else:
            traceback = exc.__traceback__
            while traceback.tb_next: traceback = traceback.tb_next
            filename = os.path.split(traceback.tb_frame.f_code.co_filename)[1]
            line_number = traceback.tb_lineno
            error_message = (f"⚠️ Во время выполнения операции произошла ошибка:\n"
                             f"<code>{exc.__class__.__name__} "
                             f"({filename}, строка {line_number}): {' '.join([escape_html(str(arg)) for arg in exc.args])}</code>")
        if contact_note:
            error_message += f"\nЕсли тебе кажется, что это баг, сообщи {OWNER_HANDLE}"
        await bot.send_message(message.chat.id, error_message, reply_markup=reply_markup)
        return handled

bot = telebot.async_telebot.AsyncTeleBot(
    TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True,
    exception_handler=MyExceptionHandler()
)
# telebot.logger.setLevel(telebot.logging.DEBUG)

@bot.message_handler(commands=["start", "help"], chat_types=["private", "group", "supergroup"])
async def help(message: t.Message):
    response = ""
    if message.text == "/start":
        response += "Добро пожаловать!\n"
    response += (
        f"Чтобы предложить видео с дактилем, просто пришлите видео, а затем напишите, что вы продактилировали\n"
        f"Ознакомьтесь с советами по записи видео: /tips\n"
        f"Если у вас нет идей, что продактилировать, воспользуйтесь командой /inspiration — она предложит вам словосочетание\n"
        f"По всем вопросам пишите {OWNER_HANDLE}"
    )
    if message.from_user.id == OWNER_ID:
        response += f"\n<code>chat_id={message.chat.id}</code>"
    await bot.send_message(message.chat.id, response)

@bot.message_handler(commands=["tips"], chat_types=["private", "group", "supergroup"])
async def help(message: t.Message):
    response = (
        '<strong>Советы:</strong>\n'
        '- Ознакомьтесь с <a href="https://vk.com/video-211239992_456239018">видео</a> о том, как дактилировать\n'
        '- Записывайте видео так, чтобы ваши лицо и рука были хорошо освещены\n'
        '- Не удаляйте звук с видео. Предпочитаемый формат ― видеосообщения (кружочки)\n'
    )
    await bot.send_message(message.chat.id, response)

@bot.message_handler(commands=["inspiration"], chat_types="private")
async def inspiration(message: t.Message):
    options = PHRASES[~PHRASES["used"]]
    last = LAST_INSPIRATION.get(message.from_user.id)
    if last:
        last = last[2:]
        options = options[~((options["word_lex_0"].isin(last)) | (options["word_lex_1"].isin(last)))]
    result = options.sample(1).iloc[0]
    phrase = result['word_form_0'] + " " + result['word_form_1']
    phrase = phrase[0].upper() + phrase[1:]
    LAST_INSPIRATION[message.from_user.id] = (result.name, phrase, result["word_lex_0"], result["word_lex_1"])
    response = (
        f"Продактилируйте: <strong>{phrase}</strong>\n"
        f"Если хотите получить другое предложение, используйте /inspiration ещё раз."
    )
    await bot.send_message(message.chat.id, response)

def mention(user: t.User): return f"@{user.username}" if user.username else f"<code>{user.id}</code>"

async def propose_manage(i: int):
    proposed = PROPOSED[i]
    buttons = {
        "Принять": {"callback_data": f"proposed_{i}_accept"},
        "Изменить": {"callback_data": f"proposed_{i}_edit"},
        "Отклонить": {"callback_data": f"proposed_{i}_decline"}
    }
    reply_params = t.ReplyParameters(proposed.msg_id, allow_sending_without_reply=True)
    await bot.send_message(
        MANAGER_CHAT_ID,
        f'{proposed.user.full_name} ({mention(proposed.user)}) предлагает видео: '
        f'<tg-spoiler><strong>{proposed.phrase}</strong></tg-spoiler>',
        reply_markup=quick_markup(buttons, row_width=3), reply_parameters=reply_params
    )

PROPOSED_ACTIONS_TO_PROMPTS = {
    "accept": (
        "{user} <strong>принимает</strong> предложение. Введите дату и время публикации в формате "
        "<code>DD.MM(.YYYY) HH:MM</code>, или напишите <code>Сейчас</code> или <code>Позже</code>"
        ),
    "edit": "{user} <strong>редактирует</strong> предложение. Введите исправленный вариант",
    "decline": "{user} <strong>отклоняет</strong> предложение. Укажите причину отказа"
}

@bot.callback_query_handler(lambda query: query.data.startswith("proposed_"))
async def handle_proposed(callback_query: t.CallbackQuery):
    _, i, action = callback_query.data.split("_")
    i = int(i)
    message = callback_query.message
    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=None)
    if not PROPOSED[i]: raise UserError("Это предложение уже обработано")
    if action == "cancel":
        CURRENT_PROPOSED.clear()
        await bot.edit_message_text("Действие отменено", message.chat.id, message.message_id)
        await propose_manage(i)
        return
    buttons = {"Отмена": {"callback_data": f"proposed_{i}_cancel"}}
    prompt_msg = await bot.send_message(
        message.chat.id,
        PROPOSED_ACTIONS_TO_PROMPTS[action].format(user=callback_query.from_user.first_name),
        reply_markup=quick_markup(buttons)
    )
    CURRENT_PROPOSED["idx"] = i
    CURRENT_PROPOSED["action"] = action
    CURRENT_PROPOSED["prompt_msg_id"] = prompt_msg.id

async def end_proposed_prompt():
    prompt_msg_id = CURRENT_PROPOSED["prompt_msg_id"]
    CURRENT_PROPOSED.clear()
    await bot.edit_message_reply_markup(MANAGER_CHAT_ID, prompt_msg_id, reply_markup=None)

async def accept_proposed(i: int, text: str):
    dt = None
    now = datetime.now()
    one_day = timedelta(days=1)
    text = text.strip().lower()
    if text == "сейчас": dt = now
    elif text == "позже": dt = now + one_day
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m %H:%M"):
        try: dt = datetime.strptime(text, fmt)
        except ValueError: pass
    if dt is None:
        msg = "Введите слово <code>Сейчас</code> или <code>Позже</code> или дату в формате <code>DD.MM(.YYYY) HH:MM</code>"
        raise UserError(msg)
    if dt.year < now.year:
        dt = dt.replace(year=now.year)
    if dt < now - one_day:
        dt = dt.replace(year=dt.year+1)
    await end_proposed_prompt()
    proposed = PROPOSED[i]
    PROPOSED[i] = None
    delayed = dt > datetime.now()
    if delayed:
        await bot.send_message(
            MANAGER_CHAT_ID,
            "К сожалению, бот не может автоматически настроить отложенное сообщение. "
            "Перешлите эти сообщения в канал, <strong>удалите указание источника</strong> "
            "и настройте дату и время публикации вручную:"
        )
        send_to = MANAGER_CHAT_ID
    else:
        send_to = CHANNEL_ID
    if proposed.idx is not None:
        PHRASES.loc[proposed.idx, "used"] = True
        update_phrases()
    await bot.copy_message(send_to, MANAGER_CHAT_ID, proposed.msg_id)
    await bot.send_message(send_to, f"||{proposed.phrase}||", parse_mode="MarkdownV2")
    if not delayed:
        await bot.send_message(
            MANAGER_CHAT_ID,
            "Предложение принято и опубликовано в канале!"
        )

async def edit_proposed(i: int, text: str):
    await end_proposed_prompt()
    PROPOSED[i].phrase = text
    PROPOSED[i].idx = None
    await propose_manage(i)

async def decline_proposed(i: int, text: str):
    await end_proposed_prompt()
    proposed = PROPOSED[i]
    PROPOSED[i] = None
    response = f"Ваше предложение было отклонено:\n<em>{text}</em>\nВы можете отправить новое видео с учётом комментария!"
    reply_params = t.ReplyParameters(proposed.orig_msg_id, allow_sending_without_reply=True)
    await bot.send_message(proposed.user.id, response, reply_parameters=reply_params)
    await bot.send_message(MANAGER_CHAT_ID, "Предложение успешно отклонено")

@bot.message_handler(
    func=lambda message: message.chat.id == MANAGER_CHAT_ID and CURRENT_PROPOSED
)
async def handle_current_proposed(message: t.Message):
    i, action = CURRENT_PROPOSED["idx"], CURRENT_PROPOSED["action"]
    match action:
        case "accept": await accept_proposed(i, message.text)
        case "edit": await edit_proposed(i, message.text)
        case "decline": await decline_proposed(i, message.text)

@bot.message_handler(content_types=['video', 'video_note'], chat_types="private")
async def video_sent(message: t.Message):
    SENT_VIDEOS[message.from_user.id] = (message.chat.id, message.message_id)
    last = LAST_INSPIRATION.get(message.from_user.id)
    if last:
        buttons = {"Да": {"callback_data": "inspiration_yes"},
                   "Нет": {"callback_data": "inspiration_no"}}
        response = f"Видео принято! Вы продактилировали <strong>{last[1]}</strong>?"
        await bot.send_message(message.chat.id, response, reply_markup=quick_markup(buttons))
        return
    await bot.send_message(message.chat.id, "Видео принято! Теперь напишите текстом, что вы продактилировали")

async def propose(phrase: str, user: t.User):
    chat_id, message_id = SENT_VIDEOS.pop(user.id)
    idx = None
    last = LAST_INSPIRATION.get(user.id)
    if last:
        idx = last[0]
        del LAST_INSPIRATION[user.id]
    video_message = await bot.copy_message(MANAGER_CHAT_ID, chat_id, message_id)
    i = len(PROPOSED)
    PROPOSED.append(Proposed(user, phrase, video_message.message_id, message_id, idx))
    await propose_manage(i)
    await bot.send_message(chat_id, f"Ваше предложение отправлено на проверку. Спасибо!")

@bot.callback_query_handler(lambda query: query.data.startswith("inspiration_"))
async def handle_inspiration(callback_query: t.CallbackQuery):
    is_inspiration = callback_query.data.endswith("_yes")
    message = callback_query.message
    user = callback_query.from_user
    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=None)
    if is_inspiration:
        last = LAST_INSPIRATION.get(user.id)
        if not last: raise UserError("Не удалось найти предложение для дактиля")
        await propose(last[1], user)
    else:
        LAST_INSPIRATION.pop(user.id)
        await bot.send_message(message.chat.id, "Пожалуйста, напишите текстом, что вы продактилировали")

def is_suggestion(message: t.Message): return message.from_user.id in SENT_VIDEOS

@bot.message_handler(func=is_suggestion, regexp=r"^[А-Яа-яЁё -]+$", chat_types="private")
async def translation_sent(message: t.Message):
    await propose(message.text, message.from_user)

@bot.message_handler(func=is_suggestion, chat_types="private")
async def wrong_translation_sent(message: t.Message):
    await bot.send_message(message.chat.id, "Сообщение содержит запрещённые символы. Пожалуйста, используйте кириллицу")

ALL_CONTENT_TYPES = ['text', 'audio', 'photo', 'voice', 'video', 'document', 'location', 'contact', 'sticker', 'video_note']
@bot.message_handler(content_types=ALL_CONTENT_TYPES, chat_types="private")
async def handle_other_types(message: t.Message):
    raise UserError("Этот тип сообщения не поддерживается. Пожалуйста, используйте команду или пришлите видео")

print("Запускаю бота...")
asyncio.run(bot.polling())