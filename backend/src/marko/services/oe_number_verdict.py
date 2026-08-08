"""Вердикт считается локально по тексту страницы /oem/<номер>.

Страница отвечает на вопрос «какая деталь носит этот номер». Заголовок её —
`<номер> - <тип детали, ...> OE number by<ПРОИЗВОДИТЕЛИ>`. Тип детали с этой
страницы сравнивается с типом детали из нашего названия. Номер в блоке
производителей — эхо запроса и доказательством не является.
"""

from __future__ import annotations

import re

#: Тип детали в наших названиях -> как он называется в каталоге.
#: Ключ ищется в нашем названии, значения — в заголовке страницы.
PART_TYPES: dict[str, tuple[str, ...]] = {
    "молдинг": ("moulding", "molding", "trim", "cover strip"),
    "шаровая опора": ("ball joint",),
    "кульова опора": ("ball joint",),
    "датчик": ("sensor", "transmitter", "sender"),
    "фонар": ("light", "lamp", "rearlight"),
    "мотор радиатора": ("fan", "blower", "electric motor"),
    "вентилятор": ("fan", "blower"),
    "кронштейн": ("bracket", "support", "guide", "roller", "holder"),
    "выключатель": ("switch",),
    "втулка": ("bush", "bushing", "mounting", "sleeve"),
    "сайлентблок": ("bush", "bushing", "mounting"),
    "ремень": ("belt",),
    "вилка выжима": ("release fork", "fork"),
    "стойка стабилизатора": ("link", "coupling rod", "rod/strut", "strut"),
    "рычаг": ("control arm", "trailing arm", "wishbone", "link set", "suspension arm"),
    "суппорт": ("caliper",),
    "корзина сцепления": ("pressure plate", "clutch"),
    "диск сцепления": ("clutch disc", "clutch plate", "clutch"),
    "колодки": ("brake pad", "brake lining"),
    "прокладк": ("gasket", "seal"),
    "радиатор": ("radiator", "cooler"),
    "наконечник": ("tie rod end", "track rod end"),
    "замок": ("lock", "latch"),
    "контакт группа": ("ignition switch", "ignition lock", "lock cylinder", "starter switch"),
    "контактная группа": ("ignition switch", "ignition lock", "lock cylinder", "starter switch"),
    "контактная група": ("ignition switch", "ignition lock", "lock cylinder", "starter switch"),
    "контакт група": ("ignition switch", "ignition lock", "lock cylinder", "starter switch"),
    "провода высоковольтные": ("ignition cable", "ignition lead"),
    "подшипник": ("bearing", "wheel bearing"),
    "підшипник": ("bearing", "wheel bearing"),
    "пружина": ("spring",),
    "амортизатор": ("shock absorber", "damper"),
    "бендикс": ("freewheel gear", "starter"),
    "вкладыш": ("bearing shell", "big end bearing", "crankshaft bearing"),
    "помпа": ("water pump",),
    "термостат": ("thermostat",),
    "трос": ("cable",),
    "стекло": ("glass", "window"),
    "бампер": ("bumper",),
    "крыло": ("wing", "fender"),
    "решетка": ("grille",),
    "зеркало": ("mirror",),
    "гранат": ("joint kit", "cv joint", "drive shaft"),
    "шрус": ("joint kit", "cv joint", "drive shaft"),
    "опора двигателя": ("engine mount", "mounting"),
    "подушка двигателя": ("engine mount", "mounting"),
    "цилиндр": ("cylinder",),
    "фильтр": ("filter",),
    "шланг": ("brake hose", "hose", "pipe", "line"),
    "ролик": ("tensioner", "idler", "deflection", "pulley", "guide pulley"),
    "ступица": ("wheel hub", "wheel bearing", "hub bearing", "hub"),
    "маточин": ("wheel hub", "wheel bearing", "hub"),
    "тяга рулевая": ("tie rod", "track rod", "steering rod"),
    "рулевая тяга": ("tie rod", "track rod", "steering rod"),
    "сальник": ("shaft seal", "seal", "gasket"),
    "шкив": ("pulley", "belt pulley"),
    "рейка рулевая": ("steering gear", "steering rack"),
    "расходомер": ("air mass sensor", "mass air flow", "air flow meter"),
    "піввісь": ("drive shaft", "half shaft", "axle"),
    "полуось": ("drive shaft", "half shaft", "axle"),
    "личинк": ("lock cylinder", "lock barrel"),
    "крышка": ("cap", "cover", "lid"),
    "кришка": ("cap", "cover", "lid"),
    "насос": ("pump",),
    "шайба": ("washer", "thrust washer"),
    "ручка двер": ("door handle", "handle"),
    "стартер": ("starter",),
    "бензонасос": ("fuel pump",),
    "реле": ("relay",),
    "пыльник": ("bellow", "boot", "dust cover", "protective cap"),
    "пильник": ("bellow", "boot", "dust cover", "protective cap"),
    "ремкомплект": ("repair kit", "repair set"),
    "крестовина": ("joint", "universal joint", "propshaft"),
    "форсунка": ("injector", "nozzle"),
    "перемикач": ("switch",),
    "отбойник": ("bump stop", "rubber buffer", "buffer"),
    "генератор": ("alternator",),
    "поршень": ("piston",),
    "клапан": ("valve",),
    "патрубок": ("hose", "pipe", "radiator hose"),
    "плата": ("bulb holder", "lamp base", "socket"),
    "вкладыш": ("bearing shell", "big end bearing", "crankshaft bearing", "bearing"),
    "трос": ("cable",),
    "тросик": ("cable",),
    "успокоитель": ("guide", "rail", "tensioner"),
    "натяжитель": ("tensioner",),
    "распредвал": ("camshaft",),
    "коленвал": ("crankshaft",),
}


