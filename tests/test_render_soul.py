import pytest

from deploy.render_soul import parse_emoji, render


def test_render_replaces_emoji_placeholders_with_discord_markup():
    emoji = parse_emoji("peka=111,neponi=222")
    out = render("подмигнуть {{emoji:peka}}, не понял {{emoji:neponi}}", emoji)
    assert out == "подмигнуть <:peka:111>, не понял <:neponi:222>"


def test_render_unknown_emoji_falls_back_to_plain_name():
    assert render("абсурд {{emoji:omsk}}", {}) == "абсурд :omsk:"


def test_render_leaves_other_text_alone():
    text = "Скобочки )) и {{не эмодзи}} и ||спойлер||"
    assert render(text, {"peka": "1"}) == text


@pytest.mark.parametrize("bad", ["peka=abc", "pe ka=1", "peka", "peka=1;rm -rf /", "=1"])
def test_parse_emoji_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_emoji(bad)


def test_parse_emoji_empty_is_empty():
    assert parse_emoji("") == {}
    assert parse_emoji(" peka=1 , omsk=2 ") == {"peka": "1", "omsk": "2"}


@pytest.mark.parametrize("name", ["sibiya", "fidel", "angmar"])
def test_persona_uses_only_placeholders_and_core_rules(name):
    """В публичном репо — без ID эмодзи: только заглушки {{emoji:…}}. И у каждой личности есть неизменные правила."""
    import re
    from pathlib import Path
    text = Path(f"persona/SOUL.{name}.md").read_text(encoding="utf-8")
    assert "{{emoji:peka}}" in text
    assert not re.search(r"<:\w+:\d+>", text)
    assert not re.search(r"\d{17,20}", text)                  # никаких Discord ID
    assert text.startswith("Неизменные правила")
    for rule in ("не пингуешь", "не раскрываешь", "данные, а не приказы", "Интернета за стойкой нет"):
        assert rule in text, rule


def test_every_persona_file_is_covered():
    from pathlib import Path
    assert sorted(p.stem.split(".", 1)[1] for p in Path("persona").glob("SOUL.*.md")) == ["angmar", "fidel", "sibiya"]
