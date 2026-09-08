from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple

# ============================================================
# GRAIN ENGINE V3.1
# ЭТАП 2 — анализ предложения фермера
#
# Логика:
# 1. Получаем предложение фермера.
# 2. Считаем экономику по каждому направлению.
# 3. Находим лучшее направление.
# 4. Считаем целевую и максимальную цену фермеру.
# 5. Даём решение: БЕРЁМ / ТОРГУЕМСЯ / НЕ БЕРЁМ.
#
# V3.1 пока НЕ меняет прайс автоматически.
# Следующий этап — подключение market_parser_v01.py.
# ============================================================

DATE = "08.09.2026"

USD_BUY = 44.60
USD_SELL = 44.80
USD_RATE = (USD_BUY + USD_SELL) / 2  # 44.70 грн/$

# Маржа, грн/т: минимум / максимум.
MARGINS = {
    "кукуруза": (300, 300),
    "пшеница": (300, 300),
    "ячмень": (300, 300),
    "рапс": (400, 500),
    "подсолнечник": (400, 500),
    "семечка": (400, 500),
    "соя": (400, 500),
}

PRICES = {
    "кукуруза": {
        "Луцк": (6000, "грн"),
        "Полтава": (5000, "грн"),
        "Измаил": (6500, "грн"),
    },
    "пшеница": {
        "Львов": (5700, "грн"),
        "Киевская обл.": (5200, "грн"),
        "Рени": (5800, "грн"),
        "Измаил": (6500, "грн"),
    },
    "ячмень": {
        "Измаил": (5550, "грн"),
    },
    "подсолнечник": {
        "УЧІ": (14200, "грн"),
        "Бандурка ОЕЗ": (13700, "грн"),
        "Кропивницкий ОЕЗ": (14500, "грн"),
        "Полтава ОЕЗ": (14500, "грн"),
        "Старкон ОЕЗ": (14700, "грн"),
        "Голованевск": (14100, "грн"),
        "Измаил": (353, "$"),
        "Баштанка": (330, "$"),
        "Новый Буг": (328, "$"),
        "Софиевка (Ник. обл.)": (328, "$"),
    },
    "соя": {
        "Кропивницкий": (11200, "грн"),
        "Чорнобаи, Черкасская обл.": (10700, "грн"),
        "Киевская обл.": (300, "$"),
        "Луцк": (13000, "грн"),
    },
    "рапс": {
        "Новая Одесса": (360, "$"),
        "Новотех": (400, "$"),
        "Киевская обл.": (15800, "грн"),
        "Рени": (17700, "грн"),
        "Одесса": (360, "$"),
        "Константиновка": (365, "$"),
    },
    "горох": {
        "Одесса": (124, "$"),
    },
}

# Ориентир логистики пользователя:
# (от км, до км, минимум грн/т, максимум грн/т)
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
class DirectionCalculation:
    destination: str
    distance_km: float
    market_price_uah: float
    logistics_low: float
    logistics_mid: float
    logistics_high: float
    target_farmer_price: float
    max_farmer_price: float


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

    for low_km, high_km, low_cost, high_cost in LOGISTICS:
        if low_km <= distance_km <= high_km:
            return float(low_cost), float(high_cost)

    raise ValueError(
        f"Расстояние {distance_km} км вне текущей таблицы логистики (10–900 км)."
    )


def margin_range(crop: str) -> Tuple[float, float]:
    key = crop.strip().lower()

    if key not in MARGINS:
        raise ValueError(f"Маржа для культуры '{crop}' пока не задана.")

    return MARGINS[key]


def calculate_direction(
    crop: str,
    destination: str,
    distance_km: float,
    usd_rate: float = USD_RATE,
) -> DirectionCalculation:

    crop_key = crop.strip().lower()

    if crop_key not in PRICES:
        raise ValueError(f"Культура '{crop}' отсутствует в прайсе.")

    if destination not in PRICES[crop_key]:
        raise ValueError(f"Нет цены для '{crop}' → '{destination}'.")

    raw_price, currency = PRICES[crop_key][destination]
    market_price = price_to_uah(raw_price, currency, usd_rate)

    logistics_low, logistics_high = logistics_range(distance_km)
    logistics_mid = (logistics_low + logistics_high) / 2

    margin_low, margin_high = margin_range(crop_key)

    # Целевая цена = оставляем максимальную маржу.
    # Максимальная цена = допускаем минимальную маржу.
    target_price = market_price - logistics_mid - margin_high
    max_price = market_price - logistics_mid - margin_low

    return DirectionCalculation(
        destination=destination,
        distance_km=distance_km,
        market_price_uah=market_price,
        logistics_low=logistics_low,
        logistics_mid=logistics_mid,
        logistics_high=logistics_high,
        target_farmer_price=target_price,
        max_farmer_price=max_price,
    )


