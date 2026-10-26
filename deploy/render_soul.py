"""Собрать SOUL.md для сервера: заглушки {{emoji:имя}} → эмодзи сервера <:имя:ID>.
ID эмодзи в публичном репо не храним — они приходят из секрета BARMAN_EMOJI («peka=ID,neponi=ID»).

Использование: python3 deploy/render_soul.py persona/SOUL.sibiya.md "$BARMAN_EMOJI" > SOUL.md
"""
from __future__ import annotations

import re
import sys

_PLACEHOLDER = re.compile(r"\{\{emoji:(\w+)\}\}")
_PAIR = re.compile(r"(\w+)=(\d+)")


def parse_emoji(spec: str) -> dict[str, str]:
    """«peka=1,omsk=2» → {"peka": "1", "omsk": "2"}. Мусор — ValueError (в выкатку не пускаем)."""
    out: dict[str, str] = {}
    for part in (p.strip() for p in (spec or "").split(",")):
        if not part:
            continue
        m = _PAIR.fullmatch(part)
        if not m:
            raise ValueError(f"BARMAN_EMOJI: ожидается имя=ID, получено {part!r}")
        out[m.group(1)] = m.group(2)
    return out


def render(text: str, emoji: dict[str, str]) -> str:
    """Заглушки → <:имя:ID>; эмодзи без ID → :имя: (просто текст, ничего не ломает)."""
    def sub(m: re.Match) -> str:
        name = m.group(1)
        return f"<:{name}:{emoji[name]}>" if name in emoji else f":{name}:"
    return _PLACEHOLDER.sub(sub, text)


if __name__ == "__main__":
    src, spec = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    with open(src, encoding="utf-8") as f:
        sys.stdout.write(render(f.read(), parse_emoji(spec)))
