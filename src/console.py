from __future__ import annotations

import sys


def configure_console() -> None:
    """Force stdout/stderr en UTF-8 pour éviter le crash cp1252 sur les emojis.

    Windows Titre par défaut à l'encodage cp1252 : un contenu généré avec des
    emojis (ex. ✨ \u2728) fait exploser les `print(...)` du CLI et du serveur.
    On reconfigue en UTF-8 avec repli « replace » : la sortie ne plante jamais,
    elle affiche les caractères non représentables sous la forme de �.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass