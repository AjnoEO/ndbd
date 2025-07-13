import schedule
# from datetime import datetime, timedelta, timezone
from copy import deepcopy
import os
import random
import threading
import time
import pandas as pd
import numpy as np
import telebot
import telebot.types as t
from telebot.apihelper import ApiTelegramException
from telebot.formatting import escape_html
from telebot.util import quick_markup, extract_command
from classes import Proposed
from data import (
    DEBUG, CHANNEL_ID, MANAGER_CHAT_ID, OWNER_ID, OWNER_HANDLE, TOKEN,
    PROPOSED, USER_DATA, TOTALS, update_user_data, update_proposed
)
from utils import UserError, gram_number

PHRASES_PATH = os.path.join("phrases", "phrases.csv")
PHRASES = pd.read_csv(PHRASES_PATH, dtype={"used": np.bool_})

def update_phrases():
    PHRASES.to_csv(PHRASES_PATH, index=False)

LAST_INSPIRATION: dict[int, tuple[int, str, str, str]] = {} # df_idx, phrase, word_lex_0, word_lex_1
SENT_VIDEOS: dict[int, tuple[int, int]] = {} # chat_id, message_id
CURRENT_PROPOSED: dict[str, int | str] = {} # idx, action, prompt_msg_id

class MyExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exc: Exception):
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
        if message:
            chat_id = message.chat.id
        else:
            chat_id = MANAGER_CHAT_ID
        contact_note = (message is not None) and (message.from_user.id != OWNER_ID)
        handled = False
        if message is not None and isinstance(exc, UserError):
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
        bot.send_message(chat_id, error_message, reply_markup=reply_markup)
        return handled

bot = telebot.TeleBot(
    TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True,
    exception_handler=MyExceptionHandler()
)
telebot.logger.setLevel(telebot.logging.INFO)

@bot.message_handler(commands=["start", "help"], chat_types=["private", "group", "supergroup"])
def help(message: t.Message):
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
        if message.reply_to_message:
            response += f"\n<code>message_id={message.reply_to_message.message_id}</code>"
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=["tips"], chat_types=["private", "group", "supergroup"])
def help(message: t.Message):
    response = (
        '<strong>Советы:</strong>\n'
        '- Ознакомьтесь с <a href="https://vk.com/video-211239992_456239018">видео</a> о том, как дактилировать\n'
        '- Не делайте лишних пауз. Если надо, попрактикуйтесь перед записью, чтобы не задумываться о буквах на ходу\n'
        '- Если всё ещё тяжело, потренируйте дактиль для себя, пока не привыкнете, прежде чем предлагать видео'
        '- Записывайте видео так, чтобы ваши лицо и рука были хорошо освещены\n'
        '- Не удаляйте звук с видео. Предпочитаемый формат ― видеосообщения (кружочки)\n'
    )
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=["inspiration"], chat_types="private")
def inspiration(message: t.Message):
    options = PHRASES[~PHRASES["used"]]
    last = LAST_INSPIRATION.get(message.from_user.id)
    if last:
        last = last[2:]
        options = options[~((options["word_lex_0"].isin(last)) | (options["word_lex_1"].isin(last)))]
    result = options.sample(1).iloc[0]
    phrase = result['word_form_0'] + " " + result['word_form_1']
    phrase = phrase[0].upper() + phrase[1:]
    LAST_INSPIRATION[message.from_user.id] = (int(result.name), phrase, result["word_lex_0"], result["word_lex_1"])
    response = (
        f"Продактилируйте: <strong>{phrase}</strong>\n"
        f"Если хотите получить другое предложение, используйте /inspiration ещё раз."
    )
    bot.send_message(message.chat.id, response)

def mention(user: t.User): return f"@{user.username}" if user.username else f"<code>{user.id}</code>"

def is_manager(user_id: int):
    try:
        bot.get_chat_member(MANAGER_CHAT_ID, user_id)
        return True
    except ApiTelegramException as e:
        if "member not found" in e.description:
            return False
        raise

