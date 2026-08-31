"""Тверді відсіви пропозицій: вживані деталі та ціни «за запитом».

Модель добре впізнає деталь, але обмежень не має: у звіт лізли розборка,
«ціна договірна» й інший мотлох. Ці правила детерміновані й безкоштовні —
працюють навіть тоді, коли модель недоступна.

Про «ціну за запитом» чесно: більшість таких оголошень до нас і не доходить,
бо ціна не розбирається і пропозиція відпадає раніше, а нулі добиває
_drop_implausible. Правило потрібне для випадку, коли маркер стоїть поруч із
розібраним числом — сніпет Google хапає ціну доставки чи «від».

Ринок двомовний, тому маркери й українські, і російські.
"""

from __future__ import annotations

import re

# Межі слова обов'язкові: «бу» живе всередині «бампер», «буксир», «бухта»,
# а «ЕБУ двигуна» — це блок управління, а не вживана деталь.
_USED_RE = re.compile(
    r"""
    б\s*[/\\.\-]\s*[ув]            # б/у, б\у, б.у, б-у, б/в
    | \bбу\b | \bбв\b
    | вживан\w* | уживан\w* | потриман\w*
    | бывш\w* | использованн\w*
    # Саме «розборка», а не «розбортовка»: корінь без «к» ловить чуже слово.
    | авторозборк\w* | авторазборк\w* | розборк\w* | разборк\w*
    | \bрозбір\b | \bразбор\b
    | \bдонор\w*
    | під\s+відновлен\w* | под\s+восстановлен\w*
    | відновлен\w* | восстановлен\w*
    | після\s+дтп | после\s+дтп
    | контрактн\w*
    | \bsecond\s*hand\b | \bсеконд[\s-]?хенд\b | \bused\b
    """,
    re.I | re.U | re.X,
)

# Повний список — лише для назви оголошення.
_ON_REQUEST_RE = re.compile(
    r"""
    цін[аи]\s+(за|по)\s+(запитом|запиту|запросу)
    | цена\s+по\s+запросу
    | уточнюйте\s+цін\w* | уточняйте\s+цен\w* | уточнити\s+цін\w*
    | цін[аи]\s+при\s+звернен\w*
    | договірн\w* | договорн\w*
    | за\s+домовленіст\w* | по\s+договоренност\w*
    | \bдзвоніть\b | \bтелефонуйте\b | \bзвоните\b
    | price\s+on\s+request
    """,
    re.I | re.U | re.X,
)

# Наявність — окремо й вужче: тултип avto.pro «Дзвоніть, уточнюйте наявність»
# каже про склад, а не про ціну, і стоїть поруч зі справжньою ціною.
_ON_REQUEST_STOCK_RE = re.compile(
    r"""
    цін[аи]\s+(за|по)\s+(запитом|запиту|запросу)
    | цена\s+по\s+запросу
    | уточнюйте\s+цін\w* | уточняйте\s+цен\w*
    | цін[аи]\s+при\s+звернен\w*
    | договірн\w* | договорн\w*
    """,
    re.I | re.U | re.X,
)

_NEW_RE = re.compile(r"\bнов[аеийоыіїя]\w*|\bnew\b", re.I | re.U)

_OUT_OF_STOCK_RE = re.compile(
    r"""
    \bнема(?:є)?\s+в\s+наявності\b
    | \bнет\s+в\s+наличии\b
    | \bзакінчився\b
    | \bнемає\s+на\s+складі\b
    | \bвідсутній\b
    | \bзнято\s+з\s+продажу\b
    | \bпродано\b
    | \bout\s+of\s+stock\b
    | \bsold\s+out\b
    """,
    re.I | re.U | re.X,
)

_ON_ORDER_RE = re.compile(
    r"""
    \bпід\s+замовлення\b
    | \bпод\s+заказ\b
    | \bочікується\b
    | \bожидается\b
    | \bпоставка\s+від\b
    | \bдоставка\s+з-за\s+кордону\b
    """,
    re.I | re.U | re.X,
)

_IN_STOCK_RE = re.compile(
    r"""
    \b(?:є\s+)?в\s+наявності\b
    | \bв\s+наличии\b
    | \bготовий\s+до\s+відправки\b
    | \bavailable\b
    | \bin\s+stock\b
    """,
    re.I | re.U | re.X,
)


def is_used(text: str | None) -> bool:
    """Вживана, відновлена або з розборки — нам потрібні тільки нові деталі."""
    return bool(text) and _USED_RE.search(text) is not None


def is_price_on_request(title: str | None, availability: str | None = None) -> bool:
    """«Ціну скажемо, якщо напишете» — така пропозиція не є ціною."""
    if title and _ON_REQUEST_RE.search(title):
        return True
    return bool(availability) and _ON_REQUEST_STOCK_RE.search(availability) is not None


def is_junk(title: str | None, availability: str | None = None) -> bool:
    """Пропозиція, якій не місце в порівнянні цін.

    «Під замовлення» сюди НЕ входить: відсутність на складі — це все одно
    ринкова ціна, а викинувши її, ми б мовчки збіднили звіт.
    """
    if is_used(title) or is_used(availability):
        return True
    return is_price_on_request(title, availability)


def condition_of(title: str | None, availability: str | None = None) -> str | None:
    """Стан із тексту оголошення; None — коли продавець про нього мовчить.

    Раніше стан просто оголошувався новим — це було припущення, а не факт.
    """
    if is_used(title) or is_used(availability):
        return "used"
    if title and _NEW_RE.search(title):
        return "new"
    return None


def stock_of(availability: str | None) -> str | None:
    """Класифікувати текст як in_stock, on_order, out_of_stock або None."""
    if not availability:
        return None
    # «Немає в наявності» містить позитивний маркер «в наявності», тому
    # негативний клас завжди перевіряється першим.
    if _OUT_OF_STOCK_RE.search(availability):
        return "out_of_stock"
    if _ON_ORDER_RE.search(availability):
        return "on_order"
    if _IN_STOCK_RE.search(availability):
        return "in_stock"
    return None
