import argparse
import logging
from pathlib import Path

from src.api.documents.services.document_processing import process_document
from src.shared.masking import mask_document_text


def _load_text_from_input(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".pdf", ".docx"}:
        extraction = process_document(
            file_bytes=path.read_bytes(),
            filename=path.name,
        )
        return extraction.raw_text, extraction.extraction_method

    return path.read_text(encoding="utf-8"), "plain_text"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocuMind unified extraction+masking demo"
    )
    parser.add_argument("file_path", help="Path to input TXT, PDF, or DOCX file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    path = Path(args.file_path)
    text, source_method = _load_text_from_input(path)
    result = mask_document_text(text, include_debug_samples=True, max_debug_samples=10)

    print("input_file:", path.name)
    print("source_method:", source_method)
    print("original_length:", result.original_length)
    print("masked_length:", result.masked_length)
    print("replacements_count:", result.replacements_count)
    print("replacement_stats:", result.replacement_stats)
    print("debug_samples:", result.debug_samples)
    print("used_roles:", result.used_roles)
    print("notes:", result.notes)
    print("\n--- Masked text preview ---\n")
    print(result.masked_text[:1500])


if __name__ == "__main__":
    main()
