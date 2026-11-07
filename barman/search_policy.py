"""Pure routing for ambiguity and fresh facts; never decides user permissions."""
from dataclasses import dataclass
import re

POE = re.compile(r"\b(?:poe[12]?|пое[12]?|по[еэ]ш\w*|path\s+of\s+exile)\b", re.I)
FRESH = re.compile(r"когда|во\s+сколько|выход|выйд|старт|релиз|дат[ауы]|свеж|последн|следующ|ближайш|актуал|сейчас|сегодня|новост|патч|обнов|новая\s+лига|\b(?:when|latest|current|next|release|patch|today)\b", re.I)
EXPLICIT_SEARCH = re.compile(r"найди|поищи|погугл|проверь.*интернет", re.I)
FACT_TOPIC = re.compile(r"патч|обнов|верси|релиз|лиг[аиуы]|сезон|цен[ауы]|стоим|стоит|курс|погод|новост|расписан|старт|выйд|выход(?:ит|ят)|\b(?:price|version|patch|release|league|season|weather|news)\b", re.I)
QUESTION = re.compile(r"\b(?:когда|какая|какой|какие|какое|какова|сколько|почем|что|че|как|почему|зачем|где|when|what|why|how)\b|во\s+сколько", re.I)


@dataclass(frozen=True)
class SearchPolicy:
    requires_evidence: bool
    domains: tuple[str, ...] = ()
    clarification: str | None = None
    game: str | None = None


def search_policy(text: str, *, game_hint: str | None = None) -> SearchPolicy:
    text = (text or "").lower().replace("ё", "е")
    poe = bool(POE.search(text))
    diablo = bool(re.search(r"\b(?:diablo|диабло)\b", text))
    if not poe and not diablo:
        poe = game_hint in ("Path of Exile", "Path of Exile 2")
        diablo = game_hint == "Diablo IV"
    factual_question = bool(QUESTION.search(text) and FACT_TOPIC.search(text))
    fresh = factual_question or bool(FRESH.search(text) and (poe or diablo or FACT_TOPIC.search(text)))
    fresh = fresh or bool(QUESTION.search(text) and (poe or diablo))
    if not factual_question and re.search(r"анекдот|пошути|сочини|придумай.*(?:шутк|истори|стих)", text):
        fresh = False
    first = bool(re.search(r"(?:poe|пое|по[еэ]ш\w*|path\s+of\s+exile)\s*(?:1\b(?!\.\d)|один\b)|"
                           r"\bперв(?:ая|ую|ой)\s+(?:част[ььи]|poe|пое|по[еэ]ш\w*)\b", text))
    if poe:
        game = "Path of Exile" if first or (not POE.search(text) and game_hint == "Path of Exile") else "Path of Exile 2"
    else:
        game = "Diablo IV" if diablo else None
    release_question = bool(re.search(r"когда|во\s+сколько|выйд|выходит|старт|when", text))
    event = bool(re.search(r"лиг|патч|обнов|сезон|релиз|полно[а-я]*|ранн[а-я]*\s+доступ|\b1\.0\b", text))
    clarification = None
    if poe and game == "Path of Exile 2" and release_question and not event:
        clarification = "Про новую лигу, обновление или полный релиз PoE 2?"
    if game is None and re.fullmatch(r"(?:а\s+)?(?:релиз\s+когда|когда\s+релиз)[?!. ]*", text.strip()):
        clarification = "Релиз какой игры?"
    domains = []
    if poe:
        domains.append("pathofexile.com")
        if game == "Path of Exile 2":
            domains.append("pathofexile2.com")
    if diablo:
        domains.extend(("news.blizzard.com", "diablo4.blizzard.com"))
    return SearchPolicy(fresh or bool(EXPLICIT_SEARCH.search(text)), tuple(domains), clarification, game)
