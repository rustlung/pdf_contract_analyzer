import logging
import re
from dataclasses import dataclass

from src.shared.masking.masking_types import MaskingResult

logger = logging.getLogger(__name__)

ROLE_WORDS = ("Заказчик", "Исполнитель", "Подрядчик", "Покупатель", "Продавец")

# 1) Strict format entities first
STRICT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+7|8)[\s\-()]*(?:\d[\s\-()]*){10}(?!\w)")),
    ("INN", re.compile(r"\b(?:\d{10}|\d{12})\b")),
    ("KPP", re.compile(r"\b\d{9}\b")),
    ("OGRN", re.compile(r"\b\d{13}\b")),
    ("OGRNIP", re.compile(r"\b\d{15}\b")),
    (
        "PASSPORT",
        re.compile(
            r"(?i)\bпаспорт(?:\s*[:\-])?(?:\s+серия)?\s*\d{2}\s*\d{2}\s*(?:№|N)?\s*\d{6}\b"
        ),
    ),
    (
        "ACCOUNT",
        re.compile(r"(?i)\b(?:р/с|рс|расчетный\s+счет)\s*[:\-]?\s*\d{20}\b"),
    ),
    (
        "KS",
        re.compile(r"(?i)\b(?:к/с|кс|корреспондентский\s+счет)\s*[:\-]?\s*\d{20}\b"),
    ),
    ("BIK", re.compile(r"(?i)\bбик\s*[:\-]?\s*\d{9}\b")),
]

# 2) Then organizations / person / address (conservative)
ORGANIZATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "COMPANY",
        re.compile(
            r"\b(?:ООО|АО|ПАО|ЗАО|НАО)\s*(?:\"[^\n\".,;:]{1,80}\"|«[^\n».,;:]{1,80}»|[А-ЯЁA-Z][^\n,;:.]{1,60})"
        ),
    ),
    (
        "COMPANY",
        re.compile(r"\bИП\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}\b"),
    ),
]

PERSON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "PERSON",
        re.compile(
            r"\b[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){2}\b"
        ),
    ),
    (
        "PERSON",
        re.compile(
            r"\b[А-ЯЁ][а-яё]+(?:ой|ий|ая|яя|ина|ина|ов|ев|ин)\s+[А-ЯЁ][а-яё]+(?:ы|и|а|я)?\s+[А-ЯЁа-яё]+(?:вич|вна|вны|евич|евна|евны|ович|овна|овны|ич|ична|ичны|оглы|кызы)\b"
        ),
    ),
]

ADDRESS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ADDRESS",
        re.compile(
            r"(?i)(\bадрес\s*:\s*)((?:\d{6},\s*)?.{10,220}?)(?=\s+(?:именуем|действующ|с\s+одной\s+стороны)\b|[\n;]|$)"
        ),
    ),
    (
        "ADDRESS",
        re.compile(
            r"(?i)(\bзарегистрирован(?:ный|ная|ного|ной|о)?\s+по\s+адресу\s*:\s*)((?:\d{6},\s*)?.{10,220}?)(?=\s+(?:именуем|действующ|с\s+одной\s+стороны)\b|[\n;]|$)"
        ),
    ),
    (
        "ADDRESS",
        re.compile(
            r"(?i)(\bадрес\s+регистрации\s*:\s*)((?:\d{6},\s*)?.{10,220}?)(?=\s+(?:именуем|действующ|с\s+одной\s+стороны)\b|[\n;]|$)"
        ),
    ),
]


TYPE_PRIORITIES: dict[str, int] = {
    "PASSPORT": 500,
    "ACCOUNT": 450,
    "KS": 440,
    "BIK": 430,
    "COMPANY": 400,
    "PERSON": 300,
    "ADDRESS": 200,
    "INN": 170,
    "KPP": 160,
    "OGRN": 150,
    "OGRNIP": 140,
    "PHONE": 130,
    "EMAIL": 120,
}


@dataclass(slots=True)
class MatchSpan:
    start: int
    end: int
    entity_type: str
    value: str
    priority: int


def _collect_matches(text: str) -> list[MatchSpan]:
    matches: list[MatchSpan] = []

    for entity_type, pattern in STRICT_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(0)
            value = match.group(0).strip()
            if value:
                matches.append(
                    MatchSpan(
                        start=start,
                        end=end,
                        entity_type=entity_type,
                        value=value,
                        priority=TYPE_PRIORITIES.get(entity_type, 0),
                    )
                )

    for entity_type, pattern in ORGANIZATION_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(0)
            value = match.group(0).strip()
            if value:
                matches.append(
                    MatchSpan(
                        start=start,
                        end=end,
                        entity_type=entity_type,
                        value=value,
                        priority=TYPE_PRIORITIES.get(entity_type, 0),
                    )
                )

    for entity_type, pattern in PERSON_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(0)
            value = match.group(0).strip()
            if value:
                matches.append(
                    MatchSpan(
                        start=start,
                        end=end,
                        entity_type=entity_type,
                        value=value,
                        priority=TYPE_PRIORITIES.get(entity_type, 0),
                    )
                )

    # For address patterns we only mask address value (group 2), not the prefix.
    for entity_type, pattern in ADDRESS_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span(2)
            value = match.group(2).strip()
            if value:
                matches.append(
                    MatchSpan(
                        start=start,
                        end=end,
                        entity_type=entity_type,
                        value=value,
                        priority=TYPE_PRIORITIES.get(entity_type, 0),
                    )
                )

    return matches