#: Марка в нашем названии -> как она пишется в каталоге. Модель без марки
#: («Кадет», «Ланос») тоже считается: в наших названиях марку часто опускают.
CAR_MAKES: dict[str, str] = {
    "audi": "AUDI", "ауди": "AUDI",
    "vw": "VW", "фольксваген": "VW", "golf": "VW", "passat": "VW", "пассат": "VW",
    "caddy": "VW", "кадди": "VW", "transporter": "VW", "транспортер": "VW",
    "t4": "VW", "t5": "VW", "bora": "VW", "jetta": "VW", "sharan": "VW",
    "polo": "VW", "поло": "VW", "lt": "VW", "vento": "VW",
    "skoda": "SKODA", "шкода": "SKODA", "octavia": "SKODA", "октавия": "SKODA",
    "octavi": "SKODA", "fabia": "SKODA",
    "seat": "SEAT",
    "opel": "OPEL", "опель": "OPEL", "kadet": "OPEL", "кадет": "OPEL",
    "astra": "OPEL", "астра": "OPEL", "vectra": "OPEL", "вектра": "OPEL",
    "vektra": "OPEL", "corsa": "OPEL", "omega": "OPEL", "zafira": "OPEL",
    "signum": "OPEL", "combo": "OPEL", "ascona": "OPEL", "vivaro": "OPEL",
    "movano": "OPEL", "frontera": "OPEL",
    "ford": "FORD", "форд": "FORD", "escort": "FORD", "mondeo": "FORD",
    "focus": "FORD", "фокус": "FORD", "transit": "FORD", "транзит": "FORD",
    "fiesta": "FORD", "scorpio": "FORD", "sierra": "FORD", "connect": "FORD",
    "c-max": "FORD", "cmax": "FORD", "galaxy": "FORD", "fusion": "FORD",
    "mb": "MERCEDES-BENZ", "mercedes": "MERCEDES-BENZ", "мерседес": "MERCEDES-BENZ",
    "vito": "MERCEDES-BENZ", "вито": "MERCEDES-BENZ", "sprinter": "MERCEDES-BENZ",
    "спринтер": "MERCEDES-BENZ", "w203": "MERCEDES-BENZ", "w204": "MERCEDES-BENZ",
    "w210": "MERCEDES-BENZ", "w124": "MERCEDES-BENZ",
    "renault": "RENAULT", "рено": "RENAULT", "master": "RENAULT", "trafic": "RENAULT",
    "kangoo": "RENAULT", "kango": "RENAULT", "megane": "RENAULT", "laguna": "RENAULT",
    "scenic": "RENAULT", "logan": "RENAULT",
    "daewoo": "DAEWOO", "дэу": "DAEWOO", "lanos": "DAEWOO", "ланос": "DAEWOO",
    "nexia": "DAEWOO", "нексия": "DAEWOO", "espero": "DAEWOO", "sens": "DAEWOO",
    "chevrolet": "CHEVROLET", "шевроле": "CHEVROLET", "lachetti": "CHEVROLET",
    "lacetti": "CHEVROLET", "aveo": "CHEVROLET",
    "fiat": "FIAT", "фиат": "FIAT", "ducato": "FIAT", "doblo": "FIAT",
    "scudo": "FIAT", "punto": "FIAT",
    "peugeot": "PEUGEOT", "пежо": "PEUGEOT", "partner": "PEUGEOT", "boxer": "PEUGEOT",
    "expert": "PEUGEOT", "exspert": "PEUGEOT",
    "citroen": "CITROEN", "ситроен": "CITROEN", "berlingo": "CITROEN",
    "jumper": "CITROEN", "jumpy": "CITROEN",
    "bmw": "BMW", "бмв": "BMW",
    "nissan": "NISSAN", "ниссан": "NISSAN", "primera": "NISSAN", "almera": "NISSAN",
    "toyota": "TOYOTA", "тойота": "TOYOTA", "corolla": "TOYOTA", "auris": "TOYOTA",
    "hyundai": "HYUNDAI", "хундай": "HYUNDAI", "accent": "HYUNDAI",
    "kia": "KIA", "киа": "KIA", "sorento": "KIA",
    "iveco": "IVECO", "ивеко": "IVECO", "daily": "IVECO",
    "volvo": "VOLVO", "вольво": "VOLVO",
    "mazda": "MAZDA", "мазда": "MAZDA",
    "honda": "HONDA", "хонда": "HONDA",
    "mitsubishi": "MITSUBISHI", "митсубиси": "MITSUBISHI",
    "porsche": "PORSCHE",
    "lada": "LADA", "ваз": "LADA",
}

