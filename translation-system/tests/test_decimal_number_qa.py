"""Tests the actual production number-QA functions without Google dependencies.

Extract only their AST definitions, so the tests run on the lightweight CI
runner while exercising the unmodified production source.
"""
import ast
from decimal import Decimal, InvalidOperation
import re
from pathlib import Path
import unittest
import unicodedata


def _function(name, tree):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing production function: {name}")


source = Path(__file__).resolve().parents[1] / "gemini_multi_production_runner.py"
tree = ast.parse(source.read_text(encoding="utf8"))
names = (
    "normalize_unicode_digits",
    "_decimal_localized_number",
    "_locale_number_issues",
    "translated_number_issues",
)
extract = ast.Module(body=[_function(name, tree) for name in names], type_ignores=[])
namespace = {
    "re": re, "Decimal": Decimal, "InvalidOperation": InvalidOperation,
    "unicodedata": unicodedata,
}
exec(compile(extract, str(source), "exec"), namespace)
namespace["_LOCALE_SOURCE_NUMBER"] = re.compile(
    r"(?<![\w])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w])"
)
namespace["_LOCALE_TARGET_NUMBER"] = re.compile(
    r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])"
)
check = namespace["translated_number_issues"]


class DecimalNumberQATests(unittest.TestCase):
    def test_italian_portuguese_decimal_commas_are_valid(self):
        for lang in ("it", "pt"):
            self.assertEqual(check("The value is 2.5.", "Il valore è 2,5.", lang), [])
            self.assertEqual(check("The value is 2.5.", "O valor é 2,50.", lang), [])
            self.assertEqual(check("It is 2.5.", "Valor: 2.5", lang), [])

    def test_missing_and_wrong_values_still_fail(self):
        for lang in ("it", "pt"):
            for value in ("12,5", "25", "2.500", "no number", "2,6"):
                with self.subTest(lang=lang, value=value):
                    self.assertIn("missing_number:2.5", check("2.5", value, lang))

    def test_integer_not_confused_with_fraction(self):
        for lang in ("it", "pt"):
            self.assertIn("missing_number:2", check("2", "2,5", lang))
            self.assertEqual(check("2,500 visitors", "2.500 persone", lang), [])
            self.assertIn("missing_number:2,500", check("2,500", "2,5", lang))

    def test_number_cannot_be_hidden_as_substring(self):
        for lang in ("it", "pt"):
            self.assertIn("missing_number:2026", check("2026", "12026", lang))
            self.assertIn("missing_number:2.5", check("2.5", "12,5", lang))

    def test_existing_languages_keep_literal_check(self):
        self.assertIn("missing_number:2.5", check("2.5", "2,5", "en"))
        self.assertEqual(check("2.5", "2.5", "es"), [])


if __name__ == "__main__":
    unittest.main()
