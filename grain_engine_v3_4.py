from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional
from math import radians, sin, cos, asin, sqrt
import json
from pathlib import Path

# ============================================================
# GRAIN ENGINE V3.4
# ЭТАП 3 — быстрый расчёт цены фермеру БЕЗ цены фермера
#
# Сценарий:
# Фермер: "Хмельницкая обл., Грим'ячка, 100 т сои, показатели в базе"
# -> движок определяет направления -> считает логистику ->
# -> вычитает нашу маржу -> выдаёт цену НА МЕСТЕ у фермера.
#
# ВАЖНО:
# - текущие цены рынка живут отдельно от логики движка;
# - расстояния пока считаются через координаты + коэффициент дороги;
# - следующим этапом подключим точный дорожный маршрут/геокодер.
# ============================================================

DATE = "08.09.2026"
USD_BUY = 44.60
USD_SELL = 44.80
USD_RATE = (USD_BUY + USD_SELL) / 2

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

# Актуальный прайс на 08.09.2026.
PRICES = {
    "кукуруза": {
        "Луцк": (6000, "грн"), "Полтава": (5000, "грн"), "Измаил": (6500, "грн")},
    "пшеница": {
        "Львов": (5700, "грн"), "Киевская обл.": (5200, "грн"),
        "Рени": (6500, "грн"), "Измаил": (6500, "грн")},
    "ячмень": {"Измаил": (5550, "грн")},
    "подсолнечник": {
        "УЧІ": (14200, "грн"), "Бандурка ОЕЗ": (13700, "грн"),
        "Кропивницкий ОЕЗ": (14500, "грн"), "Полтава ОЕЗ": (14500, "грн"),
        "Старкон ОЕЗ": (14700, "грн"), "Голованевск": (14100, "грн"),
        "Измаил": (353, "$"), "Баштанка": (330, "$"),
        "Новый Буг": (328, "$"), "Софиевка (Ник. обл.)": (328, "$")},
    "соя": {
        "Кропивницкий": (11200, "грн"), "Чорнобаи, Черкасская обл.": (10700, "грн"),
        "Киевская обл.": (300, "$"), "Луцк": (13000, "грн")},
    "рапс": {
        "Новая Одесса": (360, "$"), "Новотех": (400, "$"),
        "Киевская обл.": (15800, "грн"), "Рени": (17700, "грн"),
        "Одесса": (360, "$"), "Константиновка": (365, "$")},
    "горох": {"Одесса": (124, "$")},
}

LOGISTICS = [
    (10, 50, 200, 300), (50, 100, 300, 550), (100, 150, 500, 700),
    (150, 200, 700, 850), (200, 250, 850, 1050), (250, 300, 1050, 1200),
    (300, 350, 1200, 1350), (350, 400, 1350, 1500), (400, 450, 1500, 1500),
    (450, 500, 1500, 1600), (500, 550, 1600, 1650), (550, 600, 1600, 1750),
    (600, 650, 1750, 1800), (650, 700, 1750, 1850), (700, 750, 1850, 1875),
    (750, 800, 1850, 1900), (800, 900, 2000, 2100),
]

# Координаты населённых пунктов/направлений.
# Пока используем центр населённого пункта. Для заводов позже внесём
# координаты конкретной точки приёмки.
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

# До появления точного дорожного API используем поправку от прямого
# расстояния к ориентировочному дорожному расстоянию.
ROAD_FACTOR = 1.20

@dataclass
class FarmerRequest:
    crop: str
    origin: str
    volume_t: float
    quality: str = "в базе"

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


def price_to_uah(value: float, currency: str, usd_rate: float = USD_RATE) -> float:
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
    raise ValueError(f"Расстояние {distance_km:.0f} км вне таблицы логистики 10–900 км.")


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(h))


def resolve_location(name: str) -> Tuple[float, float]:
    key = name.strip()
    if key in LOCATIONS:
        return LOCATIONS[key]
    # Простое сопоставление по нижнему регистру для будущих вариантов написания.
    low = key.lower()
    for known, coords in LOCATIONS.items():
        if known.lower() in low or low in known.lower():
            return coords
    raise ValueError(f"Населённый пункт '{name}' пока отсутствует в базе координат.")


def distance_to_destination(origin: str, destination: str) -> Tuple[float, str]:
    origin_xy = resolve_location(origin)
    destination_xy = resolve_location(destination)
    straight = haversine_km(origin_xy, destination_xy)
    road = straight * ROAD_FACTOR
    return round(road, 1), "оценка по координатам"


def margin_range(crop: str) -> Tuple[float, float]:
    key = crop.strip().lower()
    if key not in MARGINS:
        raise ValueError(f"Маржа для культуры '{crop}' пока не задана.")
    return MARGINS[key]


def calculate_quote(request: FarmerRequest, usd_rate: float = USD_RATE) -> FarmerQuote:
    crop = request.crop.strip().lower()
    if request.volume_t <= 0:
        raise ValueError("Объём должен быть больше 0 т.")
    if crop not in PRICES:
        raise ValueError(f"Культура '{request.crop}' отсутствует в актуальном прайсе.")

    margin_low, margin_high = margin_range(crop)
    options: List[QuoteOption] = []

    for destination, (raw_price, currency) in PRICES[crop].items():
        try:
            distance, distance_type = distance_to_destination(request.origin, destination)
            market = price_to_uah(raw_price, currency, usd_rate)
            log_low, log_high = logistics_range(distance)
            log_mid = (log_low + log_high) / 2

            # Рекомендуемая цена: оставляем верхнюю границу нашей маржи.
            farmer_price = market - log_mid - margin_high
            # Максимум: минимальная допустимая маржа.
            maximum_price = market - log_mid - margin_low

            if farmer_price > 0:
                options.append(QuoteOption(
                    destination=destination,
                    distance_km=distance,
                    distance_type=distance_type,
                    market_price_uah=market,
                    logistics_mid=log_mid,
                    margin=margin_high,
                    farmer_price=farmer_price,
                ))
        except (ValueError, KeyError):
            # Направления без координат пока пропускаем, не ломая весь расчёт.
            continue

    if not options:
        raise ValueError(
            f"Не удалось рассчитать ни одного направления для '{request.origin}'. "
            "Добавьте населённый пункт/координаты направления."
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


def print_quote(quote: FarmerQuote) -> None:
    print("\n" + "=" * 64)
    print("GRAIN ENGINE V3.4 — БЫСТРАЯ ЦЕНА ФЕРМЕРУ")
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


if __name__ == "__main__":
    # Реальный тестовый сценарий пользователя:
    request = FarmerRequest(
        crop="соя",
        origin="Грим'ячка, Хмельницкая обл.",
        volume_t=100,
        quality="показатели в базе",
    )
    quote = calculate_quote(request)
    print_quote(quote)
