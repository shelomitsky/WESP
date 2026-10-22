"""Shared gettext domain for Python helpers and the Plasma widget."""
from functools import lru_cache
import gettext
import os
from pathlib import Path
import re

DOMAIN='plasma_applet_org.wledcontrol.desktop'
LOCALE=Path(__file__).resolve().parent/'locale'


@lru_cache(maxsize=16)
def translator(languages):
    return gettext.translation(DOMAIN,localedir=LOCALE,
                               languages=languages.split(':'),fallback=True)


def tr(message,*values):
    base=next((os.environ[key] for key in ('LC_ALL','LC_MESSAGES','LANG')
               if os.environ.get(key)),'C')
    languages=('en' if base.upper() in ('C','POSIX') or base.upper().startswith('C.')
               else os.environ.get('LANGUAGE') or base)
    text=translator(languages).gettext(message)
    # Use the same numbered placeholders as KDE. Values are inserted once and
    # cannot become new placeholders or translation source strings.
    def replace(match):
        index=int(match[1])-1
        return str(values[index]) if 0<=index<len(values) else match[0]
    return re.sub(r'%([1-9][0-9]*)',replace,text)
