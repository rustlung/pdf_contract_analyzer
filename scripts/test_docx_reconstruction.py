import logging
from pathlib import Path

from src.api.documents.docx_reconstruction_service import DocxReconstructionService


SAMPLE_TEXT = """ДОГОВОР ОКАЗАНИЯ УСЛУГ

г. Москва
01.03.2026

1. ПРЕДМЕТ ДОГОВОРА
1.1. Исполнитель обязуется оказать услуги, а Заказчик обязуется принять и оплатить их.
1.2. Перечень услуг определяется приложением к договору.

2. ПОРЯДОК РАСЧЕТОВ
- Оплата производится ежемесячно.
- Срок оплаты: до 5 числа каждого месяца.

ПРОЧИЕ УСЛОВИЯ
Стороны признают юридическую силу документов, переданных по электронной почте.
"""


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    service = DocxReconstructionService()
    docx_bytes = service.generate_docx(SAMPLE_TEXT)

    output_path = Path("tmp/output_reconstructed.docx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(docx_bytes)

    print(f"Готово: {output_path.resolve()}")
    print(f"Размер файла: {len(docx_bytes)} bytes")


if __name__ == "__main__":
    main()