@bot.message_handler(commands=["ask_for_help"], func=lambda message: message.chat.id == MANAGER_CHAT_ID)
def ask_for_help(message: t.Message):
    text = message.text
    if " " in text and (arg := text[text.find(" ")+1:]).isnumeric():
        arg = int(arg)
    else:
        arg = 5
    if arg < 1: raise UserError("Укажите натуральное число")
    user_lasts = [
        (user_id, data["last"]) for user_id, data in USER_DATA.items()
        if not (data["accepted"] or data.get("no_reminders") or data.get("reminded") or (is_manager(user_id) and not DEBUG))
    ]
    user_lasts = sorted(user_lasts, key=lambda t: t[1])
    prompt = (
        "Здравствуйте, {user}! У нас заканчиваются посты для канала, нам нужна помощь. "
        "Пожалуйста, если есть возможность, запишите одно или несколько новых видео в канал.\n"
        "Полезные команды:\n- /tips\n- /inspiration\nСпасибо!"
    )
    button = {"Отключить напоминания": {"callback_data": "reminders_off"}}
    count = 0
    response = ""
    exception = None
    for user_id, _ in user_lasts:
        user = USER_DATA[user_id]["obj"]
        try:
            bot.send_message(user_id, prompt.format(user=user.first_name), reply_markup=quick_markup(button))
        except ApiTelegramException as e:
            if e.error_code == 403:
                del USER_DATA[user_id]
                update_user_data()
                continue
            if exception is None: exception = e
        count += 1
        USER_DATA[user_id]["reminded"] = True
        update_user_data()
        response += f"\n- {user.full_name} ({mention(user)})"
        if count == arg: break
    if count == 0:
        raise UserError("Не удалось найти пользователей, которых можно призвать записать новое видео")
    response = f"Просьба записать новое видео отправлена {count} пользовател{gram_number(count, 'ю', 'ям')}:" + response
    bot.send_message(MANAGER_CHAT_ID, response)
    if exception: raise exception

@bot.callback_query_handler(func=lambda query: query.data.startswith("reminders_"))
def handle_reminders(query: t.CallbackQuery):
    turn_on = query.data.endswith("_on")
    user = query.from_user
    USER_DATA[user.id]["no_reminders"] = not turn_on
    update_user_data()
    if turn_on:
        response = "Напоминания включены"
        button = {"Отключить": {"callback_data": "reminders_off"}}
    else:
        response = "Напоминания отключены. Если захотите снова получать напоминания, нажмите на кнопку ниже"
        button = {"Включить": {"callback_data": "reminders_on"}}
    bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup=None)
    bot.send_message(query.message.chat.id, response, reply_markup=quick_markup(button))
    bot.answer_callback_query(query.id)

@bot.message_handler(
    commands=["update_history", "force_update_history"],
    func=lambda message: message.chat.id == MANAGER_CHAT_ID
)
def update_history(message: t.Message):
    command = extract_command(message.text)
    if USER_DATA:
        if command == "update_history":
            response = (
                "Какие-то данные об истории предложений уже имеются. Пожалуйста, используйте "
                "<code>/force_update_history</code>, если всё равно хотите перезаписать историю"
            )
            bot.send_message(message.chat.id, response)
            return
        USER_DATA.clear()
        update_user_data()
    USER_DATA["updating"] = True
    prompt = (
        "Добавляйте пользователей в формате <code>&lt;ID&gt; &lt;pos&gt;</code>, где <code>pos</code> — "
        "номер последнего поста от пользователя. Когда всё будет завершено, введите /update_finish"
    )
    bot.send_message(message.chat.id, prompt)

@bot.message_handler(
    regexp="^\d+ -?\d+$", 
    func=lambda message: message.chat.id == MANAGER_CHAT_ID and USER_DATA.get("updating")
)
def load_user(message: t.Message):
    user_id, last = map(int, message.text.split())
    user = bot.get_chat_member(user_id, user_id).user
    USER_DATA[user_id] = {"obj": user, "last": last, "accepted": []}
    bot.send_message(message.chat.id, f"Пользователь сохранён: {user.full_name} ({mention(user)})")

@bot.message_handler(
    commands=["update_finish"], 
    func=lambda message: message.chat.id == MANAGER_CHAT_ID
)
def update_finish(message: t.Message):
    if not USER_DATA.get("updating"):
        raise UserError("Эту команду можно использовать только после /update_history")
    del USER_DATA["updating"]
    update_user_data()
    num = len(USER_DATA)
    bot.send_message(
        message.chat.id, f"Информация {'об' if num in (1, 11) else 'о'} {num} пользовател{gram_number(num, 'е', 'ях')} сохранена"
    )

