import json
import os
from classes import Proposed, ObjectJSONEncoder, object_hook
from configparser import ConfigParser
from telebot.types import User

if os.path.exists("config.ini"):
    __config = ConfigParser()
    __config.read("config.ini")
else:
    raise FileExistsError("Отсутствует файл config.ini.\n"
                          "Если вы клонировали или запуллили git-репозиторий, "
                          "убедитесь, что вы скопировали example.config.ini, "
                          "переименовали его config.ini и исправили под себя.")

__data = __config["data"]
DEBUG = __data["debug"].lower() == 'true'
TOKEN = __data["token"]
OWNER_ID = int(__data["owner_id"])
OWNER_HANDLE = __data["owner_handle"]
MANAGER_CHAT_ID = int(__data["manager_chat_id"])
CHANNEL_ID = int(__data["channel_id"])

USER_DATA: dict[int, dict[str, User|int|list[int]|bool]] = {} # obj, last, accepted, no_reminders, reminded
__user_data_path = "user_data.json"
if __user_data_path in os.listdir():
    with open(__user_data_path, encoding="utf8") as f:
        USER_DATA = json.load(f, object_hook=object_hook)
    USER_DATA = {int(i): v for i, v in USER_DATA.items()}

TOTALS = {}
def update_totals():
    TOTALS["posted"] = max([d["last"] for d in USER_DATA.values()], default=0)
    TOTALS["accepted"] = sum([len(d["accepted"]) for d in USER_DATA.values()])
update_totals()

def update_user_data():
    with open(__user_data_path, encoding="utf8", mode="w") as f:
        json.dump(USER_DATA, f, ensure_ascii=False, cls=ObjectJSONEncoder, indent=4)
    update_totals()

PROPOSED: list[Proposed] = []
__proposed_path = "proposed_list.json"
if __proposed_path in os.listdir():
    with open(__proposed_path, encoding="utf8") as f:
        PROPOSED = json.load(f, object_hook=object_hook)
    for p in PROPOSED:
        if not p: continue
        if p._user: continue
        if p.user_id in USER_DATA: p._user = USER_DATA[p.user_id]["obj"]

def update_proposed():
    with open(__proposed_path, encoding="utf8", mode="w") as f:
        json.dump(PROPOSED, f, ensure_ascii=False, cls=ObjectJSONEncoder, indent=4)
