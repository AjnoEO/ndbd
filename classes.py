import telebot.types as t

class Proposed:
    def __init__(self, user: t.User, phrase: str, msg_id: int, orig_msg_id: int, idx: int | None = None):
        self.user = user
        self.phrase = phrase
        self.msg_id = msg_id
        self.orig_msg_id = orig_msg_id
        self.idx = idx