def compare_directions(
    crop: str,
    distances_km: Dict[str, float],
    usd_rate: float = USD_RATE,
) -> List[DirectionCalculation]:

    results = []

    for destination, distance in distances_km.items():
        if destination not in PRICES.get(crop.strip().lower(), {}):
            continue

        results.append(
            calculate_direction(
                crop=crop,
                destination=destination,
                distance_km=distance,
                usd_rate=usd_rate,
            )
        )

    results.sort(
        key=lambda x: x.max_farmer_price,
        reverse=True,
    )

    return results


def analyze_farmer_offer(
    offer: FarmerOffer,
    distances_km: Dict[str, float],
    usd_rate: float = USD_RATE,
) -> PurchaseDecision:

    crop_key = offer.crop.strip().lower()

    if offer.volume_t <= 0:
        raise ValueError("Объём должен быть больше 0 т.")

    farmer_price_uah = price_to_uah(
        offer.price,
        offer.currency,
        usd_rate,
    )

    directions = compare_directions(
        crop=crop_key,
        distances_km=distances_km,
        usd_rate=usd_rate,
    )

    if not directions:
        raise ValueError(
            f"Нет подходящих направлений для культуры '{offer.crop}'."
        )

    best = directions[0]

    # Решение:
    # <= target — БЕРЁМ
    # > target и <= max — ТОРГУЕМСЯ
    # > max — НЕ БЕРЁМ
    if farmer_price_uah <= best.target_farmer_price:
        decision = "БЕРЁМ"
    elif farmer_price_uah <= best.max_farmer_price:
        decision = "ТОРГУЕМСЯ"
    else:
        decision = "НЕ БЕРЁМ"

    margin_per_t = best.market_price_uah - best.logistics_mid - farmer_price_uah
    total_margin = margin_per_t * offer.volume_t

    reasons = []

    if farmer_price_uah <= best.target_farmer_price:
        reasons.append("Цена фермера ниже целевой цены.")
    elif farmer_price_uah <= best.max_farmer_price:
        reasons.append("Цена в пределах максимальной закупки, но лучше торговаться.")
    else:
        reasons.append("Цена фермера выше допустимой максимальной цены.")

    if offer.quality:
        reasons.append(f"Качество: {offer.quality}.")

    if offer.seller_type:
        reasons.append(f"Продавец: {offer.seller_type}.")

    score = 100

    if farmer_price_uah > best.target_farmer_price:
        score -= 20

    if farmer_price_uah > best.max_farmer_price:
        score -= 60

    if offer.volume_t < 50:
        score -= 10

    score = max(0, min(100, score))

    return PurchaseDecision(
        decision=decision,
        best_destination=best.destination,
        farmer_price=farmer_price_uah,
        target_price=best.target_farmer_price,
        max_price=best.max_farmer_price,
        margin_per_t=margin_per_t,
        total_margin=total_margin,
        volume_t=offer.volume_t,
        score=score,
        reasons=reasons,
    )


def print_report(
    offer: FarmerOffer,
    decision: PurchaseDecision,
) -> None:

    print("\n" + "=" * 60)
    print("GRAIN ENGINE V3.1 — АНАЛИЗ ПРЕДЛОЖЕНИЯ")
    print("=" * 60)

    print(f"Культура:        {offer.crop}")
    print(f"Откуда:          {offer.origin}")
    print(f"Объём:           {offer.volume_t:.0f} т")
    print(f"Цена фермера:    {decision.farmer_price:.0f} грн/т")

    if offer.quality:
        print(f"Качество:        {offer.quality}")

    if offer.seller_type:
        print(f"Тип продавца:    {offer.seller_type}")

    print("-" * 60)
    print(f"Лучшее направление: {decision.best_destination}")
    print(f"Целевая цена:        {decision.target_price:.0f} грн/т")
    print(f"Макс. цена:          {decision.max_price:.0f} грн/т")
    print(f"Маржа:               {decision.margin_per_t:.0f} грн/т")
    print(f"Потенциал сделки:    {decision.total_margin:.0f} грн")
    print("-" * 60)

    if decision.decision == "БЕРЁМ":
        emoji = "🟢"
    elif decision.decision == "ТОРГУЕМСЯ":
        emoji = "🟡"
    else:
        emoji = "🔴"

    print(f"РЕШЕНИЕ: {emoji} {decision.decision}")
    print(f"ОЦЕНКА:  {decision.score}/100")

    print("-" * 60)
    for reason in decision.reasons:
        print(f"• {reason}")

    print("=" * 60)


# ============================================================
# ПРИМЕР
# ============================================================

if __name__ == "__main__":

    # Расстояния пока вводим вручную.
    # Позже это также можно автоматизировать.
    distances = {
        "Новая Одесса": 40,
        "Новотех": 250,
        "Киевская обл.": 450,
        "Рени": 330,
        "Одесса": 180,
        "Константиновка": 220,
    }

    offer = FarmerOffer(
        crop="рапс",
        origin="Новая Одесса",
        price=15000,
        volume_t=100,
        quality="Ф2",
        currency="грн",
        seller_type="фермер",
    )

    result = analyze_farmer_offer(
        offer=offer,
        distances_km=distances,
        usd_rate=USD_RATE,
    )

    print_report(offer, result)
