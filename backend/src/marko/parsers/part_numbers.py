"""Каталожні номери деталі: звідки б вони не прийшли, розбір один.

Номери лежать у двох різних місцях і в різному вигляді: у XLSX-експорті —
колонками та характеристиками, на сторінці товару — атрибутами Apollo. Спільне
в них те, що поруч із номерами живе вільний текст, і саме він раніше йшов у
пошук замість номера.
"""
from __future__ import annotations

import re

_MIN_OEM_LENGTH = 4  # shorter tokens are truncation noise, not part numbers
_MIN_SEARCH_OEM_LENGTH = 6  # «94-06» та «6 pin» — не номери
# Лише латиниця й цифри, щонайменше дві цифри: кирилиця відсіює слова, а
# вимога цифр — марки та моделі («Ford», «Sierra»).
_SEARCH_OEM_RE = re.compile(r"(?=(?:\D*\d){2})[A-Z0-9]+")

# Марки й моделі авто, склеєні з цифрами: «AUDI100», «PEUGEOT206»,
# «MERCEDESBENZW210». У «Пошукові запити» вони лежать упереміш зі справжніми
# номерами, а сортування ставить літерні токени першими — тож модель авто
# з'їдала пошуковий слот справжнього OEM і приводила сторінки цілих машин.
# Список явний, бо за формою їх не відрізнити від справжніх номерів
# (VKBA6522 — підшипник SKF, JHQ047 — теж каталожний номер).
_CAR_MODEL_RE = re.compile(
    r"""^(?:
        AUDI|BMW|MERCEDES(?:BENZ)?|BAUREIHE|VOLKSWAGEN|VW|OPEL|FORD|FIAT
        |PEUGEOT|CITROEN|RENAULT|CHEVROLET|DAEWOO|SKODA|SEAT|NISSAN|TOYOTA
        |HYUNDAI|KIA|MAZDA|HONDA|MITSUBISHI|SUZUKI|VOLVO|IVECO
        |SPRINTER|VITO|VIANO|GOLF|PASSAT|TRANSIT|ESCORT|SIERRA|MONDEO|FOCUS
        |KANGOO|BERLINGO|DUCATO|DOBLO|COMBO|CADDY|TRAFIC|MASTER|LANOS|AVEO
        |LACETTI|NUBIRA|LEGANZA|MATIZ|LOGAN|MEGANE|CLIO|SCENIC|LAGUNA
    )[A-Z]{0,2}\d{1,4}$""",
    re.X,
)


def is_car_model(token: str) -> bool:
    """«AUDI100» — модель авто з пошукової фрази, а не каталожний номер."""
    return _CAR_MODEL_RE.fullmatch(token) is not None


def normalize_oem(value: object) -> str | None:
    """Uppercase part number without separators, or None when unusable."""
    token = re.sub(r"[\s ]+", "", str(value or "")).upper()
    if len(token) < _MIN_OEM_LENGTH or not any(char.isalnum() for char in token):
        return None
    if is_car_model(token):
        return None
    return token


def split_number_list(value: object) -> list[str]:
    """«312783, 77648805» — так номери перелічені і в експорті, і на сторінці."""
    return [str(part) for part in str(value or "").split(",")]


def part_number(value: object) -> str | None:
    """Схоже на каталожний номер, а не на слово чи об'єм двигуна.

    «1.6-1.8-2.0» після склеювання дало б «161820» — саме тому крапка одразу
    відхиляє токен: у номерах Prom її не буває, а в об'ємах є завжди.
    """
    raw = str(value or "").strip()
    if "." in raw:
        return None
    token = re.sub(r"[\s \-]+", "", raw).upper()
    if len(token) < _MIN_SEARCH_OEM_LENGTH or is_car_model(token):
        return None
    return token if _SEARCH_OEM_RE.fullmatch(token) else None


def numbers_from_list(value: object) -> list[str]:
    """Номери з перелічення через кому; фрази поруч із ними відкидає."""
    return [
        number
        for number in map(part_number, split_number_list(value))
        if number is not None
    ]


def order_numbers(numbers: list[str]) -> tuple[str, ...]:
    """Номер виробника першим: за внутрішнім артикулом конкурентів не знайти.

    Номер виробника майже завжди має літеру (8E0513033, 056121113D), а
    внутрішній артикул магазину — самі цифри. Пошукових термінів беруть лише
    перші два, тож без цього сортування справжній номер туди не потрапляв.
    """
    return tuple(
        sorted(
            dict.fromkeys(numbers),
            key=lambda code: not any(char.isalpha() for char in code),
        )
    )
