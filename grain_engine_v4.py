from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional
from math import radians, sin, cos, asin, sqrt
from pathlib import Path
import json
import re


# ============================================================
# GRAIN ENGINE V4.0
# Единый движок закупки зерна
#
# Поток:
# речь фермера
# -> культура + объём + локация + качество
# -> геолокация
# -> расстояние до направлений
# -> логистика
# -> рыночная цена
# -> маржа
# -> рекомендуемая / максимальная цена фермеру
# -> БЕРЁМ / ТОРГУЕМСЯ / НЕ БЕРЁМ
#
# Рыночный прайс хранится отдельно:
# market_prices_YYYY-MM-DD.json
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PRICE_FILE = BASE_DIR / "market_prices_2026-09-08.json"
DEFAULT_LOCATION_CACHE = BASE_DIR / "locations_cache.json"

ROAD_FACTOR = 1.20

# Резервный курс используется только если JSON-прайс не содержит курс.
USD_RATE_FALLBACK = 44.70

# Минимальная/максимальная маржа, грн/т.
MARGINS = {
    "кукуруза": (300, 300),
    "пшеница": (300, 300),
    "ячмень": (300, 300),
    "рапс": (400, 500),
    "подсолнечник": (400, 500),
    "семечка": (400, 500),
    "соя": (400, 500),
    "горох": (300, 400),
}

# Логистика: от км, до км, минимум грн/т, максимум грн/т.
LOGISTICS = [
    (10, 50, 200, 300),
    (50, 100, 300, 550),
    (100, 150, 500, 700),
    (150, 200, 700, 850),
    (200, 250, 850, 1050),
    (250, 300, 1050, 1200),
    (300, 350, 1200, 1350),
    (350, 400, 1350, 1500),
    (400, 450, 1500, 1500),
    (450, 500, 1500, 1600),
    (500, 550, 1600, 1650),
    (550, 600, 1600, 1750),
    (600, 650, 1750, 1800),
    (650, 700, 1750, 1850),
    (700, 750, 1850, 1875),
    (750, 800, 1850, 1900),
    (800, 900, 2000, 2100),
]

# Известные координаты. Новые населённые пункты должны приходить
# из геокодера и записываться в locations_cache.json.
LOCATIONS = {
    "Грим'ячка, Хмельницкая обл.": (49.14083, 27.10167),
    "Гримячка, Хмельницкая обл.": (49.14083, 27.10167),
    "Грим'ячка": (49.14083, 27.10167),
    "Кропивницкий": (48.5106, 32.2656),
    "Чорнобаи, Черкасская обл.": (49.67037, 32.32336),
    "Киевская обл.": (50.38125, 30.52662),
    "Луцк": (50.74778, 25.32444),
    "Одесса": (46.4825, 30.7233),
    "Рени": (45.457, 28.284),
    "Измаил": (45.3493, 28.8408),
    "Львов": (49.8397, 24.0297),
    "Полтава": (49.5883, 34.5514),
    "Новая Одесса": (47.3078, 31.7851),
    "Баштанка": (47.406, 32.442),
    "Новый Буг": (47.683, 32.504),
    "Константиновка": (47.823, 30.715),
}

CROP_ALIASES = {
    "соя": "соя", "сої": "соя",
    "рапс": "рапс", "рапсу": "рапс", "ріпак": "рапс", "ріпаку": "рапс",
    "кукуруза": "кукуруза", "кукурудза": "кукуруза",
    "пшеница": "пшеница", "пшеницу": "пшеница", "пшениці": "пшеница",
    "ячмень": "ячмень", "ячмінь": "ячмень",
    "подсолнечник": "подсолнечник", "соняшник": "подсолнечник",
    "горох": "горох", "гороха": "горох", "гороху": "горох",
}


@dataclass
class FarmerRequest:
    crop: str
    origin: str
    volume_t: float
    quality: str = "требует уточнения"


@dataclass
class QuoteOption:
    destination: str
    distance_km: float
    distance_type: str
    market_price_uah: float
    logistics_mid: float
    margin: float
    farmer_price: float


@dataclass
class FarmerQuote:
    crop: str
    origin: str
    volume_t: float
    quality: str
    recommended_price: float
    maximum_price: float
    best_destination: str
    logistics_mid: float
    margin: float
    distance_km: float
    distance_type: str
    alternatives: List[QuoteOption]


@dataclass
class FarmerOffer:
    crop: str
    origin: str
    price: float
    volume_t: float
    quality: str = ""
    currency: str = "грн"
    seller_type: str = ""


