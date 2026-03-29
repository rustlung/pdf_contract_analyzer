import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

from src.api.documents import process_document
from src.llm.contract_comparison_service import (
    ContractComparisonError,
    ContractComparisonService,
)
from src.shared.masking import mask_document_text


DEFAULT_SAMPLE_1 = (
    "Договор оказания услуг между COMPANY_1 и COMPANY_2. "
    "Срок: 12 месяцев. Оплата: 100000 рублей ежемесячно до 5 числа. "
    "Исполнитель обязуется оказывать услуги по технической поддержке."
)

DEFAULT_SAMPLE_2 = (
    "Договор оказания услуг между COMPANY_1 и COMPANY_3. "
    "Срок: 24 месяца. Оплата: 120000 рублей ежемесячно до 10 числа. "
    "Исполнитель обязуется оказывать услуги по технической поддержке и сопровождению."
)


def _infer_mime(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return None


def _load_masked_text_from_document(path: Path) -> str:
    file_bytes = path.read_bytes()
    document_result = process_document(
        file_bytes=file_bytes,
        filename=path.name,
        mime_type=_infer_mime(path),
    )
    masking_result = mask_document_text(document_result.raw_text)
    logging.info(
        "Prepared masked text from document: file=%s extraction_method=%s used_ocr=%s text_length=%s replacements=%s",
        path.name,
        document_result.extraction_method,
        document_result.used_ocr,
        len(document_result.raw_text),
        masking_result.replacements_count,
    )
    return masking_result.masked_text


def _load_text_or_file(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    path = Path(value)
    if path.exists() and path.is_file():
        if path.suffix.lower() in {".pdf", ".docx"}:
            return _load_masked_text_from_document(path)
        return path.read_text(encoding="utf-8")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test LLM contract comparison with two masked texts."
    )
    parser.add_argument(
        "--text1",
        type=str,
        default=None,
        help="Masked text #1 or path to .txt/.pdf/.docx file",
    )
    parser.add_argument(
        "--text2",
        type=str,
        default=None,
        help="Masked text #2 or path to .txt/.pdf/.docx file",
    )
    args = parser.parse_args()

    text1 = _load_text_or_file(args.text1, DEFAULT_SAMPLE_1)
    text2 = _load_text_or_file(args.text2, DEFAULT_SAMPLE_2)

    logging.basicConfig(level=logging.INFO)
    service = ContractComparisonService()
    try:
        result = service.compare_contracts(text1, text2)
    except ContractComparisonError as exc:
        print(f"Contract comparison error: {exc}")
        return

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
