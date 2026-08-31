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


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        ("Немає в наявності", "out_of_stock"),
        ("Нема в наявності", "out_of_stock"),
        ("Нет в наличии", "out_of_stock"),
        ("Товар закінчився", "out_of_stock"),
        ("Немає на складі", "out_of_stock"),
        ("Відсутній", "out_of_stock"),
        ("Знято з продажу", "out_of_stock"),
        ("Продано", "out_of_stock"),
        ("Out of stock", "out_of_stock"),
        ("Sold out", "out_of_stock"),
        ("Під замовлення", "on_order"),
        ("Под заказ", "on_order"),
        ("Очікується", "on_order"),
        ("Ожидается", "on_order"),
        ("Поставка від 5 днів", "on_order"),
        ("Доставка з-за кордону", "on_order"),
        ("В наявності", "in_stock"),
        ("Є в наявності", "in_stock"),
        ("В наличии", "in_stock"),
        ("Готовий до відправки", "in_stock"),
        ("Available", "in_stock"),
        ("In stock", "in_stock"),
    ],
)
def test_stock_markers(availability, expected):
    assert offer_gates.stock_of(availability) == expected


# Рядки нижче — НЕ вигадані: кожен знайдено в живому кеші звітів
# (backend/tests/fixtures/audit/redis/) або зафіксовано ревізією пісочниці.
# Словник, перевірений лише синтетичними фразами, на цих рядках мовчав.
@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        # Машинні коди Prom: 57×avail і 5×not_avail у кеші звітів.
        ("avail", "in_stock"),
        ("not_avail", "out_of_stock"),
        ("available", "in_stock"),
        ("not_available", "out_of_stock"),
        ("waiting_for_supply", "on_order"),
        # Тултипи avto.pro з кешу звітів: відправка сьогодні/завтра = на складі.
        ("Отправка товара завтра из г. Киев", "in_stock"),
        ("Отправка товара сегодня из г. Винница", "in_stock"),
        ("Товар в наличии и готов к отправке из г. Киев", "in_stock"),
        # Інверсія з ревізії пісочниці: коротке «не в наявності» падало
        # в позитивний клас через хвіст «в наявності».
        ("Не в наявності", "out_of_stock"),
        ("Не в наличии", "out_of_stock"),
        # Дірки словника з ревізії пісочниці.
        ("Недоступний", "out_of_stock"),
        ("Недоступно", "out_of_stock"),
        ("Деталь відсутня", "out_of_stock"),
        ("Отсутствует", "out_of_stock"),
        ("Розпродано", "out_of_stock"),
        ("Распродано", "out_of_stock"),
        ("Нет на складе", "out_of_stock"),
        ("Товара нет", "out_of_stock"),
    ],
)
def test_live_stock_strings_are_classified(availability, expected):
    """Словник має впізнавати те, що реально приходить із джерел."""
    assert offer_gates.stock_of(availability) == expected


@pytest.mark.parametrize(
    "availability",
    [
        "Дзвоніть, уточнюйте наявність",
        "Уточнюйте у менеджера",
        # Живий рядок avto.pro: «через 5 дней» може бути і постачанням
        # під замовлення — класифікувати нечесно.
        "Отправка товара через 5 дней из г. Киев",
        "",
        None,
    ],
)
def test_unknown_stock_markers_stay_unknown(availability):
    assert offer_gates.stock_of(availability) is None
