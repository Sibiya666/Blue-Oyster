"""Pure routing for ambiguity and fresh facts; never decides user permissions."""
from dataclasses import dataclass
import re

POE = re.compile(r"\b(?:poe[12]?|пое[12]?|по[еэ]ш\w*|path\s+of\s+exile)\b", re.I)
FRESH = re.compile(r"когда|во\s+сколько|выход|выйд|старт|релиз|дат[ауы]|свеж|последн|следующ|ближайш|актуал|сейчас|сегодня|новост|патч|обнов|новая\s+лига|\b(?:when|latest|current|next|release|patch|today)\b", re.I)
EXPLICIT_SEARCH = re.compile(r"найди|поищи|погугл|проверь.*интернет", re.I)
FACT_TOPIC = re.compile(r"патч|обнов|верси|релиз|лиг[аиуы]|сезон|цен[ауы]|стоим|стоит|курс|погод|новост|расписан|старт|выйд|выход(?:ит|ят)|\b(?:price|version|patch|release|league|season|weather|news)\b", re.I)
QUESTION = re.compile(r"\b(?:когда|какая|какой|какие|какое|какова|сколько|почем|что|when|what)\b|во\s+сколько|how\s+much", re.I)


@dataclass(frozen=True)
class SearchPolicy:
    requires_evidence: bool
    domains: tuple[str, ...] = ()
    clarification: str | None = None


def search_policy(text: str) -> SearchPolicy:
    text = (text or "").lower().replace("ё", "е")
    poe = bool(POE.search(text))
    diablo = bool(re.search(r"\b(?:diablo|диабло)\b", text))
    factual_question = bool(QUESTION.search(text) and FACT_TOPIC.search(text))
    fresh = factual_question or bool(FRESH.search(text) and (poe or diablo or FACT_TOPIC.search(text)))
    if not factual_question and re.search(r"анекдот|пошути|сочини|придумай.*(?:шутк|истори|стих)", text):
        fresh = False
    explicit_poe = bool(re.search(r"path\s+of\s+exile|(?:poe|пое|по[еэ]ш\w*)\s*[12]\b|"
                                  r"\b(?:первая|первую|вторая|вторую)\s+(?:част[ььи]|poe|пое)\b", text))
    clarification = "Про PoE 1, PoE 2 или новую лигу?" if poe and fresh and not explicit_poe else None
    domains = []
    if fresh and poe:
        domains.extend(("pathofexile.com", "pathofexile2.com"))
    if fresh and diablo:
        domains.extend(("news.blizzard.com", "diablo4.blizzard.com"))
    return SearchPolicy(fresh or bool(EXPLICIT_SEARCH.search(text)), tuple(domains), clarification)
