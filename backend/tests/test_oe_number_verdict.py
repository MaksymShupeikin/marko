"""Вердикт по номеру считается у нас, а не тем, кто скачивал страницы.

Прошлый прогон отдал решение таблице из 22 слов внутри чужого скрипта: она
опровергла `1H0698151A` рядом с надписью «Brake pad set», потому что искала
`brake pads`. Здесь то же решение принимается по заголовку страницы и
проверяется на 50 строках с известным ответом — 25 верных номеров и 25
подставных, взятых у детали другого типа.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from marko.services.oe_number_verdict import our_makes, verdict

CANARIES = Path(__file__).parent / "fixtures" / "oe_number_verdict_canaries.csv"

_BLOCK = (
    "1603164 - Ball joint OE number by "
    "ASÜNA, BEDFORD, CHEVROLET, DAEWOO, OPEL, PONTIAC, SEAT, VAUXHALL"
)


def test_part_type_from_the_page_confirms_our_row() -> None:
    assert verdict("Шаровая опора Opel Kadet", "1603164", _BLOCK)[0] == "ПОДТВЕРЖДЁН"


def test_a_different_part_type_refutes_it() -> None:
    verd, why = verdict("Мотор радиатора Audi A4", "1603164", _BLOCK)
    assert verd == "ОПРОВЕРГНУТ"
    assert "деталь другая" in why


def test_brake_pad_set_is_not_a_different_part_from_колодки() -> None:
    """Именно эта строка была опровергнута зря: искали `brake pads`."""

    head = "1H0698151A - Brake pad set OE number by AUDI, SEAT, SKODA, VW"
    assert verdict("Колодки торм передние VW Golf 3", "1H0698151A", head)[0] == "ПОДТВЕРЖДЁН"


def test_the_maker_list_objects_even_when_the_part_type_agrees() -> None:
    head = "1603164 - Ball joint OE number by TOYOTA, LEXUS"
    verd, why = verdict("Шаровая опора Opel Kadet", "1603164", head)
    assert verd == "ОПРОВЕРГНУТ"
    assert "машина другая" in why


def test_one_concern_writes_several_brands_and_that_is_not_an_objection() -> None:
    head = "035103383J - Gasket OE number by AUDI, CUPRA, SEAT, SKODA, VW"
    assert verdict("Прокладки гол. блока Audi-100", "035103383J", head)[0] == "ПОДТВЕРЖДЁН"


def test_a_match_deep_in_the_tail_of_the_type_list_does_not_count() -> None:
    """`link set` девятым в списке подойдёт почти к чему угодно."""

    head = (
        "9064600055 - Rod assembly, tie rod axle joint, mounting kit, repair kit, "
        "link set, inner tie rod OE number by AUDI, MERCEDES-BENZ, VW"
    )
    assert verdict("Стойка стабилизатора переднего VW Passat", "9064600055", head)[0] == "ОПРОВЕРГНУТ"


def test_an_empty_catalogue_page_gets_no_verdict_at_all() -> None:
    for head in ("Nothing Matches your Search for: l45449", "Search results for vkba3624", ""):
        assert verdict("Ступица задняя Opel Vectra", "VKBA3624", head)[0] == "НЕ НАЙДЕНО"


def test_a_page_about_another_number_gets_no_verdict() -> None:
    assert verdict("Шаровая опора Opel Kadet", "1603999", _BLOCK)[0] == "НЕ НАЙДЕНО"


def test_a_name_we_cannot_read_gets_no_verdict_rather_than_a_guess() -> None:
    verd, why = verdict("Хреновина какая-то", "1603164", _BLOCK)
    assert verd == "НЕ НАЙДЕНО"
    assert "не разобран" in why


def test_the_make_is_read_from_the_model_when_the_name_omits_it() -> None:
    assert "OPEL" in our_makes("Шаровая опора Kadet Ascona")
    assert "DAEWOO" in our_makes("Корзина сцепления Lanos Nexia")
    assert "FORD" in our_makes("Амортизатор задний Scorpio 85- газ")


def test_the_name_may_be_written_in_ukrainian() -> None:
    """Каталог заказчика двуязычный, и «група» — не опечатка.

    Без украинского ключа строка 77645785 не разбиралась вообще и уходила в
    «НЕ НАЙДЕНО» при совершенно однозначной странице.
    """

    head = "6R0905865 - Ignition-/starter switch, ignition switch OE number by AUDI, SEAT, SKODA, VW"
    assert verdict("Контактная група замка зажигания Audi", "6R0905865", head)[0] == "ПОДТВЕРЖДЁН"
    assert verdict("Підшипник передньої маточини Renault", "7701205779",
                   "7701205779 - Wheel bearing kit OE number by RENAULT")[0] == "ПОДТВЕРЖДЁН"


def test_the_catalogue_may_write_the_type_only_as_a_starter_switch() -> None:
    head = "4A0905849 - Ignition-/starter switch OE number by AUDI, VW"
    assert verdict("Контакт группа замка заж. Audi-100", "4A0905849", head)[0] == "ПОДТВЕРЖДЁН"


def _canary_rows() -> list[dict[str, str]]:
    with CANARIES.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("row", _canary_rows(), ids=lambda r: f"{r['number']}-{r['expected'][:4]}")
def test_every_canary_is_either_answered_correctly_or_not_answered(row: dict[str, str]) -> None:
    verd, why = verdict(row["name"], row["number"], row["headline"])
    assert verd in {row["expected"], "НЕ НАЙДЕНО"}, why


def test_the_canary_set_is_mostly_answered_not_mostly_dodged() -> None:
    """Воздержание безопасно, поэтому оно должно быть ограничено сверху."""

    rows = _canary_rows()
    answered = [r for r in rows if verdict(r["name"], r["number"], r["headline"])[0] != "НЕ НАЙДЕНО"]
    assert len(answered) >= 40, f"ответов только {len(answered)} из {len(rows)}"


# Дырки словаря, найденные на этапе 7. Каждая — языковой факт: как деталь
# называется у нас и как её называет каталог. Это не подгонка под ответ:
# «радиатор печки» — это heat exchanger независимо от того, что показала
# страница.


def test_the_heater_core_is_a_heat_exchanger() -> None:
    assert verdict(
        "Радиатор печки  Daewoo (Део) Lanos (плоские соты)",
        "96231949",
        "96231949 - Heat exchanger OE number by CHEVROLET, DAEWOO, GENERAL MOTORS",
    )[0] == "ПОДТВЕРЖДЁН"


def test_the_air_conditioning_radiator_is_a_condenser() -> None:
    assert verdict(
        "Радиатор кондиционера Renault Kangoo Nissan Kubistar",
        "8200221131",
        "8200221131 - Condenser OE number by NISSAN, RENAULT",
    )[0] == "ПОДТВЕРЖДЁН"


def test_the_caliper_may_be_spelled_the_ukrainian_way() -> None:
    assert verdict(
        "Супорт задний  Renault Trafic 2.Opel Vivaro",
        "7701056166",
        "7701056166 - Repair kit, brake caliper, piston OE number by DACIA, RENAULT",
    )[0] == "ПОДТВЕРЖДЁН"


def test_piston_rings_are_a_piston_ring_kit() -> None:
    assert verdict(
        "Кольца поршней VW (Фольксваген) Golf 81,0",
        "037198151",
        "037198151 - Piston ring kit OE number by AUDI, CUPRA, VW",
    )[0] == "ПОДТВЕРЖДЁН"


def test_the_starter_drive_is_a_pinion() -> None:
    assert verdict(
        "Бендикс VW Golf 2/VW Passat В3 1,9D/1,9TD",
        "02A911335B",
        "02A911335B - Pinion OE number by AUDI, SEAT, SKODA, VAG, VW",
    )[0] == "ПОДТВЕРЖДЁН"


def test_the_expansion_tank_and_its_cap_are_known_words() -> None:
    assert verdict(
        "Бачок розширювальний Audi A6 2.0-3.2 04->",
        "025121321B",
        "025121321B - Sealing cap, expansion tank, cap OE number by AUDI, VW",
    )[0] == "ПОДТВЕРЖДЁН"


def test_a_latin_letter_inside_a_russian_word_does_not_hide_the_part() -> None:
    """«Крышкa» — последняя буква латинская. В данных заказчика это бывает."""

    assert verdict(
        "Крышкa расширительного бачка VW (Фольксваген) Golf",
        "171121321D",
        "171121321D - Sealing cap, expansion tank, closure OE number by AUDI, VW",
    )[0] == "ПОДТВЕРЖДЁН"


def test_a_brake_disc_against_an_intercooler_is_a_refusal() -> None:
    """Номер из справочника оказался чужим: диск против интеркулера Honda."""

    assert verdict(
        "Диск тормозной задний MB Vito",
        "197106A0A01",
        "197106A0A01 - Intercooler OE number by HONDA",
    )[0] == "ОПРОВЕРГНУТ"


def test_a_parts_brand_in_the_maker_block_is_not_an_objection() -> None:
    """SACHS не выпускает автомобили: сказать по нему, чья это машина, нечем."""

    assert verdict(
        "Амортизатор задний MB Sprinter (906) 46-",
        "314608",
        "314 608 - Shock absorber OE number by SACHS",
    )[0] == "ПОДТВЕРЖДЁН"


def test_a_real_car_maker_beside_a_parts_brand_still_objects() -> None:
    assert verdict(
        "Амортизатор задний Renault Kangoo 08->",
        "344709",
        "344709 - Shock absorber OE number by CHEVROLET, OPEL, SACHS",
    )[0] == "ОПРОВЕРГНУТ"