def propose_manage(i: int):
    proposed = PROPOSED[i]
    buttons = {
        "Принять": {"callback_data": f"proposed_{i}_accept"},
        "Изменить": {"callback_data": f"proposed_{i}_edit"},
        "Отклонить": {"callback_data": f"proposed_{i}_decline"}
    }
    reply_params = t.ReplyParameters(proposed.msg_id, allow_sending_without_reply=True)
    user = proposed.get_user(bot)
    bot.send_message(
        MANAGER_CHAT_ID,
        f'{user.full_name} ({mention(user)}) предлагает видео: '
        f'<tg-spoiler><strong>{proposed.phrase}</strong></tg-spoiler>',
        reply_markup=quick_markup(buttons, row_width=3), reply_parameters=reply_params
    )

PROPOSED_ACTIONS_TO_PROMPTS = {
    "accept": "{user} <strong>принимает</strong> предложение. Вы уверены?",
    "edit": "{user} <strong>редактирует</strong> предложение. Введите исправленный вариант",
    "decline": "{user} <strong>отклоняет</strong> предложение. Укажите причину отказа"
}

def accept_proposed(idx: int):
    proposed = PROPOSED[idx]
    user = proposed.get_user(bot)
    USER_DATA.setdefault(user.id, {
        "obj": user,
        "last": 0,
        "accepted": []
    })
    USER_DATA[user.id]["accepted"].append(idx)
    update_user_data()

@bot.callback_query_handler(lambda query: query.data.startswith("proposed_"))
def handle_proposed(callback_query: t.CallbackQuery):
    _, i, action = callback_query.data.split("_")
    i = int(i)
    message = callback_query.message
    bot.answer_callback_query(callback_query.id)
    bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=None)
    if not PROPOSED[i]: raise UserError("Это предложение уже обработано")
    if action == "cancel":
        CURRENT_PROPOSED.clear()
        bot.edit_message_text("Действие отменено", message.chat.id, message.message_id)
        propose_manage(i)
        return
    if action == "confirm":
        accept_proposed(CURRENT_PROPOSED["idx"])
        reply_params = t.ReplyParameters(CURRENT_PROPOSED["prompt_msg_id"])
        bot.send_message(message.chat.id, "Предложение принято", reply_parameters=reply_params)
        return
    buttons = {"Подтвердить": {"callback_data": f"proposed_{i}_confirm"}, "Отмена": {"callback_data": f"proposed_{i}_cancel"}}
    if action != "accept":
        del buttons["Подтвердить"]
    prompt_msg = bot.send_message(
        message.chat.id,
        PROPOSED_ACTIONS_TO_PROMPTS[action].format(user=callback_query.from_user.first_name),
        reply_parameters=t.ReplyParameters(message.id),
        reply_markup=quick_markup(buttons)
    )
    CURRENT_PROPOSED["idx"] = i
    CURRENT_PROPOSED["action"] = action
    CURRENT_PROPOSED["prompt_msg_id"] = prompt_msg.id

def end_proposed_prompt():
    prompt_msg_id = CURRENT_PROPOSED["prompt_msg_id"]
    CURRENT_PROPOSED.clear()
    bot.edit_message_reply_markup(MANAGER_CHAT_ID, prompt_msg_id, reply_markup=None)

def post_proposed(i: int):
    if i >= len(PROPOSED) or not PROPOSED[i]: raise UserError(f"Предложение с ID {i} не найдено")
    proposed = PROPOSED[i]
    PROPOSED[i] = None
    update_proposed()
    USER_DATA[proposed.user_id]["last"] = TOTALS["posted"]+1
    USER_DATA[proposed.user_id]["accepted"].remove(i)
    update_user_data()
    if proposed.phrase_idx is not None:
        PHRASES.loc[proposed.phrase_idx, "used"] = True
        update_phrases()
    bot.copy_message(CHANNEL_ID, MANAGER_CHAT_ID, proposed.msg_id)
    bot.send_message(CHANNEL_ID, f"<tg-spoiler>{proposed.phrase}</tg-spoiler>")

def edit_proposed(i: int, text: str):
    end_proposed_prompt()
    PROPOSED[i].phrase = text
    PROPOSED[i].phrase_idx = None
    update_proposed()
    propose_manage(i)

def decline_proposed(i: int, text: str):
    end_proposed_prompt()
    proposed = PROPOSED[i]
    PROPOSED[i] = None
    update_proposed()
    response = f"Ваше предложение было отклонено:\n<em>{text}</em>\nВы можете отправить новое видео с учётом комментария!"
    reply_params = t.ReplyParameters(proposed.orig_msg_id, allow_sending_without_reply=True)
    bot.send_message(proposed.user_id, response, reply_parameters=reply_params)
    bot.send_message(MANAGER_CHAT_ID, "Предложение успешно отклонено")

