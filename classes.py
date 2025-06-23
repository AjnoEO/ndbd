from json import JSONEncoder
import telebot.types as t

class Proposed:
    def __init__(self, user: t.User, phrase: str, msg_id: int, orig_msg_id: int, phrase_idx: int | None = None):
        if isinstance(user, str): user = t.User.de_json(user)
        self.user = user
        self.phrase = phrase
        self.msg_id = msg_id
        self.orig_msg_id = orig_msg_id
        self.phrase_idx = phrase_idx
    
    def to_json(self):
        return {
            "__class__": "Proposed",
            "user": self.user.to_dict() | {"__class__": "User"},
            "phrase": self.phrase,
            "msg_id": self.msg_id,
            "orig_msg_id": self.orig_msg_id,
            "phrase_idx": self.phrase_idx
        }

class ProposedJSONENcoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, Proposed):
            return o.to_json()
        return super().default(o)

def proposed_hook(obj: dict[str]):
    if "__class__" in obj:
        cl = obj.pop("__class__")
        if cl == "Proposed":
            return Proposed(**obj)
        if cl == "User":
            return t.User(**obj)
        raise ValueError(f"Неизвестный класс: {cl}")
    return obj
