"""Translation helpers for strings that Blender cannot translate on its own.

Blender translates RNA strings automatically: property ``name`` / ``description``,
``EnumProperty`` item names, operator ``bl_label`` / ``bl_description`` are looked up in
the add-on translation dict (registered in :mod:`__init__`).  Strings drawn by Python
code are **not** translated on the way to the screen:

* ``layout.label(text=...)`` / ``layout.operator(..., text=...)``;
* the HUD, which paints text with ``blf``.

Those go through :func:`t`.  Dynamic messages must be translated **before** formatting
(:func:`tfmt`): building a sentence with an f-string first would hand the translator a
different msgid every time, so it could never be translated.

Keep msgids in English.  A translation is optional: without one the msgid is shown,
which is why every user-visible string in this add-on is written in English in source.
"""

from __future__ import annotations

import bpy

__all__ = ["t", "tfmt"]


def t(msgid: str) -> str:
    """Translate an interface string (returns ``msgid`` when there is no translation)."""
    if not msgid:
        return msgid
    try:
        return bpy.app.translations.pgettext_iface(msgid)
    except (AttributeError, RuntimeError):
        return msgid


def tfmt(msgid: str, **values) -> str:
    """Translate, then fill in placeholders: ``tfmt("Level {level}", level=3)``.

    Translators keep the ``{name}`` placeholders; the format call happens afterwards, so
    word order can change freely between languages.
    """
    return t(msgid).format(**values)
