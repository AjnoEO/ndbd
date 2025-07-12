class UserError(Exception):
    """Ошибки, вызванные неправильными действиями пользователей"""
    def __init__(self, *args, contact_note = True, reply_markup = None):
        super().__init__(*args)
        self.reply_markup = reply_markup
        self.contact_note = contact_note

def gram_number(number: int, sg: str, pauc: str, pl: str = None):
    if pl is None: pl = pauc
    if number // 10 % 10 == 1: return pl
    if number % 10 == 0: return pl
    if number % 10 == 1: return sg
    if number % 10 < 5: return pauc
    return pl