@bot.message_handler(
    func=lambda message: message.chat.id == MANAGER_CHAT_ID and CURRENT_PROPOSED and CURRENT_PROPOSED["action"] != "accept"
)
def handle_current_proposed(message: t.Message):
    i, action = CURRENT_PROPOSED["idx"], CURRENT_PROPOSED["action"]
    match action:
        case "edit": edit_proposed(i, message.text)
        case "decline": decline_proposed(i, message.text)

@bot.message_handler(content_types=['video', 'video_note'], chat_types="private")
def video_sent(message: t.Message):
    SENT_VIDEOS[message.from_user.id] = (message.chat.id, message.message_id)
    last = LAST_INSPIRATION.get(message.from_user.id)
    if last:
        buttons = {"Да": {"callback_data": "inspiration_yes"},
                   "Нет": {"callback_data": "inspiration_no"}}
        response = f"Видео принято! Вы продактилировали <strong>{last[1]}</strong>?"
        bot.send_message(message.chat.id, response, reply_markup=quick_markup(buttons))
        return
    bot.send_message(message.chat.id, "Видео принято! Теперь напишите текстом, что вы продактилировали")

@bot.message_handler(commands=["add"], regexp="^/add \d+ [А-Яа-яЁё -]+$", func=lambda message: message.chat.id == MANAGER_CHAT_ID)
def force_propose(message: t.Message):
    if not message.reply_to_message or message.reply_to_message.content_type not in ['video', 'video_note']:
        raise UserError("Команду /add необходимо использовать в ответ на видео")
    _, user_id, phrase = message.text.split(maxsplit=2)
    user_id = int(user_id)
    i = len(PROPOSED)
    user = USER_DATA[user_id]["obj"] if user_id in USER_DATA else user_id
    PROPOSED.append(Proposed(user, phrase, message.reply_to_message.message_id, 0))
    update_proposed()
    accept_proposed(i)
    user = USER_DATA[user_id]["obj"]
    bot.send_message(message.chat.id, f"Предложение от пользователя {user.full_name} ({mention(user)}) принято. ID: {i}")

@bot.message_handler(commands=["add"], func=lambda message: message.chat.id == MANAGER_CHAT_ID)
def wrong_force_propose(message: t.Message):
    if message.text == "/add":
        raise UserError("Формат команды: <code>/add &lt;ID&gt; &lt;транскрипция&gt;</code>")
    raise UserError("Сообщение содержит запрещённые символы. Пожалуйста, используйте кириллицу")

def next_to_post(
        user_data: dict[int, dict[str, t.User|int|list[int]]] = None, 
        totals: dict[str, int] = None):
    if user_data is None: user_data = USER_DATA
    if totals is None: totals = TOTALS
    input_len = totals["accepted"]
    best_user = None
    best_val = None
    for user_id, data in user_data.items():
        count = len(data["accepted"])
        if count == 0: continue
        last = totals["posted"] + 1 - data["last"]
        val = (input_len) - last * (count - 1) - 1
        if count > 1: val *= input_len
        val = (val, -last)
        if best_val is None or best_val > val:
            best_user = user_id
            best_val = val
    return best_user

@bot.message_handler(commands=["force_post"], func=lambda message: message.chat.id == MANAGER_CHAT_ID)
def force_post(message: t.Message):
    i = message.text.split(maxsplit=1)[-1]
    if not (i.isnumeric() or i == "next"): raise UserError("Формат команды: <code>/force_post &lt;ID|next&gt;</code>")
    if i == "next": i = USER_DATA[next_to_post()]["accepted"][0]
    if i is None: raise UserError("Больше нет принятых неопубликованных предложений")
    else: i = int(i)
    post_proposed(i)
    bot.send_message(
        MANAGER_CHAT_ID,
        "Предложение опубликовано в канале!"
    )

