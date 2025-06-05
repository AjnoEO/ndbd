class UserError(Exception):
    """Ошибки, вызванные неправильными действиями пользователей"""
    def __init__(self, *args, contact_note = True, reply_markup = None):
        super().__init__(*args)
        self.reply_markup = reply_markup
        self.contact_note = contact_note