import re


_DOC_TITLE_RE = re.compile(r"^\s*ДОГОВОР\b.*$", re.IGNORECASE)
_NUMBERING_RE = re.compile(r"^\s*\d+(\.\d+)*[\.)]?\s*.*$")
_BULLET_RE = re.compile(r"^\s*[-—]\s+.+$")
_ALL_CAPS_RE = re.compile(r"^[^a-zа-я]*[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9\s\"'().,:;-]{5,}$")
_REQUISITE_HINT_RE = re.compile(
    r"^\s*(ИНН|КПП|ОГРН|ОГРНИП|БИК|Р/С|К/С|РЕКВИЗИТ|АДРЕС|ПАСПОРТ|БАНК)\b",
    re.IGNORECASE,
)


def _is_structural_line(line: str) -> bool:
    if not line.strip():
        return True
    return bool(
        _DOC_TITLE_RE.match(line)
        or _NUMBERING_RE.match(line)
        or _BULLET_RE.match(line)
        or _ALL_CAPS_RE.match(line)
    )


def _is_requisite_line(line: str) -> bool:
    return bool(_REQUISITE_HINT_RE.match(line.strip()))


def _should_join(prev: str, current: str) -> bool:
    if not prev:
        return False
    if _is_structural_line(current):
        return False
    if _is_requisite_line(prev) or _is_requisite_line(current):
        return True
    if prev.endswith((".", "!", "?", ";", ":")):
        return False
    if len(prev.split()) <= 2:
        return True
    if current and current[0].islower():
        return True
    return False


def normalize_extracted_text_for_docx(raw_text: str) -> list[str]:
    """
    Normalize extracted text from PDF/DOCX before DOCX reconstruction.

    Returns a list of normalized paragraph-like lines.
    Empty string item means explicit paragraph break.
    """
    if not raw_text or not raw_text.strip():
        return []

    lines = raw_text.splitlines()
    normalized: list[str] = []
    buffer = ""

    def flush_buffer() -> None:
        nonlocal buffer
        if buffer.strip():
            normalized.append(buffer.strip())
        buffer = ""

    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            flush_buffer()
            if normalized and normalized[-1] != "":
                normalized.append("")
            continue

        if _is_structural_line(line):
            flush_buffer()
            normalized.append(line)
            continue

        if _should_join(buffer, line):
            buffer = f"{buffer} {line}".strip()
            continue

        flush_buffer()
        buffer = line

    flush_buffer()

    # Remove leading/trailing and duplicate paragraph separators
    compact: list[str] = []
    for item in normalized:
        if item == "" and (not compact or compact[-1] == ""):
            continue
        compact.append(item)

    if compact and compact[-1] == "":
        compact.pop()

    return compact
