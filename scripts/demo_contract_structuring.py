import argparse
import logging
from dataclasses import asdict
from pathlib import Path

from src.api.documents import process_document
from src.api.documents.docx_generator import generate_contract_docx
from src.llm.contract_structuring_service import ContractStructuringService
from src.shared.masking import mask_document_text


def run_demo(input_path: Path, output_docx: Path) -> None:
    file_bytes = input_path.read_bytes()

    processing_result = process_document(
        file_bytes=file_bytes,
        filename=input_path.name,
        mime_type=None,
    )
    print(
        f"[1/4] Документ обработан: method={processing_result.extraction_method}, "
        f"pages={processing_result.pages_count}, text_length={len(processing_result.raw_text)}"
    )

    masking_result = mask_document_text(processing_result.raw_text)
    print(
        f"[2/4] Деперсонализация завершена: replacements={masking_result.replacements_count}, "
        f"masked_length={masking_result.masked_length}"
    )

    structuring_service = ContractStructuringService()
    structured_data = structuring_service.structure_contract(masking_result.masked_text)
    print("[3/4] LLM структурирование завершено")
    print(asdict(structured_data))

    docx_bytes = generate_contract_docx(structured_data)
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    output_docx.write_bytes(docx_bytes)
    print(f"[4/4] DOCX сгенерирован: {output_docx} ({len(docx_bytes)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo: document pipeline -> masking -> LLM structuring -> DOCX generation"
    )
    parser.add_argument("input_file", type=Path, help="Path to source PDF/DOCX file")
    parser.add_argument(
        "--output-docx",
        type=Path,
        default=Path("tmp/structured_contract_demo.docx"),
        help="Output DOCX path",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    run_demo(args.input_file, args.output_docx)


if __name__ == "__main__":
    main()
