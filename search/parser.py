import re

STOP_WORDS = {
    "я", "мне", "хочу", "хотел", "хотела", "нужен", "нужна", "нужно", "нужны", "купить", "куплю",
    "найди", "найти", "подбери", "подобрать", "покажи", "ищу", "надо", "для", "и", "с", "со", "на",
    "в", "во", "по", "к", "у", "а", "но", "или", "же", "бы", "мой", "мою", "свой", "какой-нибудь",
    "пожалуйста", "плиз", "руб", "рубль", "рубля", "рублей", "р", "₽", "руб.", "тыс", "тысяч", "тысячи", "к",
}

BRAND_ALIASES = {
    "самсунг": "samsung",
    "эппл": "apple",
    "эпл": "apple",
    "сяоми": "xiaomi",
    "ксиаоми": "xiaomi",
    "поко": "poco",
    "хонор": "honor",
    "хуавей": "huawei",
    "оппо": "oppo",
    "виво": "vivo",
    "леново": "lenovo",
    "асус": "asus",
    "эйсер": "acer",
    "сони": "sony",
    "джейбиэл": "jbl",
}

MODEL_HINTS = {
    "айфон": ("iphone", "apple"),
    "iphone": ("iphone", "apple"),
    "макбук": ("macbook", "apple"),
    "macbook": ("macbook", "apple"),
    "аирподс": ("airpods", "apple"),
    "airpods": ("airpods", "apple"),
    "галакси": ("galaxy", "samsung"),
    "galaxy": ("galaxy", "samsung"),
    "редми": ("redmi", "xiaomi"),
    "redmi": ("redmi", "xiaomi"),
}

MAX_MARKERS = r"(?:до|не\s+дороже|дешевле|максимум|не\s+более|не\s+больше|в\s+пределах|за|бюджет)"
MIN_MARKERS = r"(?:от|дороже|минимум|не\s+менее|не\s+меньше|не\s+дешевле)"
NUMBER = r"(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?"
UNIT = r"(?:\s*(к|тыс\.?|тысяч[и]?|млн\.?|миллион[аов]*)(?![а-яa-z]))?"
CURRENCY = r"(?:\s*(?:₽|руб(?:лей|ля|\.)?|р\b\.?))?"

PRICE_RE = re.compile(
    rf"(?<![\w-])(?P<marker>{MAX_MARKERS}|{MIN_MARKERS})\s+{NUMBER}{UNIT}{CURRENCY}",
    re.IGNORECASE,
)
MAX_RE = re.compile(rf"^{MAX_MARKERS}$", re.IGNORECASE)

ENDINGS = (
    "ами", "ями", "ов", "ев", "ей", "ах", "ях", "ам", "ям", "ом", "ем", "ой", "ий", "ый", "ая",
    "ое", "ые", "ие", "ую", "юю", "ы", "и", "а", "я", "у", "ю", "е", "о", "ь",
)

TOKEN_RE = re.compile(r"[\w₽]+(?:[-.][\w]+)*", re.UNICODE)


def stem(word):
    word = word.lower().replace("ё", "е")
    for ending in sorted(ENDINGS, key=len, reverse=True):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def tokenize(text):
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _multiplier(unit):
    if not unit:
        return 1
    unit = unit.lower()
    if unit.startswith("млн") or unit.startswith("миллион"):
        return 1_000_000
    return 1000


def _extract_prices(text):
    price_min = None
    price_max = None
    unit_max = None
    unit_min = None
    spans = []
    for m in PRICE_RE.finditer(text):
        digits = re.sub(r"[ \u00a0]", "", m.group(2))
        value = int(digits) * _multiplier(m.group(3))
        marker = re.sub(r"\s+", " ", m.group("marker").lower())
        if MAX_RE.match(marker):
            price_max = value
            unit_max = m.group(3)
        else:
            price_min = value
            unit_min = m.group(3)
        spans.append(m.span())
    if price_min is not None and price_max is not None and unit_max and not unit_min and price_min < 1000:
        price_min *= _multiplier(unit_max)
    if price_min is not None and price_max is not None and price_min > price_max:
        price_min, price_max = price_max, price_min
    return price_min, price_max, spans


def _cut(text, spans):
    parts = []
    last = 0
    for start, end in sorted(spans):
        parts.append(text[last:start])
        last = end
    parts.append(text[last:])
    return " ".join(parts)


def _find_brand(tokens, brands):
    index = {}
    for b in brands:
        index[b["normalized_name"].lower()] = b["normalized_name"]
        index[b["name"].lower()] = b["normalized_name"]
    for pos, token in enumerate(tokens):
        key = BRAND_ALIASES.get(token, token)
        if key in index:
            return index[key], pos
    return None, None


def _find_category(tokens, categories):
    stems = [stem(t) for t in tokens]
    best = None
    for cat in categories:
        terms = [cat["name"]] + [k for k in cat.get("keywords", "").split(",")]
        for term in terms:
            words = [stem(w) for w in tokenize(term)]
            if not words:
                continue
            positions = []
            for w in words:
                if w in stems:
                    positions.append(stems.index(w))
                else:
                    positions = []
                    break
            if positions:
                size = len(words)
                if best is None or size > best[0]:
                    best = (size, cat["slug"], positions)
    if best is None:
        return None, []
    return best[1], best[2]


def parse_query(text, categories, brands):
    text = (text or "").strip()
    price_min, price_max, spans = _extract_prices(text)
    rest = _cut(text, spans)
    tokens = tokenize(rest)

    used = set()
    brand, brand_pos = _find_brand(tokens, brands)
    if brand_pos is not None:
        used.add(brand_pos)
    category, cat_positions = _find_category(tokens, categories)
    used.update(cat_positions)

    known = {b["normalized_name"] for b in brands}
    if brand is None:
        for token in tokens:
            hint = MODEL_HINTS.get(token)
            if hint and hint[1] in known:
                brand = hint[1]
                break

    keywords = []
    for pos, token in enumerate(tokens):
        if pos in used or token in STOP_WORDS:
            continue
        if token in MODEL_HINTS:
            token = MODEL_HINTS[token][0]
        if len(token) < 2 and not token.isdigit():
            continue
        keywords.append(token)

    return {
        "category": category,
        "brand": brand,
        "price_min": price_min,
        "price_max": price_max,
        "keywords": keywords,
    }