#: Одна марка нескольких имён: концерн пишет один и тот же номер под разными
#: брендами, и в блоке каталога они стоят рядом. Несовпадение внутри группы —
#: не возражение.
MAKE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"VW", "AUDI", "SKODA", "SEAT", "VAG", "CUPRA", "PORSCHE"}),
    frozenset({"OPEL", "VAUXHALL", "CHEVROLET", "DAEWOO", "GENERAL MOTORS", "PONTIAC", "ASÜNA", "BEDFORD"}),
    frozenset({"PEUGEOT", "CITROEN", "CITROËN", "FIAT", "LANCIA", "ALFA ROMEO"}),
    frozenset({"RENAULT", "DACIA", "NISSAN"}),
    frozenset({"HYUNDAI", "KIA"}),
)


def our_makes(name: str) -> set[str]:
    low = re.sub(r"[^0-9a-zа-яёіїєA-ZА-Я\- ]", " ", (name or "").lower())
    words = set(re.split(r"[ \-]+", low))
    found = {CAR_MAKES[w] for w in words if w in CAR_MAKES}
    for token, make in CAR_MAKES.items():
        if len(token) > 4 and token in low:
            found.add(make)
    return found


def _expand(makes: set[str]) -> set[str]:
    out = set(makes)
    for group in MAKE_GROUPS:
        if out & group:
            out |= group
    return out

#: Заголовок страницы поиска по номеру: «<номер> - <типы> OE number by<марки>».
_HEADLINE = re.compile(r"^\s*(?P<num>[0-9A-Za-z][0-9A-Za-z .\-/]*?)\s*-\s*(?P<types>.+?)\s*OE number by(?P<makers>.*)$", re.S)

#: Страница ничего не показала. Заголовок при этом выглядит нормальным.
_EMPTY = (
    "nothing matches your search",
    "autoteile online kaufen",
    "top ersatzteile",
)


def _norm(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def our_part_types(name: str) -> set[str]:
    low = (name or "").lower()
    return {key for key in PART_TYPES if key in low}


def verdict(name: str, number: str, headline: str) -> tuple[str, str]:
    """-> (вердикт, причина). Три исхода, как в задании."""

    head = (headline or "").strip()
    low = head.lower()
    if not head or any(marker in low for marker in _EMPTY):
        return "НЕ НАЙДЕНО", "каталог ничего не показал"

    match = _HEADLINE.match(head)
    if not match:
        # Слабый шаблон: перечень типов без блока производителей. Тип детали
        # он показывает, но подставную деталь того же типа отличить нечем.
        return "НЕ НАЙДЕНО", "не страница номера, решать не по чему"

    if _norm(match.group("num")) != _norm(number):
        return "НЕ НАЙДЕНО", "страница про другой номер"

    ours = our_part_types(name)
    if not ours:
        return "НЕ НАЙДЕНО", "тип детали из нашего названия не разобран"

    # Каталог перечисляет типы детали от главного к побочным, и хвост списка
    # бывает длиной в девять позиций. Совпадение в хвосте почти ничего не
    # значит: под «link set» на девятом месте подойдёт что угодно.
    types_low = ", ".join(match.group("types").lower().split(",")[:3])
    hit = next(
        (k for k in sorted(ours) if any(w in types_low for w in PART_TYPES[k])), None
    )
    if hit is None:
        return "ОПРОВЕРГНУТ", f"деталь другая: {match.group('types')[:60]} != {sorted(ours)}"

    # Тип детали сошёлся. Второй признак — марка. Номера в блоке производителей
    # это эхо нашего запроса, а вот сами марки мы не спрашивали, их назвал
    # каталог. Возражают они только когда обе стороны разобраны.
    page_makes = {
        m.strip().upper()
        for m in re.split(r"[,/]", match.group("makers"))
        if m.strip()
    }
    mine = our_makes(name)
    if mine and page_makes and not (_expand(mine) & _expand(page_makes)):
        return (
            "ОПРОВЕРГНУТ",
            f"машина другая: {sorted(page_makes)[:4]} != {sorted(mine)}",
        )
    return "ПОДТВЕРЖДЁН", f"{hit} -> {match.group('types')[:50]}"
