"""Program language: Polish or English.

Texts are written next to each other in the code: t("po polsku", "in English"). This way f-strings
with numbers behave the same in both languages and a missing translation is visible at once.

On the first start the language comes from the Windows interface language:
Polish Windows gives PL, anything else gives EN. Afterwards the choice in the app settings applies.
"""
import locale
import os

JEZYKI = {"pl": "Polski", "en": "English"}
JEZYK = "pl"


def ustaw(kod):
    global JEZYK
    JEZYK = kod if kod in JEZYKI else "en"


def t(pl, en):
    """Text in the current language."""
    return pl if JEZYK == "pl" else en


def jezyk_systemu():
    """'pl' when the Windows interface is Polish, 'en' in every other case."""
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "pl" if langid & 0x3FF == 0x15 else "en"  # 0x15 = LANG_POLISH
    except (AttributeError, OSError):
        pass
    # Outside Windows (tests): environment variables or the locale
    for nazwa in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        if os.environ.get(nazwa, "").lower().startswith("pl"):
            return "pl"
    try:
        return "pl" if (locale.getlocale()[0] or "").lower().startswith("pl") else "en"
    except ValueError:
        return "en"
