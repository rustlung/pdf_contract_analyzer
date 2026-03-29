from dataclasses import dataclass, field


@dataclass(slots=True)
class MaskingResult:
    original_length: int
    masked_length: int
    masked_text: str
    replacements_count: int
    replacement_stats: dict[str, int]
    unique_companies_count: int = 0
    used_roles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    debug_samples: list[tuple[str, str]] = field(default_factory=list)
