from json import JSONEncoder
import telebot.types as t
# from telebot.async_telebot import AsyncTeleBot
from telebot import TeleBot

class Proposed:
    def __init__(self, user: t.User, phrase: str, msg_id: int, orig_msg_id: int, phrase_idx: int | None = None):
        if isinstance(user, (str, dict)): user = t.User.de_json(user)
        if isinstance(user, t.User):
            self.user_id = user.id
            self._user = user
        else:
            self.user_id = user
            self._user = None
        self.phrase = phrase
        self.msg_id = msg_id
        self.orig_msg_id = orig_msg_id
        self.phrase_idx = phrase_idx
    
    def to_json(self):
        return {
            "__class__": "Proposed",
            "user": self.user_id,
            "phrase": self.phrase,
            "msg_id": self.msg_id,
            "orig_msg_id": self.orig_msg_id,
            "phrase_idx": self.phrase_idx
        }
    
    def get_user(self, bot: TeleBot):
        if not self._user:
            self._user = bot.get_chat_member(self.user_id, self.user_id).user
        return self._user

class ObjectJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, Proposed):
            return o.to_json()
        if isinstance(o, t.User):
            return {"__class__": "User"} | o.to_dict()
        return super().default(o)

def object_hook(obj: dict[str]):
    if "__class__" in obj:
        cl = obj.pop("__class__")
        if cl == "Proposed":
            return Proposed(**obj)
        if cl == "User":
            return t.User(**obj)
        raise ValueError(f"Неизвестный класс: {cl}")
    return obj
