GTIN_LENGTHS = (8, 12, 13, 14)
MAX_MATCH_KEY_LEN = 300


def normalize_brand(name: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in name.lower()).split())


def normalize_text(text: str) -> str:
    return normalize_brand(text.replace("+", " plus "))


def build_match_key(vendor: str, model: str) -> str:
    brand, model = normalize_brand(vendor), normalize_text(model)
    key = f"{brand}|{model}"
    return key if brand and model and len(key) <= MAX_MATCH_KEY_LEN else ""


def build_search_text(*parts: str) -> str:
    words = dict.fromkeys(normalize_text(" ".join(parts)).split())
    return f" {' '.join(words)} " if words else ""


def is_valid_gtin(code: str) -> bool:
    if not (code.isascii() and code.isdigit() and len(code) in GTIN_LENGTHS):
        return False
    digits = [int(ch) for ch in reversed(code)]
    total = sum(digit * (3 if index % 2 == 0 else 1) for index, digit in enumerate(digits[1:]))
    return (10 - total % 10) % 10 == digits[0]


def valid_gtins(barcodes) -> tuple:
    return tuple(code for code in barcodes if is_valid_gtin(code))