def _extract_roles(text: str) -> list[str]:
    detected_roles: list[str] = []
    for role in ROLE_WORDS:
        if re.search(rf"\b{role}\b", text, re.IGNORECASE):
            detected_roles.append(role)
    return detected_roles


def _spans_overlap(a: MatchSpan, b: MatchSpan) -> bool:
    return not (a.end <= b.start or b.end <= a.start)


def _resolve_overlaps(matches: list[MatchSpan]) -> list[MatchSpan]:
    # Higher priority first. For same priority keep longer match first.
    ranked = sorted(
        matches,
        key=lambda m: (-m.priority, -(m.end - m.start), m.start),
    )
    accepted: list[MatchSpan] = []

    for candidate in ranked:
        if any(_spans_overlap(candidate, chosen) for chosen in accepted):
            continue
        accepted.append(candidate)

    return accepted


def _mask_with_spans(
    text: str,
    spans: list[MatchSpan],
    replacement_stats: dict[str, int],
    debug_samples: list[tuple[str, str]] | None,
    max_debug_samples: int,
) -> tuple[str, dict[str, int], int]:
    mappings: dict[str, dict[str, str]] = {}
    counters: dict[str, int] = {}
    masked_text = text

    for span in sorted(spans, key=lambda s: s.start, reverse=True):
        type_map = mappings.setdefault(span.entity_type, {})
        token = type_map.get(span.value)
        if token is None:
            counters[span.entity_type] = counters.get(span.entity_type, 0) + 1
            token = f"{span.entity_type}_{counters[span.entity_type]}"
            type_map[span.value] = token

        if debug_samples is not None and len(debug_samples) < max_debug_samples:
            debug_samples.append((span.value, token))

        masked_text = masked_text[:span.start] + token + masked_text[span.end:]
        replacement_stats[span.entity_type] = replacement_stats.get(span.entity_type, 0) + 1

    unique_companies_count = len(mappings.get("COMPANY", {}))
    replacement_stats["COMPANY_UNIQUE"] = unique_companies_count
    replacement_stats["PERSON_UNIQUE"] = len(mappings.get("PERSON", {}))
    replacement_stats["ADDRESS_UNIQUE"] = len(mappings.get("ADDRESS", {}))
    return masked_text, replacement_stats, unique_companies_count


def mask_document_text(
    text: str,
    *,
    include_debug_samples: bool = False,
    max_debug_samples: int = 10,
) -> MaskingResult:
    logger.info("Masking pipeline started")

    original_length = len(text)
    notes: list[str] = []

    if original_length < 30:
        warning = "Input text is very short, masking quality may be limited."
        notes.append(warning)
        logger.warning(warning)

    if not text.strip():
        warning = "Input text is empty or whitespace-only."
        notes.append(warning)
        logger.warning(warning)

    used_roles = _extract_roles(text)

    spans = _collect_matches(text)
    non_overlapping_spans = _resolve_overlaps(spans)

    replacement_stats: dict[str, int] = {}
    debug_samples: list[tuple[str, str]] | None = [] if include_debug_samples else None

    masked_text, replacement_stats, unique_companies_count = _mask_with_spans(
        text,
        non_overlapping_spans,
        replacement_stats,
        debug_samples,
        max_debug_samples,
    )
    replacements_count = sum(
        value for key, value in replacement_stats.items() if not key.endswith("_UNIQUE")
    )

    logger.info(
        (
            "Masking pipeline finished: replacements_count=%s "
            "unique_companies_count=%s person_count=%s "
            "address_context_count=%s passport_count=%s account_count=%s ks_count=%s bik_count=%s replacement_stats=%s"
        ),
        replacements_count,
        unique_companies_count,
        replacement_stats.get("PERSON", 0),
        replacement_stats.get("ADDRESS", 0),
        replacement_stats.get("PASSPORT", 0),
        replacement_stats.get("ACCOUNT", 0),
        replacement_stats.get("KS", 0),
        replacement_stats.get("BIK", 0),
        replacement_stats,
    )

    return MaskingResult(
        original_length=original_length,
        masked_length=len(masked_text),
        masked_text=masked_text,
        replacements_count=replacements_count,
        replacement_stats=replacement_stats,
        unique_companies_count=unique_companies_count,
        used_roles=used_roles,
        notes=notes,
        debug_samples=debug_samples or [],
    )