@bot.message_handler(commands=["waitlist"], func=lambda message: message.chat.id == MANAGER_CHAT_ID)
def waitlist(message: t.Message):
    if TOTALS["accepted"] == 0:
        bot.send_message(message.chat.id, f"Нет принятых неопубликованных предложений")
        return
    t = TOTALS["accepted"]
    response = f"Публикации ожида{gram_number(t, 'ет', 'ют')} {t} предложени{gram_number(t, 'е', 'я', 'й')}:"
    user_data_copy = deepcopy(USER_DATA)
    totals_copy = TOTALS.copy()
    for i in range(10):
        if totals_copy["accepted"] == 0: break
        next_user = next_to_post(user_data_copy, totals_copy)
        totals_copy["posted"] += 1
        totals_copy["accepted"] -= 1
        data = user_data_copy[next_user]
        data["last"] = totals_copy["posted"]
        idx = data["accepted"].pop(0)
        user = data["obj"]
        response += f"\n- <code>{idx}</code> <tg-spoiler>{PROPOSED[idx].phrase}</tg-spoiler> — {user.full_name} ({mention(user)})"
    else:
        response += f"\nи ещё {totals_copy['accepted']}…"
    bot.send_message(message.chat.id, response)

def propose(phrase: str, user: t.User):
    chat_id, message_id = SENT_VIDEOS.pop(user.id)
    phrase_idx = None
    last = LAST_INSPIRATION.get(user.id)
    if last:
        phrase_idx = last[0]
        del LAST_INSPIRATION[user.id]
    video_message = bot.copy_message(MANAGER_CHAT_ID, chat_id, message_id)
    i = len(PROPOSED)
    PROPOSED.append(Proposed(user, phrase, video_message.message_id, message_id, phrase_idx))
    update_proposed()
    USER_DATA.setdefault(user.id, {"obj": user, "last": 0, "accepted": []})
    USER_DATA[user.id]["reminded"] = False
    update_user_data()
    propose_manage(i)
    bot.send_message(chat_id, f"Ваше предложение отправлено на проверку. Спасибо!")

@bot.callback_query_handler(lambda query: query.data.startswith("inspiration_"))
def handle_inspiration(callback_query: t.CallbackQuery):
    is_inspiration = callback_query.data.endswith("_yes")
    message = callback_query.message
    user = callback_query.from_user
    bot.answer_callback_query(callback_query.id)
    bot.edit_message_reply_markup(message.chat.id, message.message_id, reply_markup=None)
    if is_inspiration:
        last = LAST_INSPIRATION.get(user.id)
        if not last: raise UserError("Не удалось найти предложение для дактиля")
        propose(last[1], user)
    else:
        LAST_INSPIRATION.pop(user.id)
        bot.send_message(message.chat.id, "Пожалуйста, напишите текстом, что вы продактилировали")

def is_suggestion(message: t.Message): return message.from_user.id in SENT_VIDEOS

@bot.message_handler(func=is_suggestion, regexp=r"^[А-Яа-яЁё -]+$", chat_types="private")
def translation_sent(message: t.Message):
    propose(message.text, message.from_user)

@bot.message_handler(func=is_suggestion, chat_types="private")
def wrong_translation_sent(message: t.Message):
    bot.send_message(message.chat.id, "Сообщение содержит запрещённые символы. Пожалуйста, используйте кириллицу")

ALL_CONTENT_TYPES = ['text', 'audio', 'photo', 'voice', 'video', 'document', 'location', 'contact', 'sticker', 'video_note']
@bot.message_handler(content_types=ALL_CONTENT_TYPES, chat_types="private")
def handle_other_types(message: t.Message):
    raise UserError("Этот тип сообщения не поддерживается. Пожалуйста, используйте команду или пришлите видео")

def job():
    next_user = next_to_post()
    if next_user is None:
        response = (
            "<strong>Предложенные посты закончились!</strong> Не могу запостить новое видео\n"
            "Можно запросить новые видео у пользователей командой /ask_for_help"
        )
        bot.send_message(MANAGER_CHAT_ID, response)
    else:
        post_proposed(USER_DATA[next_user]["accepted"][0])

def schedules():
    MSK = "Europe/Moscow"
    if DEBUG:
        schedule.every().minute.do(job)
    else:
        schedule.every().day.at("09:00", MSK).do(job)
        schedule.every().day.at("17:00", MSK).do(job)
    while True:
        schedule.run_pending()
        interval = 60 if DEBUG else random.randint(3600, 3600*3)
        time.sleep(interval)

def main():
    bot.infinity_polling()

threads: list[threading.Thread] = []
for func in [main, schedules]:
    thr = threading.Thread(target=func, name=func.__name__)
    threads.append(thr)
    thr.daemon = True
    thr.start()

while True:
    time.sleep(1)
