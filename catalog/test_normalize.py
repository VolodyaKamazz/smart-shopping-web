from django.test import SimpleTestCase

from catalog.normalize import (MAX_MATCH_KEY_LEN, build_match_key, build_search_text, is_valid_gtin, normalize_brand,
                               normalize_text, valid_gtins)


class NormalizeBrandTests(SimpleTestCase):
    def test_cases(self):
        cases = {
            "Samsung": "samsung", "XIAOMI": "xiaomi", "  Apple  ": "apple",
            "Hewlett-Packard": "hewlett packard", "hewlett packard": "hewlett packard",
            "Dr. Dre": "dr dre", "Т-Банк": "т банк", "ASUS  ROG": "asus rog", "": "", "---": "",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(normalize_brand(name), expected)

    def test_is_idempotent(self):
        once = normalize_brand("Hewlett-Packard  Inc.")
        self.assertEqual(normalize_brand(once), once)


class NormalizeTextTests(SimpleTestCase):
    def test_cases(self):
        cases = {
            "Galaxy S24 8/256GB": "galaxy s24 8 256gb", "iPad 10.9 (10-го поколения)": "ipad 10 9 10 го поколения",
            "  WH-1000XM5 ": "wh 1000xm5", "Galaxy S24+": "galaxy s24 plus", "Galaxy S24 +": "galaxy s24 plus",
            "Galaxy S24 Plus": "galaxy s24 plus", "": "",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize_text(text), expected)

    def test_plus_keeps_models_apart(self):
        self.assertNotEqual(normalize_text("Galaxy S24+"), normalize_text("Galaxy S24"))

    def test_is_idempotent(self):
        once = normalize_text("Galaxy S24+ 12/512GB")
        self.assertEqual(normalize_text(once), once)


class BuildMatchKeyTests(SimpleTestCase):
    def test_key_of_brand_and_model(self):
        self.assertEqual(build_match_key("Samsung", "Galaxy S24 8/256GB"), "samsung|galaxy s24 8 256gb")

    def test_case_and_punctuation_do_not_matter(self):
        self.assertEqual(build_match_key("SAMSUNG", "galaxy  s24 8-256gb"),
                         build_match_key("Samsung", "Galaxy S24 8/256GB"))

    def test_different_models_have_different_keys(self):
        keys = {build_match_key("Samsung", model) for model in
                ("Galaxy S24 8/256GB", "Galaxy S24+ 8/256GB", "Galaxy S24 8/512GB")}
        self.assertEqual(len(keys), 3)

    def test_brand_is_part_of_the_key(self):
        self.assertNotEqual(build_match_key("Samsung", "X1"), build_match_key("Sony", "X1"))

    def test_no_key_without_brand_or_model(self):
        for vendor, model in (("", "Galaxy"), ("Samsung", ""), ("---", "Galaxy"), ("Samsung", "***")):
            with self.subTest(vendor=vendor, model=model):
                self.assertEqual(build_match_key(vendor, model), "")

    def test_no_key_when_it_does_not_fit_the_field(self):
        self.assertEqual(build_match_key("Samsung", "a" * MAX_MATCH_KEY_LEN), "")
        self.assertNotEqual(build_match_key("Samsung", "a" * 100), "")


class BuildSearchTextTests(SimpleTestCase):
    def test_words_are_normalized_unique_and_padded(self):
        text = build_search_text("Смартфон Samsung Galaxy S24 8/256GB (SM-S921B)", "Samsung",
                                 "Galaxy S24 8/256GB", "SM-S921B")
        self.assertEqual(text, " смартфон samsung galaxy s24 8 256gb sm s921b ")

    def test_whole_word_can_be_found_by_padding(self):
        text = build_search_text("Galaxy S245")
        self.assertIn(" s245 ", text)
        self.assertNotIn(" s24 ", text)

    def test_empty(self):
        self.assertEqual(build_search_text("", "---"), "")


class GtinTests(SimpleTestCase):
    VALID = ("4006381333931", "73513537", "036000241457", "036000291452", "5012345678900", "5012345674216",
             "6291041500213", "5901234123457", "96385074", "12345678901231")

    def test_valid_codes(self):
        for code in self.VALID:
            with self.subTest(code=code):
                self.assertTrue(is_valid_gtin(code))

    def test_wrong_check_digit(self):
        for code in self.VALID:
            wrong = code[:-1] + str((int(code[-1]) + 1) % 10)
            with self.subTest(code=wrong):
                self.assertFalse(is_valid_gtin(wrong))

    def test_wrong_length_or_symbols(self):
        for code in ("", "123", "40063813339311", "400638133393", "400638133393a", "4006 3813 33931", "٤٠٠٦٣٨١٣٣٣٩٣١"):
            with self.subTest(code=code):
                self.assertFalse(is_valid_gtin(code))

    def test_valid_gtins_keep_order_and_drop_invalid(self):
        self.assertEqual(valid_gtins(["1", "5901234123457", "4006381333932", "4006381333931"]),
                         ("5901234123457", "4006381333931"))
        self.assertEqual(valid_gtins(()), ())