@dataclass
class PurchaseDecision:
    decision: str
    best_destination: str
    farmer_price: float
    target_price: float
    max_price: float
    margin_per_t: float
    total_margin: float
    volume_t: float
    score: int
    reasons: List[str]


def load_prices(path: Path = DEFAULT_PRICE_FILE) -> Tuple[dict, float]:
    """Загружает актуальный прайс и средний курс USD из JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Файл прайса не найден: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    prices = data.get("prices", {})
    usd = data.get("usd", {})
    usd_rate = float(usd.get("mid", USD_RATE_FALLBACK))
    return prices, usd_rate


def price_to_uah(value: float, currency: str, usd_rate: float) -> float:
    currency = currency.strip().upper()
    if currency in ("$", "USD"):
        return value * usd_rate
    if currency in ("ГРН", "UAH"):
        return value
    raise ValueError(f"Неизвестная валюта: {currency}")


def logistics_range(distance_km: float) -> Tuple[float, float]:
    if distance_km < 10:
        return 0.0, 0.0

    for low, high, cost_low, cost_high in LOGISTICS:
        if low <= distance_km <= high:
            return float(cost_low), float(cost_high)

    raise ValueError(
        f"Расстояние {distance_km:.0f} км вне таблицы логистики 10–900 км."
    )


def margin_range(crop: str) -> Tuple[float, float]:
    key = crop.strip().lower()
    if key not in MARGINS:
        raise ValueError(f"Маржа для культуры '{crop}' пока не задана.")
    return MARGINS[key]


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(h))


def normalize_location_name(origin_text: str) -> str:
    value = re.sub(r"\s+", " ", origin_text.strip())
    value = value.replace("обл,", "обл.").replace("область,", "обл.")
    return value


def load_location_cache(path: Path = DEFAULT_LOCATION_CACHE) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_location_cache(cache: Dict[str, dict], path: Path = DEFAULT_LOCATION_CACHE) -> None:
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_cached_location(origin_text: str, path: Path = DEFAULT_LOCATION_CACHE) -> Optional[dict]:
    key = normalize_location_name(origin_text).lower()
    return load_location_cache(path).get(key)


def cache_location(
    origin_text: str,
    latitude: float,
    longitude: float,
    display_name: str = "",
    path: Path = DEFAULT_LOCATION_CACHE,
) -> dict:
    cache = load_location_cache(path)
    key = normalize_location_name(origin_text).lower()
    cache[key] = {
        "query": normalize_location_name(origin_text),
        "display_name": display_name or normalize_location_name(origin_text),
        "latitude": latitude,
        "longitude": longitude,
    }
    save_location_cache(cache, path)
    return cache[key]


def resolve_location(origin_text: str, cache_path: Path = DEFAULT_LOCATION_CACHE) -> Tuple[float, float]:
    """Сначала локальная база, затем locations_cache.json."""
    key = normalize_location_name(origin_text)

    if key in LOCATIONS:
        return LOCATIONS[key]

    low = key.lower()
    for known, coords in LOCATIONS.items():
        if known.lower() in low or low in known.lower():
            return coords

    cached = get_cached_location(key, cache_path)
    if cached:
        return float(cached["latitude"]), float(cached["longitude"])

    raise ValueError(
        f"Локация '{origin_text}' отсутствует в базе. "
        "Нужно выполнить геокодирование и сохранить координаты в locations_cache.json."
    )


def distance_to_destination(
    origin: str,
    destination: str,
    cache_path: Path = DEFAULT_LOCATION_CACHE,
) -> Tuple[float, str]:
    origin_xy = resolve_location(origin, cache_path)
    destination_xy = resolve_location(destination, cache_path)

    straight = haversine_km(origin_xy, destination_xy)
    road = straight * ROAD_FACTOR
    return round(road, 1), "оценка по координатам"


def _extract_volume(text: str) -> Optional[float]:
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*(?:т|тонн|тонны|тон|тн)\b",
        r"(\d+(?:[.,]\d+)?)\s*(?:т\.?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _extract_crop(text: str) -> Optional[str]:
    low = text.lower()
    for alias, crop in sorted(
        CROP_ALIASES.items(),
        key=lambda x: len(x[0]),
        reverse=True,
    ):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return crop
    return None


def parse_farmer_speech(text: str) -> FarmerRequest:
    """
    Пример:
    "Хмельницкая область, село Гримячка, есть 100 тонн сои, показатели в базе"
    """
    crop = _extract_crop(text)
    volume = _extract_volume(text)

    if not crop:
        raise ValueError("Не удалось определить культуру из фразы.")
    if volume is None:
        raise ValueError("Не удалось определить объём в тоннах.")

    loc_patterns = [
        r"(?:(?:в|с|из)\s+)?(?:село|с\.|смт|пгт)\s+([^,.;]+)",
        r"((?:Хмельницкая|Хмельницкая\s+обл\.?|Хмельницкая\s+область)[^,.;]*)",
        r"((?:Киевская|Винницкая|Одесская|Черкасская|Полтавская|Николаевская|Львовская|Волынская)\s+(?:обл\.?|область)[^,.;]*)",
    ]

    origin = None
    for pattern in loc_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            origin = match.group(1).strip()
            break

    if not origin:
        raise ValueError("Не удалось определить населённый пункт/локацию.")

    village = re.search(
        r"(?:село|с\.|смт|пгт)\s+([^,.;]+)",
        text,
        re.IGNORECASE,
    )
    oblast = re.search(
        r"([А-Яа-яІіЇїЄєҐґ'’-]+)\s+(?:обл\.?|область)",
        text,
        re.IGNORECASE,
    )

    if village and oblast:
        origin = f"{village.group(1).strip()}, {oblast.group(1).strip()} обл."

    quality = (
        "в базе"
        if re.search(
            r"показател\w*\s+в\s+базе|показники\s+в\s+базі",
            text,
            re.IGNORECASE,
        )
        else "требует уточнения"
    )

    return FarmerRequest(
        crop=crop,
        origin=origin,
        volume_t=volume,
        quality=quality,
    )


def calculate_quote(
    request: FarmerRequest,
    prices: dict,
    usd_rate: float,
    cache_path: Path = DEFAULT_LOCATION_CACHE,
) -> FarmerQuote:
    crop = request.crop.strip().lower()

    if request.volume_t <= 0:
        raise ValueError("Объём должен быть больше 0 т.")
    if crop not in prices:
        raise ValueError(f"Культура '{request.crop}' отсутствует в актуальном прайсе.")

    margin_low, margin_high = margin_range(crop)
    options: List[QuoteOption] = []

    for destination, data in prices[crop].items():
        try:
            raw_price = float(data["price"])
            currency = data["currency"]
            distance, distance_type = distance_to_destination(
                request.origin,
                destination,
                cache_path,
            )
            market = price_to_uah(raw_price, currency, usd_rate)
            log_low, log_high = logistics_range(distance)
            log_mid = (log_low + log_high) / 2

            farmer_price = market - log_mid - margin_high

            if farmer_price > 0:
                options.append(
                    QuoteOption(
                        destination=destination,
                        distance_km=distance,
                        distance_type=distance_type,
                        market_price_uah=market,
                        logistics_mid=log_mid,
                        margin=margin_high,
                        farmer_price=farmer_price,
                    )
                )
        except (ValueError, KeyError, TypeError):
            continue

    if not options:
        raise ValueError(
            f"Не удалось рассчитать ни одного направления для '{request.origin}'."
        )

    options.sort(key=lambda x: x.farmer_price, reverse=True)
    best = options[0]
    max_price = best.market_price_uah - best.logistics_mid - margin_low

    return FarmerQuote(
        crop=request.crop,
        origin=request.origin,
        volume_t=request.volume_t,
        quality=request.quality,
        recommended_price=round(best.farmer_price),
        maximum_price=round(max_price),
        best_destination=best.destination,
        logistics_mid=round(best.logistics_mid),
        margin=round(best.margin),
        distance_km=best.distance_km,
        distance_type=best.distance_type,
        alternatives=options,
    )


def analyze_farmer_offer(
    offer: FarmerOffer,
    prices: dict,
    usd_rate: float,
    cache_path: Path = DEFAULT_LOCATION_CACHE,
) -> PurchaseDecision:
    crop_key = offer.crop.strip().lower()

    if offer.volume_t <= 0:
        raise ValueError("Объём должен быть больше 0 т.")

    farmer_price_uah = price_to_uah(
        offer.price,
        offer.currency,
        usd_rate,
    )

    request = FarmerRequest(
        crop=crop_key,
        origin=offer.origin,
        volume_t=offer.volume_t,
        quality=offer.quality or "требует уточнения",
    )

    quote = calculate_quote(
        request,
        prices,
        usd_rate,
        cache_path,
    )

    if farmer_price_uah <= quote.recommended_price:
        decision = "БЕРЁМ"
    elif farmer_price_uah <= quote.maximum_price:
        decision = "ТОРГУЕМСЯ"
    else:
        decision = "НЕ БЕРЁМ"

    margin_per_t = (
        quote.alternatives[0].market_price_uah
        - quote.logistics_mid
        - farmer_price_uah
    )
    total_margin = margin_per_t * offer.volume_t

    reasons = []

    if decision == "БЕРЁМ":
        reasons.append("Цена фермера не выше целевой закупочной цены.")
    elif decision == "ТОРГУЕМСЯ":
        reasons.append("Цена выше целевой, но ещё находится в допустимом диапазоне.")
    else:
        reasons.append("Цена фермера выше допустимого максимума.")

    if offer.quality:
        reasons.append(f"Качество: {offer.quality}.")
    if offer.seller_type:
        reasons.append(f"Продавец: {offer.seller_type}.")

    score = 100
    if farmer_price_uah > quote.recommended_price:
        score -= 20
    if farmer_price_uah > quote.maximum_price:
        score -= 60
    if offer.volume_t < 50:
        score -= 10
    score = max(0, min(100, score))

    return PurchaseDecision(
        decision=decision,
        best_destination=quote.best_destination,
        farmer_price=farmer_price_uah,
        target_price=quote.recommended_price,
        max_price=quote.maximum_price,
        margin_per_t=margin_per_t,
        total_margin=total_margin,
        volume_t=offer.volume_t,
        score=score,
        reasons=reasons,
    )


def print_quote(quote: FarmerQuote) -> None:
    print("\n" + "=" * 64)
    print("GRAIN ENGINE V4.0 — БЫСТРАЯ ЦЕНА ФЕРМЕРУ")
    print("=" * 64)
    print(f"Культура:          {quote.crop}")
    print(f"Откуда:            {quote.origin}")
    print(f"Объём:             {quote.volume_t:.0f} т")
    print(f"Качество:          {quote.quality}")
    print("-" * 64)
    print(f"🎯 ЦЕНА ФЕРМЕРУ:   {quote.recommended_price:.0f} грн/т")
    print(f"🔴 МАКСИМУМ:       {quote.maximum_price:.0f} грн/т")
    print(f"📍 Направление:    {quote.best_destination}")
    print(f"🚛 Логистика:      ~{quote.logistics_mid:.0f} грн/т")
    print(f"💰 Маржа:          {quote.margin:.0f} грн/т")
    print(f"📏 Расстояние:     ~{quote.distance_km:.0f} км ({quote.distance_type})")
    print("-" * 64)
    print("Альтернативы:")
    for option in quote.alternatives[:5]:
        print(
            f"• {option.destination}: {option.farmer_price:.0f} грн/т "
            f"| ~{option.distance_km:.0f} км | лог. ~{option.logistics_mid:.0f}"
        )
    print("=" * 64)


def print_decision(offer: FarmerOffer, decision: PurchaseDecision) -> None:
    emoji = {
        "БЕРЁМ": "🟢",
        "ТОРГУЕМСЯ": "🟡",
        "НЕ БЕРЁМ": "🔴",
    }.get(decision.decision, "⚪")

    print("\n" + "=" * 64)
    print("GRAIN ENGINE V4.0 — РЕШЕНИЕ ПО СДЕЛКЕ")
    print("=" * 64)
    print(f"Культура:        {offer.crop}")
    print(f"Откуда:          {offer.origin}")
    print(f"Объём:           {offer.volume_t:.0f} т")
    print(f"Цена фермера:    {decision.farmer_price:.0f} грн/т")
    print("-" * 64)
    print(f"Лучшее направление: {decision.best_destination}")
    print(f"Целевая цена:        {decision.target_price:.0f} грн/т")
    print(f"Макс. цена:          {decision.max_price:.0f} грн/т")
    print(f"Маржа:               {decision.margin_per_t:.0f} грн/т")
    print(f"Потенциал сделки:    {decision.total_margin:.0f} грн")
    print(f"РЕШЕНИЕ:             {emoji} {decision.decision}")
    print(f"ОЦЕНКА:              {decision.score}/100")
    print("-" * 64)
    for reason in decision.reasons:
        print(f"• {reason}")
    print("=" * 64)


def demo() -> None:
    """Тестовый запуск на фразе фермера."""
    prices, usd_rate = load_prices()

    farmer_phrase = (
        "Хмельницкая область, село Гримячка, есть 100 тонн сои, "
        "показатели в базе"
    )

    request = parse_farmer_speech(farmer_phrase)

    # Нормализация известного написания.
    if request.origin.lower() in {
        "гримячка, хмельницкая обл.",
        "грим'ячка, хмельницкая обл.",
    }:
        request.origin = "Грим'ячка, Хмельницкая обл."

    quote = calculate_quote(
        request,
        prices,
        usd_rate,
    )
    print_quote(quote)


if __name__ == "__main__":
    demo()
