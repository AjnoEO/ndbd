import json
import os
from classes import Proposed, ProposedJSONENcoder, proposed_hook
from configparser import ConfigParser

if os.path.exists("config.ini"):
    __config = ConfigParser()
    __config.read("config.ini")
else:
    raise FileExistsError("Отсутствует файл config.ini.\n"
                          "Если вы клонировали или запуллили git-репозиторий, "
                          "убедитесь, что вы скопировали example.config.ini, "
                          "переименовали его config.ini и исправили под себя.")

__data = __config["data"]
TOKEN = __data["token"]
OWNER_ID = int(__data["owner_id"])
OWNER_HANDLE = __data["owner_handle"]
MANAGER_CHAT_ID = int(__data["manager_chat_id"])
CHANNEL_ID = int(__data["channel_id"])

PROPOSED: list[Proposed] = []
__proposed_path = "proposed_list.json"
if __proposed_path in os.listdir():
    with open(__proposed_path, encoding="utf8") as f:
        PROPOSED = json.load(f, object_hook=proposed_hook)

def update_proposed():
    with open(__proposed_path, encoding="utf8", mode="w") as f:
        json.dump(PROPOSED, f, ensure_ascii=False, cls=ProposedJSONENcoder, indent=4)
