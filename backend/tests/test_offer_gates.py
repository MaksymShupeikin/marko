"""Тверді відсіви: вживані деталі, «ціна за запитом», стан із тексту."""

import pytest

from marko.services import offer_gates


@pytest.mark.parametrize(
    "title",
    [
        "Фара права б/у Renault Kangoo",
        "Фара б\\у",
        "Фара б.у.",
        "Двигун з розборки Renault",
        "Бампер вживаний",
        "Крыло бывшее в употреблении",
        "Двигун донор",
        "Капот після ДТП",
        "Радіатор під відновлення",
        "Контрактний двигун Iveco",
        "Turbo used original",
        "Секонд-хенд запчастини",
    ],
)
def test_used_markers_drop_the_offer(title):
    assert offer_gates.is_used(title)
    assert offer_gates.is_junk(title)
    assert offer_gates.condition_of(title) == "used"


@pytest.mark.parametrize(
    "title",
    [
        "Бампер передній Renault Kangoo",
        "Буксирний гак",
        "Бухта дроту 10 м",
        "ЕБУ двигуна Bosch",
        "Бушинг стабілізатора",
        "Разбортовка не потрібна",
    ],
)
def test_bu_inside_a_word_is_not_a_used_marker(title):
    """«бу» живе всередині звичайних слів — межі слова тримають це осторонь."""
    assert not offer_gates.is_used(title)
    assert not offer_gates.is_junk(title)


@pytest.mark.parametrize(
    "title",
    [
        "Фільтр масляний — ціна за запитом",
        "Радіатор, цена по запросу",
        "Помпа, уточнюйте ціну",
        "Стартер договірна",
        "Генератор — ціна при зверненні",
        "Насос, дзвоніть",
        "Water pump, price on request",
    ],
)
def test_price_on_request_markers(title):
    assert offer_gates.is_price_on_request(title)
    assert offer_gates.is_junk(title)


def test_stock_tooltips_are_not_price_on_request():
    """Тултип avto.pro каже про склад, а ціна поруч — справжня."""
    assert not offer_gates.is_junk(
        "Фільтр масляний Bosch", "Дзвоніть, уточнюйте наявність"
    )
    assert not offer_gates.is_junk("Фільтр масляний Bosch", "Під замовлення")
    # А от ціна за запитом у наявності — це вже не ціна.
    assert offer_gates.is_junk("Фільтр масляний Bosch", "Ціна за запитом")


def test_condition_is_derived_from_text():
    assert offer_gates.condition_of("Фільтр масляний новий Bosch") == "new"
    assert offer_gates.condition_of("Фільтр масляний Bosch 0451103316") is None
    assert offer_gates.condition_of("Фара б/у") == "used"
    # Стан із наявності теж рахується.
    assert offer_gates.condition_of("Фара Renault", "з розборки") == "used"


def test_empty_text_is_not_junk():
    assert not offer_gates.is_junk(None)
    assert not offer_gates.is_used("")
    assert offer_gates.condition_of(None) is None
