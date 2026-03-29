import unittest

from src.shared.masking import mask_document_text


class TestMaskingPipeline(unittest.TestCase):
    def test_masking_keeps_meaningful_sentences(self) -> None:
        text = (
            "Стороны согласовали порядок оплаты в течение 5 рабочих дней.\n"
            "Заказчик обязан предоставить документы не позднее 10 числа.\n"
            "Настоящий договор действует до полного исполнения обязательств."
        )
        result = mask_document_text(text)
        self.assertIn(
            "Стороны согласовали порядок оплаты в течение 5 рабочих дней.",
            result.masked_text,
        )
        self.assertIn(
            "Настоящий договор действует до полного исполнения обязательств.",
            result.masked_text,
        )

    def test_masks_inn_company_and_person_with_context(self) -> None:
        text = (
            'Заказчик: ООО "Ромашка".\n'
            "ИНН 7701234567, КПП 770101001.\n"
            "Ответственный: Иванов Иван Иванович."
        )
        result = mask_document_text(text)
        self.assertIn("INN_1", result.masked_text)
        self.assertIn("COMPANY_1", result.masked_text)
        self.assertIn("PERSON_1", result.masked_text)
        self.assertIn("Заказчик:", result.masked_text)
        self.assertIn("Ответственный:", result.masked_text)
        self.assertNotIn("Иванов Иван Иванович", result.masked_text)

    def test_debug_samples_kept_in_memory_only(self) -> None:
        text = "Email: test@example.com, Телефон: +7 999 123 45 67"
        result = mask_document_text(text, include_debug_samples=True, max_debug_samples=3)
        self.assertGreaterEqual(len(result.debug_samples), 1)
        self.assertLessEqual(len(result.debug_samples), 3)

    def test_company_mapping_uses_stable_tokens(self) -> None:
        text = (
            'ООО "Ромашка" заключило договор с АО "Вектор". '
            'Позже ООО "Ромашка" направило акт.'
        )
        result = mask_document_text(text)
        self.assertIn("COMPANY_1", result.masked_text)
        self.assertIn("COMPANY_2", result.masked_text)
        self.assertEqual(result.masked_text.count("COMPANY_1"), 2)
        self.assertEqual(result.unique_companies_count, 2)

    def test_person_full_name_masked_without_tail(self) -> None:
        text = "Арендатор: Морозов Дмитрий Николаевич. Поручитель: Петровой Анны Сергеевны."
        result = mask_document_text(text)
        self.assertIn("PERSON_1", result.masked_text)
        self.assertIn("PERSON_2", result.masked_text)
        self.assertNotIn("Николаевич", result.masked_text)
        self.assertNotIn("Сергеевны", result.masked_text)
        self.assertIn("Арендатор:", result.masked_text)
        self.assertIn("Поручитель:", result.masked_text)
        self.assertNotRegex(result.masked_text, r"PERSON_\d+\s+[А-ЯЁа-яё]+")

    def test_masks_passport_and_bank_requisites(self) -> None:
        text = (
            "Паспорт: 40 15 № 837621.\n"
            "Р/с: 40817810855001234567, БИК: 044525225, К/с: 30101810400000000225."
        )
        result = mask_document_text(text)
        self.assertIn("PASSPORT_1", result.masked_text)
        self.assertIn("ACCOUNT_1", result.masked_text)
        self.assertIn("BIK_1", result.masked_text)
        self.assertIn("KS_1", result.masked_text)
        self.assertIn("Паспорт:", result.masked_text)
        self.assertIn("Р/с:", result.masked_text)

    def test_masks_address_in_explicit_context_only(self) -> None:
        text = (
            "зарегистрированный по адресу: 123456, г. Москва, ул. Ленина, д. 5, кв. 1\n"
            "Помещение по адресу г. Москва, ул. Тверская, д. 1 остается в тексте."
        )
        result = mask_document_text(text)
        self.assertIn("зарегистрированный по адресу: ADDRESS_1", result.masked_text)
        self.assertIn("Помещение по адресу г. Москва, ул. Тверская, д. 1", result.masked_text)

    def test_masks_registration_address_and_keeps_legal_tail(self) -> None:
        text = (
            "Адрес регистрации: 123456, г. Москва, ул. Пушкина, д. 12, кв. 3, "
            "именуемый в дальнейшем Наниматель, с одной стороны."
        )
        result = mask_document_text(text)
        self.assertIn("Адрес регистрации: ADDRESS_1", result.masked_text)
        self.assertIn("именуемый в дальнейшем Наниматель, с одной стороны.", result.masked_text)

    def test_no_overlap_artifacts_after_masking(self) -> None:
        text = (
            "Арендатор: Морозов Дмитрий Николаевич, зарегистрированный по адресу: "
            "123456, г. Москва, ул. Ленина, д. 5, кв. 1."
        )
        result = mask_document_text(text)
        self.assertNotRegex(result.masked_text, r"PERSON_\d+\s+[А-ЯЁа-яё]")
        self.assertNotRegex(result.masked_text, r"ADDRESS_\d+[А-ЯЁа-яё]")


if __name__ == "__main__":
    unittest.main()
