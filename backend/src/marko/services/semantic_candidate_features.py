"""Deterministic, provenance-bearing features for semantic product review.

The marketplace title is not identity evidence by itself, but it often contains
facts that can safely *disprove* identity: a contact group is not an ignition
lock housing, left is not right, and a four-pin connector is not a six-pin
connector.  This module extracts only a small closed vocabulary of such facts.

Positive similarity remains supporting evidence for the semantic reviewer.
Explicit contradictions are returned as fail-closed hard stops.  Missing
values stay UNKNOWN; no catalogue/search value is copied into the candidate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations
import json
import re
import unicodedata
from typing import Any


SEMANTIC_FEATURE_EXTRACTOR_VERSION = (
    "semantic-features-v43-transmission-mount"
)


@dataclass(frozen=True, slots=True)
class FeatureEvidence:
    value: str
    normalized_value: str
    source_field: str
    excerpt: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeatureSet:
    values: tuple[str, ...] = ()
    evidence: tuple[FeatureEvidence, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": "PRESENT" if self.values else "UNKNOWN",
            "values": list(self.values),
            "evidence": [item.as_dict() for item in self.evidence],
        }


_PART_PATTERNS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "electrical_connector",
        "sensor_connector",
        "connector",
        (
            r"\b(?:роз['’]?єм|разъем|конектор|коннектор)\w*\s+датчик\w*\b",
            r"\bsensor\s+connector\b",
        ),
    ),
    (
        "ignition_lock",
        "contact_group",
        "contact_group",
        (
            r"\bконтакт\w*\s+груп\w*\b",
            r"\bcontact\s+(?:group|switch)\b",
        ),
    ),
    (
        "ignition_lock",
        "lock_cylinder",
        "component",
        (
            r"\b(?:личинк|лічинк|серцевин)\w*[^\n]{0,30}(?:зажиган|запалюван)\w*\b",
            r"\b(?:вкладк|вставк|вкладиш)\w*[^\n]{0,25}(?:зам\w*[^\n]{0,15})?(?:зажиган|запалюван)\w*\b",
            r"\bignition\s+lock\s+cylinder\b",
            r"\bignition\s+lock\s+insert\b",
        ),
    ),
    (
        "ignition_lock",
        "housing",
        "housing",
        (
            r"\bкорпус\w*\s+зам\w*\s+(?:зажиган\w*|запал\w*)\b",
            r"\bignition\s+lock\s+housing\b",
        ),
    ),
    (
        "ignition_lock",
        "lock_assembly",
        "complete_assembly",
        (
            r"\bзам\w*\s+(?:зажиган\w*|запал\w*)[^\n]{0,45}(?:в\s+сборе|[ву]\s+зборі|в\s+складанні)\b",
            r"\b(?:в\s+сборе|[ву]\s+зборі|в\s+складанні)[^\n]{0,45}зам\w*\s+(?:зажиган\w*|запал\w*)\b",
            r"\bcomplete\s+ignition\s+lock(?:\s+assembly)?\b",
        ),
    ),
    (
        "ignition_lock",
        "",
        "",
        (
            r"\bзам\w*\s+(?:зажиган\w*|запал\w*)\b",
            r"\bignition\s+lock\b",
        ),
    ),
    (
        "sensor",
        "temperature_sensor",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,30}температ\w*\b",
            r"\bдатчик\w*\s+темп(?:\.|\b)",
            r"\bдатчик\w*\s+темпер(?:\.|\b)",
            r"\btemperature\s+sensor\b",
        ),
    ),
    (
        "sensor",
        "reverse_switch",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,30}задн\w*\s+ход\w*\b",
            r"\b(?:вимикач|выключател|лягушк)\w*[^\n]{0,25}задн\w*[^\n]{0,12}ход\w*\b",
            r"\breverse\s+(?:light\s+)?switch\b",
        ),
    ),
    (
        "sensor",
        "oxygen_sensor",
        "single_part",
        (
            r"\b(?:лямбда\s+зонд|датчик\w*\s+кислород\w*)\b",
            r"\bлямбд[ао]зонд\w*\b",
            r"\boxygen\s+sensor\b",
        ),
    ),
    (
        "sensor",
        "oil_pressure_sensor",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,30}(?:тиск|давлен)\w*[^\n]{0,20}(?:олив|масл)\w*\b",
            r"\boil\s+pressure\s+(?:sensor|switch)\b",
        ),
    ),
    (
        "sensor",
        "abs_sensor",
        "single_part",
        (
            r"\bдатчик\w*\s+(?:abs|абс)\b",
            r"\b(?:abs|абс)\s+датчик\w*\b",
            r"\babs\s+(?:wheel\s+speed\s+)?sensor\b",
        ),
    ),
    (
        "abs_system",
        "abs_ring",
        "component",
        (
            r"\b(?:кольц|кільц)\w*[^\n]{0,25}(?:abs|абс)\b",
            r"\babs\s+(?:reluctor|tone)\s+ring\b",
        ),
    ),
    (
        "sensor",
        "camshaft_position_sensor",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,35}(?:положен|положення)\w*[^\n]{0,25}(?:распредвал|розподілвал|розподільч\w*\s+вал)\w*\b",
            r"\bдатчик\w*\s+(?:распредвал|розпредвал|розпочила)\w*\b",
            r"\bcamshaft\s+position\s+sensor\b",
        ),
    ),
    (
        "sensor",
        "idle_control_sensor",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,30}холост\w*\s+ход\w*\b",
            r"\bidle\s+(?:air\s+)?control(?:\s+sensor|\s+valve)?\b",
        ),
    ),
    (
        "air_intake",
        "idle_air_control_valve",
        "single_part",
        (
            r"\b(?:клапан|регулятор)\w*[^\n]{0,25}холост\w*\s+ход\w*\b",
            r"\bidle\s+(?:air\s+)?control\s+valve\b",
        ),
    ),
    (
        "sensor",
        "mass_air_flow_sensor",
        "single_part",
        (
            r"\b(?:расходомер|витратомір)\w*(?:\s+повітря|\s+воздуха)?\b",
            r"\bmass\s+air\s+flow\s+sensor\b",
            r"\bmaf\s+sensor\b",
        ),
    ),
    (
        "electrical_switch",
        "brake_light_switch",
        "single_part",
        (
            r"\b(?:вимикач|выключател)\w*\s+стоп\w*(?:\s+сигнал\w*)?\b",
            r"\bвимикач\w*[^\n]{0,30}ліхтар\w*[^\n]{0,20}стоп\w*\b",
            r"\bbrake\s+light\s+switch\b",
        ),
    ),
    (
        "steering_column_switch",
        "turn_signal_switch",
        "single_part",
        (
            r"\b(?:перемикач|переключател)\w*[^\n]{0,25}(?:поворот|поврот|поворт)\w*\b",
            r"\bturn\s+signal\s+switch\b",
        ),
    ),
    (
        "steering_column_switch",
        "wiper_switch",
        "single_part",
        (
            r"\b(?:перемикач|переключател)\w*[^\n]{0,30}(?:склоочис|стеклоочис)\w*\b",
            r"\bперекл\.?[^\n]{0,15}стеклоочис\w*\b",
            r"\bwiper\s+switch\b",
        ),
    ),
    (
        "wiper_system",
        "wiper_blade",
        "single_part",
        (
            r"\b(?:щетк|щітк)\w*[^\n]{0,20}(?:дворник|склоочищ|стеклоочис)\w*\b",
            r"\bwiper\s+blade\b",
        ),
    ),
    (
        "ignition_system",
        "ignition_wire_set",
        "set",
        (
            r"\b(?:провод|дрот)\w*\s+(?:высоковольт|високовольт)\w*\b",
            r"\b(?:высоковольт|високовольт)\w*\s+(?:провод|дрот)\w*\b",
            r"\b(?:high[\s-]?tension|spark\s+plug)\s+wire\w*\b",
        ),
    ),
    (
        "ignition_system",
        "ignition_coil",
        "single_part",
        (
            r"\b(?:катушк\w*\s+зажиган|котушк\w*\s+запал)\w*\b",
            r"\bignition\s+coil\b",
        ),
    ),
    (
        "window_controls",
        "window_control_module",
        "module",
        (
            r"\b(?:блок|модул|модуль)\w*[^\n]{0,35}(?:управл|керув)\w*[^\n]{0,25}(?:склопід|стеклопод|склоопуск)\w*\b",
            r"\bwindow\s+(?:regulator\s+)?control\s+module\b",
        ),
    ),
    (
        "window_controls",
        "window_switch",
        "single_part",
        (
            r"\b(?:кнопк|блок\w*\s+(?:управл|керув))\w*[^\n]{0,35}(?:склопід|стеклопод|склоопуск)\w*\b",
            r"\bкнопк\w*[^\n]{0,20}ск\s*[/.-]\s*підймач\w*\b",
            r"\bwindow\s+(?:regulator\s+)?switch\b",
        ),
    ),
    (
        "window_controls",
        "window_crank_handle",
        "component",
        (
            r"\bручк\w*[^\n]{0,25}(?:стеклопод|склопід|склопідйом|склопідйом)н?\w*\b",
            r"\bручк\w*[^\n]{0,20}ск\s*[/.-]\s*підймач\w*\b",
            r"\bwindow\s+(?:regulator\s+)?crank(?:\s+handle)?\b",
        ),
    ),
    (
        "window_regulator",
        "window_regulator_motor",
        "complete_assembly",
        (
            r"\bмотор\w*[^\n]{0,25}(?:стеклоп|склоп)\w*\b",
            r"\bмотор\w*[^\n]{0,20}ск\s*[/.-]\s*підймач\w*\b",
        ),
    ),
    (
        "window_regulator",
        "window_regulator",
        "complete_assembly",
        (
            r"\b(?:ск|ст)\s*[/\.-]?\s*(?:подъемн|підйомн|підймач)\w*\b",
            r"\b(?:підйомник|підймач|стеклоподъемник|стеклопідіймач|склопід[іi]?йомник|склопідіймач)\w*\b",
            r"\bwindow\s+regulator\b",
        ),
    ),
    (
        "wiper_system",
        "wiper_motor",
        "complete_assembly",
        (
            r"\b(?:мотор|моторчик)\w*[^\n]{0,35}(?:стеклоочист|склоочис)\w*\b",
            r"\bwiper\s+motor\b",
        ),
    ),
    (
        "mirror",
        "mirror_assembly",
        "complete_assembly",
        (
            r"\b(?:зеркал|дзеркал)\w*(?:\s+(?:задн\w*\s+вид\w*|боков\w*))?\s+(?:лев|прав|лів)\w*\b",
            r"\b(?:лев|прав|лів)\w*\s+(?:зеркал|дзеркал)\w*\b",
            r"^\s*(?:зеркал|дзеркал)\w*\b",
            r"\b(?:left|right)\s+(?:door|side)\s+mirror\b",
        ),
    ),
    (
        "mirror",
        "mirror_glass",
        "component",
        (
            r"\b(?:вставк|вкладыш|вкладиш)\w*[^\n]{0,20}(?:зеркал|дзеркал)\w*\b",
            r"\bстекл\w*\s+зеркал\w*\b",
            r"\bmirror\s+glass\b",
        ),
    ),
    (
        "instrumentation",
        "instrument_cluster",
        "complete_assembly",
        (
            r"\bпанел\w*\s+прилад\w*\b",
            r"\b(?:instrument|gauge)\s+cluster\b",
        ),
    ),
    (
        "suspension_joint",
        "ball_joint",
        "single_part",
        (
            r"\bшаров\w*\s+оп+ор\w*\b",
            r"\bкульов\w*\s+оп+ор\w*\b",
            r"\bоп+ор\w*\s+(?:шаров|кульов)\w*\b",
            r"\bball\s+joint\b",
        ),
    ),
    (
        "driveline",
        "universal_joint",
        "single_part",
        (
            r"\b(?:крестовин|хрестовин)\w*(?:[^\n]{0,25}кардан\w*)?\b",
            r"\b(?:propshaft\s+)?universal\s+joint\b",
        ),
    ),
    (
        "cv_joint",
        "tripod_joint",
        "single_part",
        (
            r"\b(?:шрус|шркш)\w*[^\n]{0,25}(?:тр(?:е|и)шип|треш|трьохшип|трипод)\w*\b",
            r"\b(?:тришип|трешип|трьохшип|трипод)\w*\b",
            r"\btripod\s+(?:cv\s+)?joint\b",
        ),
    ),
    (
        "cv_joint",
        "cv_joint",
        "single_part",
        (r"\b(?:шрус|шркш|граната)\w*\b", r"\bcv\s+joint\b"),
    ),
    (
        "clutch_hydraulics",
        "clutch_master_cylinder",
        "complete_assembly",
        (
            r"\b(?:цилиндр|циліндр)\w*\s+(?:сцеплен|зчеплен)\w*\s+(?:главн|головн)\w*\b",
            r"\b(?:главн|головн)\w*\s+(?:тормозн\w*\s+)?(?:цилиндр|циліндр)\w*[^\n]{0,25}(?:сцеплен|зчеплен)\w*\b",
            r"\bclutch\s+master\s+cylinder\b",
        ),
    ),
    (
        "clutch_hydraulics",
        "clutch_slave_cylinder",
        "complete_assembly",
        (
            r"\b(?:цилиндр|циліндр)\w*\s+(?:сцеплен|зчеплен)\w*\s+(?:рабоч|робоч)\w*\b",
            r"\b(?:рабоч|робоч)\w*\s+(?:цилиндр|циліндр)\w*[^\n]{0,25}(?:сцеплен|зчеплен)\w*\b",
            r"\bclutch\s+slave\s+cylinder\b",
        ),
    ),
    (
        "clutch",
        "clutch_disc",
        "single_part",
        (
            r"\bдиск\w*\s+(?:сцепл|зчепл)\w*\b",
            r"\bclutch\s+disc\b",
        ),
    ),
    (
        "clutch",
        "release_bearing_guide",
        "component",
        (
            r"\b(?:направл|нарпавл|напрямн|спрямовуюч)\w*[^\n]{0,30}(?:выжимн|вижимн|витискн|вибивн)\w*[^\n]{0,20}(?:підшипник|подшипник)\w*\b",
            r"\bclutch\s+release\s+bearing\s+(?:guide|sleeve)\b",
        ),
    ),
    (
        "clutch",
        "release_bearing",
        "single_part",
        (
            r"\b(?:підшипник|подшипник)\w*\s+(?:выжимн|вижимн|витискн)\w*\b",
            r"\bclutch\s+release\s+bearing\b",
        ),
    ),
    (
        "clutch",
        "clutch_pressure_plate",
        "single_part",
        (
            r"\bкорзин\w*\s+сцеплен\w*\b",
            r"\bкорзин\w*\s+зчепл\w*\b",
            r"\bкошик\w*\s+зчепл\w*\b",
            r"\bclutch\s+pressure\s+plate\b",
        ),
    ),
    (
        "clutch",
        "clutch_kit",
        "kit",
        (
            r"\bкомплект\w*\s+сцеплен\w*\b",
            r"\bкомплект\w*\s+зчеплен\w*\b",
            r"\bclutch\s+kit\b",
        ),
    ),
    (
        "cooling_pump",
        "water_pump_impeller",
        "component",
        (
            r"\b(?:крыльчатк|крильчатк)\w*[^\n]{0,35}(?:водян\w*\s+)?(?:помп|насос)\w*\b",
            r"\bwater\s+pump\s+impeller\b",
        ),
    ),
    (
        "cooling_pump",
        "water_pump",
        "single_part",
        (
            r"\b(?:водян\w*\s+помп|водян\w*\s+насос)\w*\b",
            r"\bпомп\w*\s+водян\w*\b",
            r"\bпомп\w*\b",
            r"\bwater\s+pump\b",
        ),
    ),
    (
        "ac_compressor",
        "compressor_clutch",
        "component",
        (
            r"\b(?:муфт|муфта)\w*[^\n]{0,35}(?:компрессор|компресор)\w*[^\n]{0,25}(?:кондиц|кондиціон)\w*\b",
            r"\b(?:a/?c|air\s+conditioning)\s+compressor\s+clutch\b",
        ),
    ),
    (
        "ac_compressor",
        "ac_compressor",
        "complete_assembly",
        (
            r"\b(?:компрессор|компресор)\w*[^\n]{0,35}(?:кондиц|кондиціон)\w*\b",
            r"\b(?:a/?c|air\s+conditioning)\s+compressor\b",
        ),
    ),
    (
        "fuel_system",
        "fuel_injector_repair_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,35}(?:форсун|инжектор)\w*\b",
            r"\b(?:форсун|инжектор)\w*[^\n]{0,35}ремкомплект\w*\b",
            r"\bfuel\s+injector\s+(?:repair|service)\s+kit\b",
        ),
    ),
    (
        "fuel_system",
        "fuel_injector",
        "single_part",
        (
            r"\b(?:форсунк|инжектор)\w*\b",
            r"\bfuel\s+injector\b",
        ),
    ),
    (
        "fuel_system",
        "fuel_pickup_strainer",
        "component",
        (
            r"\bс(?:і|и)тк\w*\s+(?:паливозабірн|топливозаборн)\w*\b",
            r"\bfuel\s+(?:pickup\s+)?strainer\b",
        ),
    ),
    (
        "fuel_system",
        "fuel_pump",
        "single_part",
        (
            r"\b(?:паливн|топливн)\w*\s+насос\w*\b",
            r"\bнасос\w*[^\n]{0,25}(?:підкач|подкач)\w*[^\n]{0,20}(?:палив|топлив)\w*\b",
            r"\bбензонасос\w*\b",
            r"\bfuel\s+pump\b",
        ),
    ),
    (
        "fuel_system",
        "fuel_tank_cap",
        "single_part",
        (
            r"\bкрышк\w*[^\n]{0,80}топливн\w*\s+бак\w*\b",
            r"\bкришк\w*[^\n]{0,80}паливн\w*\s+бак\w*\b",
            r"\b(?:крышк|кришк)\w*\s+бак\w*\b",
            r"\b(?:крышк|кришк)\w*\s+бензобак\w*\b",
            r"\bfuel\s+tank\s+cap\b",
        ),
    ),
    (
        "engine_lubrication",
        "oil_filler_cap",
        "single_part",
        (
            r"\b(?:крышк|кришк)\w*[^\n]{0,35}(?:масл|олив)\w*[^\n]{0,25}(?:залив|заливн|горловин)\w*\b",
            r"\b(?:крышк|кришк)\w*\s+(?:залив|заливк)\w*\s+(?:масл|олив)\w*\b",
            r"\b(?:крышк|кришк)\w*\s*[,;:-]?\s*(?:залив|заливн)\w*[^\n]{0,25}(?:горловин\w*[^\n]{0,15})?(?:масл|олив)\w*\b",
            r"\bмаслозаливн\w*\s+крышк\w*\b",
            r"\boil\s+filler\s+cap\b",
        ),
    ),
    (
        "engine_lubrication",
        "dipstick_guide",
        "component",
        (
            r"\b(?:пласмаск|пластмасс?|направл|напрямн|трубк)\w*[^\n]{0,20}щуп\w*\b",
            r"\boil\s+dipstick\s+(?:guide|tube)\b",
        ),
    ),
    (
        "engine_lubrication",
        "oil_dipstick",
        "single_part",
        (
            r"^\s*щуп\w*[^\n]{0,30}(?:уровн|рівн)\w*[^\n]{0,20}(?:масл|олив)\w*\b",
            r"\boil\s+dipstick\b",
        ),
    ),
    (
        "brake_vacuum",
        "brake_vacuum_pump",
        "complete_assembly",
        (
            r"\bвакуумн\w*\s+насос\w*(?:[^\n]{0,25}(?:гальм|тормоз)\w*)?\b",
            r"\bвакумн\w*\s+насос\w*(?:[^\n]{0,25}(?:гальм|тормоз)\w*)?\b",
            r"\bнасос\w*\s+вакуумн\w*[^\n]{0,50}(?:mb|mercedes|мерседес|om\s*\d+)\b",
            r"\bbrake\s+vacuum\s+pump\b",
        ),
    ),
    (
        "electrical_charging",
        "alternator_brush_holder",
        "component",
        (
            r"\b(?:генератор\w*[^\n]{0,30}(?:щеточ|щітк)\w*|(?:щеточ|щітк)\w*[^\n]{0,30}генератор\w*)\b",
            r"\balternator\s+brush(?:\s+holder)?\b",
        ),
    ),
    (
        "starting_system",
        "starter_components",
        "component",
        (
            r"\bз\s*/\s*ч\s+на\s+стартер\w*\b",
            r"\b(?:бендикс|щіткотримач|щеткодержател)\w*[^\n]{0,30}стартер\w*\b",
            r"\bбендикс\w*\b",
            r"\bstarter\s+(?:parts|components|repair\s+kit)\b",
        ),
    ),
    (
        "starting_system",
        "starter_assembly",
        "complete_assembly",
        (r"\bстартер\w*\b", r"\bstarter\s+motor\b"),
    ),
    (
        "hvac",
        "heater_housing",
        "housing",
        (
            r"\bкорпус\w*\s+(?:пічк|печк|обігрівач|обогреват)\w*\b",
            r"\bheater\s+housing\b",
        ),
    ),
    (
        "hvac",
        "blower_resistor",
        "component",
        (
            r"\b(?:опір|сопротивлен)\w*[^\n]{0,25}(?:вентилятор|пічк|печк|печ[іи])\w*\b",
            r"\bblower\s+(?:motor\s+)?resistor\b",
        ),
    ),
    (
        "hvac",
        "cabin_blower",
        "complete_assembly",
        (
            r"\b(?:моторчик|мотор|вентилятор)\w*[^\n]{0,35}(?:пічк|печк|печ[іи]|печеньк|салон|каб[iіи]н?)\w*\b",
            r"\bвентилятор\w*\s+(?:обігрівач|обогревател)\w*\b",
            r"\bcabin\s+blower\b",
        ),
    ),
    (
        # Must precede ``top_mount``: "Опорный подшипник амортизатора" contains
        # the bare top-mount wording, and the first matching rule wins.  The
        # same ordering defect was reported twice before (2026-08-05 shadow
        # defects #2 and #9) and still cost 16 live candidates on 2026-08-06.
        "suspension",
        "top_mount_bearing",
        "single_part",
        (
            # ``опор\w*`` rather than ``опорн\w*``: the genitive "верхньої
            # опори" is the same part as the nominative "верхний опорный".
            r"\b(?:підшипник|подшипник)\w*\s+верхн\w*\s+опор\w*\b",
            r"\b(?:підшипник|подшипник)\w*[^\n]{0,30}(?:амортизатор|ст[оі]йк)\w*\b",
            r"\b(?:підшипник|подшипник)\w*\s+опор\w*[^\n]{0,25}ст[оі]йк\w*\b",
            r"\bопорн\w*\s+(?:підшипник|подшипник)\w*\b",
            # A top mount sold with its bearing is that assembly, not a bare
            # mount and not the absorber the wording also names.
            r"\bподушк\w*\s+амортизатор\w*[^\n]{0,20}(?:з|с|із)\s+(?:підшипник|подшипник)\w*\b",
            r"\bstrut\s+top\s+bearing\b",
        ),
    ),
    (
        "suspension",
        "top_mount",
        "single_part",
        (
            r"\bподушк\w*[^\n]{0,25}(?:верх(?:н\w*)?\.?\s*опорн\w*|опор\w*\s+амортизатор\w*)\b",
            r"\bопор\w*[^\n]{0,25}амортизатор\w*\b",
            r"\bstrut\s+top\s+mount\b",
        ),
    ),
    (
        "engine_mount",
        "engine_mount_bracket",
        "component",
        (
            r"\bкронштейн\w*[^\n]{0,30}(?:опор\w*\s+)?двиг\w*\b",
            r"\bengine\s+mount\s+bracket\b",
        ),
    ),
    (
        # Must precede ``engine_or_transmission_mount``: that subtype names an
        # ambiguity its own patterns do not have.  ``подушка двигателя`` says
        # engine and ``подушка КПП`` says gearbox, and collapsing both let the
        # semantic gate confirm a match between two different sellable parts.
        "engine_mount",
        "transmission_mount",
        "single_part",
        (
            r"\bподушк\w*[^\n]{0,35}(?:кпп|акпп|мкпп|мкп|акп|коробк\w*\s+передач)\w*\b",
            r"\bопор\w*[^\n]{0,35}(?:кпп|акпп|мкпп|коробк\w*\s+передач)\w*\b",
            r"\btransmission\s+mount\b",
        ),
    ),
    (
        "engine_mount",
        "engine_or_transmission_mount",
        "single_part",
        (
            r"\bподушк\w*[^\n]{0,25}(?:двигат|двигател|двигун)\w*\b",
            r"\bопор\w*[^\n]{0,25}(?:двигат|двигател|двигун)\w*\b",
            r"\bengine\s+mount\b",
        ),
    ),
    (
        "vehicle_mount",
        "cab_buffer",
        "single_part",
        (
            r"\bбуфер\w*[^\n]{0,35}(?:кабін|кабин)\w*\b",
            r"\bcab\s+(?:mount|buffer)\b",
        ),
    ),
    (
        "suspension",
        "control_arm_bushing",
        "single_part",
        (
            r"\b(?:сайлент?блок|сал[іи]нблок)\w*[^\n]{0,25}(?:рычаг|ричаг|важел)\w*\b",
            r"\bcontrol\s+arm\s+bushing\b",
        ),
    ),
    (
        "suspension",
        "axle_beam_bushing",
        "single_part",
        (
            r"\b(?:сайлентблок|сал[іи]нблок)\w*[^\n]{0,25}(?:балк|підрамник|подрамник)\w*\b",
            r"\b(?:axle\s+beam|subframe)\s+bushing\b",
        ),
    ),
    (
        "generic_bushing",
        "generic_bushing_set",
        "set",
        (
            r"\bкомплект\w*[^\n]{0,55}(?:сайлент?блок|сал[іи]нблок)\w*\b",
            r"\b(?:silentblock|silent\s+block)\s+set\b",
        ),
    ),
    (
        "suspension",
        "stabilizer_bracket",
        "component",
        (
            r"\b(?:кронштейн|кронштейн)\w*[^\n]{0,25}(?:стабилизатор|стабілізатор)\w*\b",
            r"\bstabili[sz]er\s+(?:bar\s+)?bracket\b",
        ),
    ),
    (
        "suspension",
        "stabilizer_link",
        "single_part",
        (
            r"\b(?:стойк|стійк)\w*[^\n]{0,25}(?:стабилизатор|стабілізатор)\w*\b",
            r"\b(?:стойк|стійк)\w*[^\n]{0,15}стаб\s*\.?(?=\s|$)",
            r"\bтяг\w*\s+(?:стабилизатор|стабілізатор)\w*\b",
            r"\bstabili[sz]er\s+(?:bar\s+)?link\b",
        ),
    ),
    (
        "suspension",
        "stabilizer_bushing",
        "single_part",
        (
            r"\bвтулк\w*[^\n]{0,25}(?:стабилизатор|стабілізатор)\w*\b",
            r"\bstabili[sz]er\s+bushing\b",
        ),
    ),
    (
        "gas_spring",
        "body_gas_spring",
        "single_part",
        (
            r"\bамортизатор\w*[^\n]{0,35}(?:кришк|крышк)\w*\s+багажник\w*\b",
            r"\bамортизатор\w*[^\n]{0,25}багажник\w*\b",
            r"\bгазов\w*\s+пружин\w*\b",
            r"\b(?:trunk|tailgate|hood)\s+(?:lid\s+)?gas\s+(?:spring|strut)\b",
        ),
    ),
    (
        "suspension",
        "spring_seat",
        "component",
        (r"\bопорн\w*[^\n]{0,15}чашк\w*[^\n]{0,30}пруж\w*\b",),
    ),
    (
        "suspension",
        "coil_spring",
        "single_part",
        (r"\bпружин\w*\b", r"\bcoil\s+spring\b"),
    ),
    (
        "suspension",
        "control_arm_repair_kit",
        "kit",
        (r"\bремкомплект\w*[^\n]{0,20}(?:рычаг|важел)\w*\b",),
    ),
    (
        "suspension",
        "control_arm",
        "single_part",
        (
            r"\b(?:рычаг|важіль)\w*\b",
            r"\bcontrol\s+arm\b",
        ),
    ),
    (
        "door_lock",
        "lock_striker",
        "component",
        (
            r"\b(?:скоб|ригел|щеколд|фіксатор|фиксатор)\w*[^\n]{0,30}замк\w*[^\n]{0,20}двер\w*\b",
            r"\bdoor\s+lock\s+striker\b",
        ),
    ),
    (
        "door_lock",
        "lock_set",
        "set",
        (
            r"\bкомплект\w*\s+замк\w*\b",
            r"\block\s+set\b",
        ),
    ),
    (
        "door_lock",
        "trunk_lock",
        "complete_assembly",
        (
            r"\bзамок\w*\s+багажник\w*\b",
            r"\bзамок\w*[^\n]{0,25}(?:кришк|крышк)\w*[^\n]{0,20}багажник\w*\b",
            r"\btrunk\s+lock\b",
        ),
    ),
    (
        "door_lock",
        "door_lock",
        "complete_assembly",
        (
            r"\bзамок\w*\s+двер\w*\b",
            r"\bdoor\s+lock\b",
        ),
    ),
    (
        "door_hardware",
        "door_handle_mechanism",
        "component",
        (
            r"\b(?:механизм|механізм)\w*[^\n]{0,30}(?:ручк|ручц)\w*[^\n]{0,25}двер\w*\b",
            r"\bdoor\s+handle\s+mechanism\b",
            r"\bhandle\s+mechanism\b",
        ),
    ),
    (
        "door_hardware",
        "door_handle",
        "single_part",
        (
            r"\bручк\w*\s+двер\w*\b",
            r"\bручк\w*\s+двері\b",
            r"\bручк\w*\s+(?:зовнішн|наружн)\w*[^\n]{0,25}(?:підіймал|подъемн)\w*\b",
            r"\bdoor\s+handle\b",
        ),
    ),
    (
        "door_hardware",
        "sliding_door_bracket",
        "component",
        (
            r"^\s*кронштейн\w*[^\n]{0,45}(?:зсувн|сдвижн|бічн|боков|сувальн|ковзн|розсувн)\w*[^\n]{0,20}двер\w*\b",
            r"^\s*кронштейн\w*[^\n]{0,20}двер\w*[^\n]{0,35}(?:зсувн|сдвижн|бічн|боков|сувальн|ковзн|розсувн)\w*\b",
            r"\bsliding\s+door\s+bracket\b",
        ),
    ),
    (
        "door_hardware",
        "sliding_door_roller",
        "single_part",
        (
            r"\b(?:ролик|бігунок|бегунок)\w*[^\n]{0,45}(?:зсувн|сдвижн|бічн|боков|сувальн|ковзн|розсувн)\w*[^\n]{0,20}двер\w*\b",
            r"\b(?:ролик|бігунок|бегунок)\w*[^\n]{0,20}двер\w*[^\n]{0,30}(?:зсувн|сдвижн|бічн|боков|сувальн|ковзн|розсувн)\w*\b",
            r"\bsliding\s+door\s+roller\b",
        ),
    ),
    (
        "door_hardware",
        "",
        "",
        (
            r"\b(?:направляющ|направляюч|напрямн)\w*[^\n]{0,35}(?:сдвижн|зсувн|боков|бічн)\w*[^\n]{0,20}двер\w*\b",
            r"\b(?:направляющ|направляюч|напрямн)\w*[^\n]{0,25}двер\w*[^\n]{0,30}(?:сдвижн|зсувн|боков|бічн)\w*\b",
            r"\bsliding\s+door\s+guide\b",
        ),
    ),
    (
        "engine_component",
        "valve_cover_repair_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,35}клапан\w*\s+кр(?:ыш|иш)\w*\b",
            r"\bvalve\s+cover\s+repair\s+kit\b",
        ),
    ),
    (
        "oil_seal",
        "camshaft_oil_seal",
        "single_part",
        (
            r"\bсальник\w*[^\n]{0,30}(?:розподвал|розподілвал|розподільвал|распредвал|розподільч\w*\s+вал|распределительн\w*\s+вал)\w*\b",
            r"\bcamshaft\s+oil\s+seal\b",
        ),
    ),
    (
        "engine_internal",
        "camshaft",
        "single_part",
        (
            r"\b(?:розподільч|распределительн)\w*\s+вал\w*\b",
            r"\bcamshaft\b",
        ),
    ),
    (
        "engine_internal",
        "piston_ring_set",
        "set",
        (
            r"\b(?:кольц|кільц)\w*\s+(?:поршнев|поршн)\w*\b",
            r"\bpiston\s+ring\s+set\b",
        ),
    ),
    (
        "engine_bearing",
        "connecting_rod_bearing",
        "set",
        (
            r"\b(?:вкладиш|вкладыш)\w*\s+(?:шатун|шатуна)\w*\b",
            r"\bвклад\w*\.?\s*шатун\w*\.?\b",
            r"\bconnecting\s+rod\s+bearing\w*\b",
        ),
    ),
    (
        "engine_bearing",
        "main_bearing",
        "set",
        (
            r"\b(?:вкладиш|вкладыш)\w*\s+(?:корінн|коренн)\w*\b",
            r"\bmain\s+engine\s+bearing\w*\b",
        ),
    ),
    (
        "engine_bearing",
        "crankshaft_thrust_washer",
        "set",
        (
            r"\b(?:вкладиш|вкладыш|шайб)\w*[^\n]{0,25}(?:разбег|осев)\w*[^\n]{0,25}(?:коленвал|колленвал|колінвал)\w*\b",
            r"\b(?:полукольц|півкільц)\w*[^\n]{0,25}(?:коленвал|колленвал|колінвал)\w*\b",
            r"\bcrankshaft\s+thrust\s+(?:washer|bearing)\w*\b",
        ),
    ),
    (
        "engine_bearing",
        "camshaft_bearing",
        "set",
        (
            r"\b(?:вкладиш|вкладыш)\w*[^\n]{0,25}(?:распредвал|розподілвал|розпредвал)\w*\b",
            r"\bcamshaft\s+bearing\w*\b",
        ),
    ),
    (
        "engine_internal",
        "rocker_arm",
        "single_part",
        (
            r"^\s*(?:коромисло|рокер)\w*(?:\s|$)",
            r"\bengine\s+rocker\s+arm\b",
        ),
    ),
    (
        "coolant_reservoir",
        "expansion_tank_cap",
        "component",
        (
            r"\b(?:кришк|крышк)\w*[^\n]{0,35}(?:розшир|расшир)\w*\s+бачк\w*\b",
            r"\b(?:кришк|крышк)\w*[^\n]{0,20}бачк\w*[^\n]{0,20}(?:розшир|расшир)\w*\b",
            r"\b(?:кришк|крышк)\w*[^\n]{0,20}бачк\w*[^\n]{0,30}(?:охолодж|охлажд)\w*\b",
            r"\bexpansion\s+tank\s+cap\b",
            r"\bcoolant\s+reservoir\s+cap\b",
        ),
    ),
    (
        "coolant_reservoir",
        "expansion_tank",
        "single_part",
        (
            r"\bбач(?:ок|ек)\w*\s+(?:розшир|расшир)\w*\b",
            r"\bexpansion\s+tank\b",
        ),
    ),
    (
        "coolant_flange",
        "coolant_sensor_flange",
        "component",
        (
            r"\b(?:фланш|фланец|фланець)\w*[^\n]{0,30}датчик\w*\b",
            r"\b(?:фланш|фланец|фланець)\w*[^\n]{0,40}(?:охлажд|охолодж)\w*\b",
            r"\b(?:фланш|фланец|фланець)\w*\s+(?:головк|блок)\w*\b",
            r"\bcoolant\s+(?:sensor\s+)?flange\b",
        ),
    ),
    (
        "washer_system",
        "washer_reservoir",
        "single_part",
        (
            r"\bбач(?:ок|ек)\w*\s+омывател\w*\b",
            r"\bwasher\s+(?:fluid\s+)?reservoir\b",
        ),
    ),
    (
        "steering_reservoir",
        "reservoir_cap",
        "component",
        (
            r"\b(?:крышк|кришк)\w*[^\n]{0,35}бачк\w*[^\n]{0,20}(?:гур|гпр|гідропідсил\w*|гидроусил\w*)\b",
            r"\b(?:power\s+steering|steering)\s+(?:fluid\s+)?reservoir\s+cap\b",
        ),
    ),
    (
        "steering_reservoir",
        "reservoir",
        "single_part",
        (
            r"\bбачок\w*\s+(?:гур|гпр|гідропідсил\w*|гидроусил\w*)\b",
            r"\bбачок\w*\s+г\s*/\s*[уп]\b(?:\s+(?:рул|керм)\w*)?",
            r"\bpower\s+steering\s+(?:fluid\s+)?reservoir\b",
        ),
    ),
    (
        "steering",
        "power_steering_pulley",
        "component",
        (
            r"\b(?:шкив|шків|шков)\w*[^\n]{0,30}(?:насос\w*\s+)?(?:гур|гпк|гідропідсил|гідросил|гидроусил|г\s*[./-]?\s*[уy])\w*\b",
            r"\bpower\s+steering\s+pump\s+pulley\b",
        ),
    ),
    (
        "steering",
        "power_steering_pump_repair_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,35}насос\w*[^\n]{0,25}(?:гур|гпк|гідропідсил|гідроусил|гидроусил)\w*\b",
            r"\bкомплект\w*\s+проклад\w*[^\n]{0,30}насос\w*\s+(?:гур|гпк)\b",
            r"\bpower\s+steering\s+pump\s+(?:repair|gasket|seal)\s+(?:kit|set)\b",
        ),
    ),
    (
        "steering",
        "power_steering_pump",
        "complete_assembly",
        (
            r"\bнасос\w*[^\n]{0,25}(?:гур|гпк|гідропідсил|гідроусил|гидроусил)\w*\b",
            r"\bpower\s+steering\s+pump\b",
        ),
    ),
    (
        "steering",
        "steering_column_joint",
        "single_part",
        (
            r"\bкарданчик\w*[^\n]{0,25}(?:рулев|рульов|кермов)\w*\b",
            r"\bкарданчик\w*[^\n]{0,15}рул\.?[^\n]{0,15}рейк\w*\b",
            r"\bsteering\s+column\s+joint\b",
        ),
    ),
    (
        "steering",
        "steering_rack_boot",
        "component",
        (
            r"\b(?:пыльник|пильник|пиловик|пильовик)\w*[^\n]{0,30}(?:рулев|рульов|кермов)\w*\s+рейк\w*\b",
            r"\bsteering\s+rack\s+(?:boot|gaiter)\b",
        ),
    ),
    (
        "steering",
        "steering_rack_repair_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,30}(?:рулев|кермов)\w*\s+рейк\w*\b",
            r"\bремкомплект\w*\s+(?:рулев|кермов)\w*\b",
            r"\bsteering\s+rack\s+repair\s+kit\b",
        ),
    ),
    (
        "steering",
        "steering_rack",
        "complete_assembly",
        (
            r"\b(?:рулев|рульов|кермов)\w*\s+рейк\w*\b",
            r"\bрейк\w*\s+(?:рулев|рульов|кермов)\w*\b",
            r"\bsteering\s+rack\b",
        ),
    ),
    (
        "steering",
        "tie_rod_end",
        "single_part",
        (
            r"\bнаконечник\w*[^\n]{0,25}(?:рулев|рульов|кермов)\w*\s+тяг\w*\b",
            r"\bнаконечник\w*\s+(?:рульов|кермов|керм)\w*\b",
            r"\bнакінечник\w*[^\n]{0,25}(?:рульов|керм)\w*\b",
            r"\bнакинечник\w*[^\n]{0,25}(?:рульов|керм)\w*\b",
            r"\b(?:рулев|рульов|кермов)\w*\s+(?:наконечник|накінечник|накинечник)\w*\b",
            r"\bнаконечн\w*\.?\s*р\.?\s*т\.?\b",
            r"\btie\s+rod\s+end\b",
        ),
    ),
    (
        "steering",
        "tie_rod",
        "single_part",
        (
            r"\bтяг\w*\s+(?:рулев|рульов|кермов)\w*\b",
            r"\bтяг\w*\s+керм\w*\b",
            r"\btie\s+rod\b",
        ),
    ),
    (
        "seat_hardware",
        "seat_extension_handle",
        "component",
        (
            r"\bручк\w*[^\n]{0,35}(?:подовжувач|удлинител)\w*[^\n]{0,20}сидін\w*\b",
            r"\bseat\s+extension\s+handle\b",
        ),
    ),
    (
        "body_grille",
        "bumper_grille",
        "single_part",
        (
            r"\bреш[іиое]тк\w*[^\n]{0,25}бампер\w*\b",
            r"\bbumper\s+grill(?:e)?\b",
        ),
    ),
    (
        "body_trim",
        "bumper_corner",
        "component",
        (
            r"\b(?:клик|клык|ікло|икло|кут)\w*[^\n]{0,25}бампер\w*\b",
            r"\bbumper\s+(?:corner|end)\b",
        ),
    ),
    (
        "body_grille",
        "radiator_grille",
        "single_part",
        (
            r"\bреш(?:і|и)т\w*\s+(?:в\s+)?(?:бампер\w*\s+)?(?:радіатор|радiатор|радиатор)\w*\b",
            r"\bradiator\s+grill(?:e)?\b",
        ),
    ),
    (
        "body_panel",
        "radiator_support_panel",
        "complete_assembly",
        (
            r"\bпередн\w*\s+панел\w*[^\n]{0,25}(?:телевізор|телевизор)\w*\b",
            r"\bradiator\s+support\s+panel\b",
        ),
    ),
    (
        "radiator_component",
        "radiator_cap",
        "component",
        (
            r"\b(?:крышк|кришк)\w*[^\n]{0,25}(?:радіатор|радiатор|радиатор)\w*\b",
            r"\bradiator\s+cap\b",
        ),
    ),
    (
        "radiator_component",
        "radiator_tank",
        "component",
        (
            r"\bбачок\w*\s+(?:радіатор|радiатор|радиатор)\w*\b",
            r"\bradiator\s+tank\b",
        ),
    ),
    (
        "cooling_fan",
        "fan_impeller",
        "component",
        (
            r"\b(?:крыльчатк|крильчатк)\w*[^\n]{0,30}вентилятор\w*\b",
            r"\b(?:крыльчатк|крильчатк)\w*[^\n]{0,30}термомуфт\w*\b",
            r"\b(?:fan\s+impeller|fan\s+blade)\b",
        ),
    ),
    (
        "cooling_fan",
        "fan_clutch",
        "single_part",
        (
            r"\b(?:термомуфт|тетмомуфт|в[іи]скомуфт)\w*\b",
            r"\b(?:viscous\s+)?fan\s+clutch\b",
        ),
    ),
    (
        "cooling_fan",
        "fan_module",
        "complete_assembly",
        (
            r"\b(?:дифузор|диффузор)\w*[^\n]{0,30}вентилятор\w*[^\n]{0,20}(?:[ву]\s+зборі|в\s+сборе|у\s+зборі)\b",
            r"\b(?:дифузор|диффузор)\w*[^\n]{0,40}(?:с|з)\s+мотор\w*\b",
            r"\bвентилятор\w*[^\n]{0,30}(?:[ву]\s+зборі|в\s+сборе|у\s+зборі)\b",
            r"\bcomplete\s+(?:radiator|cooling)\s+fan\s+(?:module|assembly)\b",
        ),
    ),
    (
        "cooling_fan",
        "fan_shroud",
        "housing",
        (
            r"\b(?:дифузор|диффузор)\w*[^\n]{0,35}(?:вентилятор|радіатор|радiатор|радиатор)\w*\b",
            r"\bfan\s+shroud\b",
        ),
    ),
    (
        "cooling_fan",
        "cooling_fan_motor",
        "component",
        (
            r"\bмотор\w*[^\n]{0,35}(?:радіатор|радiатор|радиатор)\w*[^\n]{0,120}без\s+(?:крыльчатк|крильчатк)\w*\b",
            r"\b(?:cooling|radiator)\s+fan\s+motor\b",
        ),
    ),
    (
        "cooling_fan",
        "generic_cooling_fan_motor",
        "",
        (
            r"^(?![^\n]*(?:крыльчат|крильчат))\s*мотор\w*[^\n]{0,35}(?:радіатор|радiатор|радиатор)\w*(?:\s|$)",
        ),
    ),
    (
        "cooling_fan",
        "engine_cooling_fan",
        "complete_assembly",
        (
            r"\bмотор\w*[^\n]{0,35}(?:радіатор|радiатор|радиатор)\w*[^\n]{0,120}(?:с|з)\s+(?:крыльчатк|крильчатк)\w*\b",
            r"\b(?:вентилятор|вентилятор|дифузор)\w*[^\n]{0,50}(?:радіатор|радiатор|радиатор)\w*\b",
            r"\b(?:вентилятор|вентилятор)\w*[^\n]{0,50}охлажд\w*\s+двиг\w*\b",
            r"\bвентилятор\w*[^\n]{0,50}охолодж\w*(?:\s+двиг\w*)?\b",
            r"\bвентилятор\w*\s+радіат\.?\w*\b",
            r"\b(?:radiator|engine\s+cooling)\s+fan\b",
        ),
    ),
    (
        "crankcase_ventilation",
        "breather_hose",
        "single_part",
        (
            r"\b(?:патрубок|шланг|трубк)\w*[^\n]{0,35}(?:вентиляц\w*\s+картер|сапун)\w*\b",
            r"\b(?:трубк|патрубок|шланг)\w*\s+сапун\w*\b",
            r"\bcrankcase\s+(?:ventilation|breather)\s+(?:hose|pipe)\b",
        ),
    ),
    (
        "coolant_hose",
        "radiator_hose",
        "single_part",
        (
            r"\b(?:патрубок|патрубок|шланг)\w*[^\n]{0,30}(?:радіатор|радiатор|радиатор|охолоджен|охлажден)\w*\b",
            r"\bradiator\s+(?:coolant\s+)?hose\b",
        ),
    ),
    (
        "oil_cooler",
        "transmission_oil_cooler",
        "single_part",
        (
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+(?:оливн|маслян)\w*[^\n]{0,140}(?:[aа][kк][pп]{1,2}|automatic\s+transmission)\b",
            r"\b(?:оливн|маслян)\w*\s+(?:охолоджувач|охладител)\w*[^\n]{0,60}(?:[aа][kк][pп]{1,2}|automatic\s+transmission)\b",
            r"\btransmission\s+oil\s+cooler\b",
        ),
    ),
    (
        "oil_cooler",
        "oil_cooler",
        "single_part",
        (
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+(?:оливн|маслян)\w*\b",
            r"\b(?:оливн|маслян)\w*\s+(?:охолоджувач|охладител)\w*\b",
            r"\boil\s+cooler\b",
        ),
    ),
    (
        "radiator",
        "heater_core",
        "single_part",
        (
            r"\b(?:радіатор|радiатор|радиатор)\w*[^\n]{0,35}(?:пічк|печк|печі|печи|опален|отопител|обігрівач|обогрев)\w*\b",
            r"\bheater\s+core\b",
        ),
    ),
    (
        "radiator",
        "ac_condenser",
        "single_part",
        (
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+кондиц(?:іон|iон|ион)\w*\b",
            r"\bradiator\w*\s+kondicioner\w*\b",
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+конденсатор\w*\b",
            r"\bконденсатор\w*[^\n]{0,25}кондиц(?:іон|ион)\w*\b",
            r"\bконденс(?:атор|ер|ор)\w*\b",
            r"\b(?:a/?c|air\s+conditioning)\s+condenser\b",
        ),
    ),
    (
        "radiator",
        "intercooler",
        "single_part",
        (
            r"(?:^|\n)\s*(?:інтеркулер|интеркулер)\w*\b",
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+(?:інтеркулер|интеркулер)(?:а|у)?\b",
            # "Радіатор наддуву" is the charge-air cooler.  Without this the
            # generic engine-radiator rule claimed it and hard-stopped eight
            # live candidates on query 0384J9 -> 0384N6, which the shadow
            # document itself lists as a successful intercooler cross.
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+наддув\w*\b",
            r"\b(?:впускн\w*\s+)?охолоджувач\w*\s+(?:наддувн\w*\s+)?повітр\w*\b",
            r"\b(?:впускн\w*\s+)?охладител\w*\s+(?:наддувочн\w*\s+)?воздух\w*\b",
            r"\bintercooler\s+(?:radiator|cooler)\b",
            r"\b(?:intake|charge)\s+air\s+cooler\b",
        ),
    ),
    (
        "exhaust_recirculation",
        "egr_cooler",
        "single_part",
        (
            r"\b(?:радіатор|радiатор|радиатор)\w*\s+egr\b",
            r"\begr\s+(?:radiator|cooler)\b",
        ),
    ),
    (
        "radiator",
        "engine_cooling_radiator",
        "single_part",
        (
            r"\bрадіатор\w*\b",
            r"\bрадiатор\w*\b",
            r"\bрадиатор\w*\b",
            r"\bradiator\b",
        ),
    ),
    (
        "wheel_end",
        "wheel_hub_flange",
        "component",
        (
            r"\b(?:фланец|фланець|фланш)\w*[^\n]{0,30}(?:ступиц|маточин|маточк)\w*\b",
            r"\bwheel\s+hub\s+flange\b",
        ),
    ),
    (
        "wheel_end",
        "wheel_hub",
        "complete_assembly",
        (
            # A hub listing often includes the bearing dimensions in
            # parentheses.  That parenthetical specification is a component
            # fact, not evidence that the sellable item is a standalone
            # bearing; keep the hub identity ahead of the generic bearing
            # pattern below.
            r"\b(?:підшипник|подшипник)\w*\s+(?:маточин|ступиц)\w*[^\n]{0,40}\(\s*(?:підшипник|подшипник)\w*\b",
            r"\b(?:маточин|ступиц)\w*[^\n]{0,45}\(\s*(?:підшипник|подшипник)\w*\b",
        ),
    ),
    (
        "wheel_end",
        "wheel_bearing",
        "single_part",
        (
            r"\b(?:підшипник|подшипник)\w*[^\n]{0,30}(?:маточ|ступ)\w*\.?\b",
            r"\b(?:ступич|ступиц|маточин)\w*[^\n]{0,25}(?:підшипник|подшипник)\w*\b",
            r"\b(?:підшипник|подшипник)\w*[^\n]{0,25}(?:колес|коліс)\w*\b",
            r"\b(?:колес|коліс)\w*[^\n]{0,25}(?:підшипник|подшипник)\w*\b",
            r"\bwheel\s+bearing\b",
        ),
    ),
    (
        "wheel_end",
        "wheel_hub",
        "complete_assembly",
        (
            r"\b(?:маточин|ступиц)\w*\b",
            r"\bwheel\s+hub\b",
        ),
    ),
    (
        "driveline_bearing",
        "propshaft_support_bearing",
        "single_part",
        (
            r"\b(?:підшипник|подшипник)\w*\s+(?:підвісн|подвесн)\w*\b",
            r"\bpropshaft\s+(?:support|center)\s+bearing\b",
        ),
    ),
    (
        "bearing",
        "generic_bearing",
        "single_part",
        (
            r"^\s*(?:підшипник|подшипник)\w*\s+[a-zа-яёіїєґ\d][\w./-]*\s*$",
            r"^\s*(?:підшипник|подшипник)\w*(?:\s+конич\w*)?\s+[a-zа-яёіїєґ\d][^\n]{0,55}(?:\d\s*[*xх]\s*\d|\d{3,})[^\n]*$",
            r"^\s*bearing\s+[a-z\d][\w./-]*\s*$",
        ),
    ),
    (
        "timing_chain_drive",
        "timing_chain_tensioner",
        "single_part",
        (
            r"\bнатяж\w*(?:-уcпокоител|успокоител|заспокійник)?\w*[^\n]{0,25}(?:цеп|ланцюг|ланцуг)\w*\b",
            r"\b(?:цеп|ланцюг|ланцуг)\w*[^\n]{0,25}натяж\w*\b",
            r"\btiming\s+chain\s+tensioner\b",
        ),
    ),
    (
        "timing_chain_drive",
        "timing_chain_guide",
        "component",
        (
            r"\b(?:успокоител|уcпокоител|успокійник|заспокійник|заспокоювач)\w*[^\n]{0,25}(?:цеп|ланцюг|ланцуг)\w*\b",
            r"\btiming\s+chain\s+guide\b",
        ),
    ),
    (
        "belt_drive",
        "crankshaft_pulley",
        "single_part",
        (
            r"\b(?:шкив|шків)\w*[^\n]{0,20}(?:коленвал|колінвал|коленчат)\w*\b",
            r"\bcrankshaft\s+pulley\b",
        ),
    ),
    (
        "belt_drive",
        "timing_roller_kit",
        "kit",
        (
            r"\bкомплект\w*[^\n]{0,30}(?:ролик|роликов|натяжн|натягу)\w*[^\n]{0,20}г[.\s]*р[.\s]*м\b",
            r"\btiming\s+(?:belt\s+)?roller\s+kit\b",
        ),
    ),
    (
        "belt_drive",
        "timing_belt_kit",
        "kit",
        (
            r"\bкомплект\w*[^\n]{0,35}(?:рем(?:е|і)?н\w*[^\n]{0,15})?г[.\s]*р[.\s]*м\b",
            r"\btiming\s+belt\s+kit\b",
        ),
    ),
    (
        "belt_drive",
        "timing_roller",
        "single_part",
        (
            r"\bролик\w*[^\n]{0,35}грм",
            r"\btiming\s+belt\s+(?:roller|pulley)\b",
        ),
    ),
    (
        "belt_drive",
        "tensioner_roller",
        "single_part",
        (
            r"\bролик\w*\s+(?:натяжн|натяжен|натягу|натягн|натяжник)\w*\b",
            r"\bbelt\s+tensioner\s+(?:roller|pulley)\b",
        ),
    ),
    (
        "belt_drive",
        "idler_roller",
        "single_part",
        (
            r"\bролик\w*\s+паразитн\w*\b",
            r"\bролик\w*[^\n]{0,30}(?:обводн|обвідн)\w*\b",
            r"\bbelt\s+idler\s+(?:roller|pulley)\b",
        ),
    ),
    (
        "belt_drive",
        "",
        "",
        (
            # A title saying only "roller of a serpentine belt" proves that
            # the offer is a roller, but not whether it is an idler or a
            # tensioner.  It must not be classified as the belt itself.
            r"\bролик\w*[^\n]{0,30}рем(?:е|і)?н\w*\s+пол[іи]кл[іи]н\w*\b",
        ),
    ),
    (
        "belt_drive",
        "serpentine_belt",
        "single_part",
        (
            r"^\s*рем(?:е|і)?н\w*\s+пол[іи]кл[іи]н\w*\b",
            r"^\s*рем(?:е|і)?н\w*\s+генератор\w*\b",
            r"\bserpentine\s+belt\b",
        ),
    ),
    (
        "belt_drive",
        "timing_belt_guide",
        "component",
        (
            r"\b(?:успокоител|уcпокоител|успокійн|успокоювач|заспокоювач)\w*[^\n]{0,20}рем(?:е|і)?н\w*[^\n]{0,15}г[.\s]*р[.\s]*м\b",
            r"\bамортизатор\w*[^\n]{0,20}рем(?:е|і)?н\w*[^\n]{0,15}г[.\s]*р[.\s]*м\b",
        ),
    ),
    (
        "belt_drive",
        "timing_belt",
        "single_part",
        (
            # Customer data contains joined forms such as ``ГРМFord``.  ``ГРМ``
            # is itself a closed automotive abbreviation, so a trailing word
            # boundary would lose valid evidence without adding safety.
            r"\bрем(?:е|і)?н\w*[^\n]{0,20}грм",
            r"\btiming\s+belt\b",
        ),
    ),
    (
        "belt_drive",
        "alternator_pulley",
        "component",
        (
            r"\b(?:шкив|шків|муфт)\w*[^\n]{0,25}генератор\w*\b",
            r"\balternator\s+(?:overrunning\s+)?pulley\b",
        ),
    ),
    (
        "electrical_charging",
        "alternator_regulator",
        "component",
        (
            r"\bрегулятор\w*[^\n]{0,35}(?:напряж|напруг)\w*[^\n]{0,25}генератор\w*\b",
            r"\bрегулятор\w*[^\n]{0,35}генератор\w*\b",
            r"\b(?:напряж|напруг)\w*[^\n]{0,25}регулятор\w*[^\n]{0,25}генератор\w*\b",
            r"\balternator\s+(?:voltage\s+)?regulator\b",
        ),
    ),
    (
        "electrical_charging",
        "alternator_assembly",
        "complete_assembly",
        (
            r"^\s*генератор\w*(?:\s|$)",
            r"^\s*alternator(?:\s|$)",
        ),
    ),
    (
        "brake_friction",
        "parking_brake_shoe",
        "set",
        (
            r"\bколодк\w*[^\n]{0,30}(?:стояночн|стоян|ручн)\w*[^\n]{0,20}(?:торм|гальм)\w*\b",
            r"\bколодк\w*[^\n]{0,20}(?:торм|гальм)\w*[^\n]{0,30}(?:стояночн|стоян|ручн)\w*\b",
            r"\bparking\s+brake\s+shoe\b",
        ),
    ),
    (
        "drum_brake_hardware",
        "drum_brake_repair_kit",
        "kit",
        (
            r"\bрем\s*комплект\w*[^\n]{0,35}(?:задн\w*\s+)?(?:тормозн|гальмівн)\w*[^\n]{0,25}(?:барабан|колод(?:к|ок))\w*\b",
            r"\bремкомплект\w*\s+барабан\w*\b",
            r"\bdrum\s+brake\s+(?:repair\s+)?kit\b",
        ),
    ),
    (
        "drum_brake_hardware",
        "drum_brake_adjuster",
        "component",
        (
            r"\b(?:механізм|механизм)\w*[^\n]{0,25}(?:розвідн|разводн)\w*[^\n]{0,20}(?:колод|тормоз|гальм)\w*\b",
            r"\b(?:розвідн|разводн)\w*[^\n]{0,25}(?:механізм|механизм)\w*\b",
            r"\bdrum\s+brake\s+adjuster\b",
        ),
    ),
    (
        "drum_brake_hardware",
        "",
        "",
        (
            r"\bрем\s*комплект\w*[^\n]{0,35}(?:задн\w*\s+)?(?:тормозн|гальмівн)\w*[^\n]{0,25}(?:барабан|колод(?:к|ок))\w*\b",
            r"\bремкомплект\w*[^\n]{0,35}(?:задн\w*\s+)?(?:тормозн|гальмівн)\w*[^\n]{0,25}(?:барабан|колод(?:к|ок))\w*\b",
            r"\bремкомплект\w*\s+барабан\w*\b",
            r"\bмеханізм\w*\s+розвідн\w*[^\n]{0,20}колод(?:к|ок)\w*\b",
            r"\bdrum\s+brake\s+(?:hardware|adjuster)(?:\s+kit)?\b",
        ),
    ),
    (
        "brake_friction",
        "brake_pad",
        "set",
        (
            r"\bколодк\w*[^\n]{0,30}(?:торм|гальм)\w*\b",
            r"\bbrake\s+pad\w*\b",
        ),
    ),
    (
        "brake_disc",
        "brake_disc",
        "single_part",
        (
            r"\bдиск\w*\s+(?:тормоз|гальм)\w*\b",
            r"\b(?:тормозн|гальмівн|гальмн)\w*\s+диск\w*\b",
            r"\bbrake\s+(?:disc|rotor)\b",
        ),
    ),
    (
        "brake_hydraulics",
        "brake_line",
        "single_part",
        (
            r"\b(?:трубк|трубопровод)\w*\s+(?:тормоз|гальм)\w*\b",
            r"\b(?:тормозн|гальмівн)\w*\s+(?:трубк|трубопровод)\w*\b",
            r"\bbrake\s+(?:line|pipe|tube)\b",
        ),
    ),
    (
        "brake_hydraulics",
        "brake_hose",
        "single_part",
        (
            r"\bшланг\w*\s+(?:тормоз|гальм)\w*\b",
            r"\b(?:тормозн|гальмівн)\w*\s+шланг\w*\b",
            r"\bbrake\s+hose\b",
        ),
    ),
    (
        "brake_hydraulics",
        "master_brake_cylinder",
        "complete_assembly",
        (
            r"\b(?:цилиндр|циліндр)\w*\s+(?:тормоз|гальм)\w*\s+(?:главн|головн)\w*\b",
            r"\b(?:главн|головн)\w*\s+(?:тормозн|гальмівн)\w*\s+(?:цилиндр|циліндр)\w*\b",
            r"\bmaster\s+brake\s+cylinder\b",
        ),
    ),
    (
        "brake_hydraulics",
        "wheel_brake_cylinder",
        "complete_assembly",
        (
            r"\b(?:цилиндр|циліндр)\w*\s+(?:тормоз|гальм)\w*(?:\s+(?:задн|передн)\w*)?\b",
            r"\bwheel\s+brake\s+cylinder\b",
        ),
    ),
    (
        "parking_brake",
        "parking_brake_cable",
        "single_part",
        (
            r"\bтрос\w*[^\n]{0,25}(?:ручн|стояночн)\w*[^\n]{0,20}(?:гальм|тормоз)\w*\b",
            r"\bparking\s+brake\s+cable\b",
        ),
    ),
    (
        "gasket",
        "oil_filter_housing_gasket",
        "single_part",
        (
            r"\bпрокладк\w*[^\n]{0,30}корпус\w*[^\n]{0,25}(?:маслян|оливн)\w*\s+ф[іи]льтр\w*\b",
            r"\boil\s+filter\s+housing\s+gasket\b",
        ),
    ),
    (
        "filter",
        "oil_filter_housing",
        "housing",
        (
            r"\bкорпус\w*[^\n]{0,30}(?:масл|олив)\w*\s+ф[іи]льтр\w*\b",
            r"\bкорпус\w*[^\n]{0,30}(?:масл|олив)\w*\s+фильтр\w*\b",
            r"\boil\s+filter\s+housing\b",
        ),
    ),
    (
        "filter",
        "engine_air_filter_housing",
        "component",
        (
            r"\bкорпус\w*\s+(?:повітр|воздуш)\w*\s+фільтр\w*\b",
            r"\bкорпус\w*\s+воздуш\w*\s+фильтр\w*\b",
            r"\bкорпус\w*\s+фільтр\w*[^\n]{0,20}(?:повітр|воздуш)\w*\b",
            r"\b(?:engine\s+)?air\s+filter\s+housing\b",
        ),
    ),
    (
        "filter",
        "cabin_filter",
        "single_part",
        (
            r"\bфільтр\w*[^\n]{0,35}(?:салон|кабін)\w*\b",
            r"\bфильтр\w*[^\n]{0,35}салон\w*\b",
            r"\bcabin\s+(?:air\s+)?filter\b",
        ),
    ),
    (
        "filter",
        "engine_air_filter",
        "single_part",
        (
            r"\bфільтр\w*\s+повітр\w*\b",
            r"\bфильтр\w*\s+воздуш\w*\b",
            r"\bфільтр\w*\s+повітр(?:я|ю)\b",
            r"\bфильтр\w*\s+воздух(?:а|у)\b",
            r"\bповітрян\w*\s+фільтр\w*\b",
            r"\bвоздушн\w*\s+фильтр\w*\b",
            r"\bengine\s+air\s+filter\b",
        ),
    ),
    (
        "filter",
        "oil_filter",
        "single_part",
        (
            r"\bфільтр\w*\s+(?:масл|олив)\w*\b",
            r"\bфильтр\w*\s+масл\w*\b",
            r"\b(?:маслян|оливн)\w*\s+фільтр\w*\b",
            r"\boil\s+filter\b",
        ),
    ),
    (
        "filter",
        "fuel_filter",
        "single_part",
        (
            r"\bфільтр\w*\s+палив\w*\b",
            r"\bфильтр\w*\s+топлив\w*\b",
            r"\bпаливн\w*\s+фільтр\w*\b",
            r"\bтопливн\w*\s+фильтр\w*\b",
            r"\bfuel\s+filter\b",
        ),
    ),
    (
        "gasket",
        "engine_gasket_kit",
        "kit",
        (
            r"\bкомплект\w*[^\n]{0,45}проклад\w*\b",
            r"\bпроклад\w*[^\n]{0,45}комплект\w*\b",
            r"\bengine\s+gasket\s+(?:kit|set)\b",
        ),
    ),
    (
        "transmission_control",
        "shifter_bushing",
        "single_part",
        (
            r"\bвтулк\w*[^\n]{0,25}(?:кул[иі]с|механизм\w*\s+переключен)\w*\b",
            r"\bshifter\s+bushing\b",
        ),
    ),
    (
        "clutch_control",
        "clutch_cable",
        "single_part",
        (
            r"\bтрос\w*\s+(?:[сc]цеплен|зчеплен)\w*\b",
            r"\bclutch\s+cable\b",
        ),
    ),
    (
        "ignition_system",
        "distributor_rotor",
        "single_part",
        (
            r"\b(?:бегунок|бігунок)\w*[^\n]{0,25}трамблер\w*\b",
            r"\bdistributor\s+rotor\b",
        ),
    ),
    (
        "exhaust_mount",
        "exhaust_hanger",
        "single_part",
        (
            r"\b(?:резинк|гумк|кронштейн)\w*[^\n]{0,30}(?:глушител|глушник)\w*\b",
            r"\bexhaust\s+(?:rubber\s+)?hanger\b",
        ),
    ),
    (
        "gasket",
        "cylinder_head_gasket",
        "single_part",
        (
            r"\bпроклад\w*[^\n]{0,35}(?:гбц|голов\w*\s+блок\w*)\b",
            r"\bcylinder\s+head\s+gasket\b",
        ),
    ),
    (
        "gasket",
        "oil_pan_gasket",
        "single_part",
        (r"\bпроклад\w*[^\n]{0,30}поддон\w*\b", r"\boil\s+pan\s+gasket\b"),
    ),
    (
        "gasket",
        "intake_manifold_gasket",
        "single_part",
        (
            r"\bпроклад\w*[^\n]{0,40}(?:впускн|впуск)\w*\s+кол(?:л)?ектор\w*\b",
            r"\bintake\s+manifold\s+gasket\b",
        ),
    ),
    (
        "gasket",
        "exhaust_manifold_gasket",
        "single_part",
        (
            r"\bпроклад\w*[^\n]{0,40}выпуск\w*\s+коллектор\w*\b",
            r"\bпроклад\w*[^\n]{0,40}випуск\w*\s+колектор\w*\b",
            r"\bпроклад\w*[^\n]{0,25}кол(?:л)?ектор\w*\s+випуск\w*\b",
            r"\bexhaust\s+manifold\s+gasket\b",
        ),
    ),
    (
        "gasket",
        "valve_cover_gasket",
        "single_part",
        (
            r"\bпроклад\w*[^\n]{0,35}клапан\w*\s+крыш\w*\b",
            r"\bпроклад\w*[^\n]{0,35}клапан\w*\s+криш\w*\b",
            r"\bvalve\s+cover\s+gasket\b",
        ),
    ),
    (
        "oil_seal",
        "valve_stem_seal",
        "single_part",
        (
            r"\bсальник\w*\s+клапан\w*\b",
            r"\bvalve\s+stem\s+seal\b",
        ),
    ),
    (
        "oil_seal",
        "transmission_oil_seal",
        "single_part",
        (
            r"\bсальник\w*[^\n]{0,30}(?:кпп|коробк\w*\s+передач)\b",
            r"\b(?:кпп|коробк\w*\s+передач)[^\n]{0,30}сальник\w*\b",
            r"\btransmission\s+oil\s+seal\b",
        ),
    ),
    (
        "oil_seal",
        "axle_oil_seal",
        "single_part",
        (
            r"\bсальник\w*[^\n]{0,30}(?:півос|полуос)\w*\b",
            r"\baxle\s+oil\s+seal\b",
        ),
    ),
    (
        "driveline",
        "halfshaft_repair_kit",
        "kit",
        (
            r"\b(?:полуос|півос|напівос)\w*[^\n]{0,35}(?:ремкомплект|р\s*/\s*к)\b",
            r"\b(?:ремкомплект|р\s*/\s*к)\w*[^\n]{0,35}(?:полуос|півос|напівос)\w*\b",
            r"\bhalfshaft\s+repair\s+kit\b",
            r"\bdrive\s*shaft\s+repair\s+kit\b",
        ),
    ),
    (
        "driveline",
        "halfshaft_flange",
        "component",
        (
            r"\b(?:флянец|фланец|фланець)\w*[^\n]{0,25}(?:полуос|півос|напівос)\w*\b",
            r"\bhalfshaft\s+flange\b",
        ),
    ),
    (
        "driveline",
        "halfshaft",
        "complete_assembly",
        (
            r"\b(?:полуос|півос|напівос)\w*\b",
            r"\b(?:привід|привод)\w*\s+(?:перед\w*\.?\s+)?мост\w*[^\n]{0,30}(?:в\s+зборі|в\s+сборе|в\s+зб\.)",
            r"\bhalfshaft\b",
            r"\bdrive\s*shaft\b",
        ),
    ),
    (
        "transmission",
        "gearbox_shift_fork",
        "component",
        (
            r"\bвилк\w*[^\n]{0,30}(?:кпп|коробк\w*\s+передач)\b",
            r"\bgearbox\s+shift\s+fork\b",
        ),
    ),
    (
        "transmission_controls",
        "shift_linkage_rod",
        "single_part",
        (
            r"\b(?:тяг|тяжк)\w*[^\n]{0,25}выбор\w*[^\n]{0,20}передач\w*\b",
            r"\bтяг\w*[^\n]{0,25}вибор\w*[^\n]{0,20}передач\w*\b",
            r"\bgear\s+shift\s+linkage\s+rod\b",
        ),
    ),
    (
        "brake_caliper",
        "caliper_piston",
        "component",
        (
            r"\bпорш(?:ен|ень)\w*[^\n]{0,30}суп(?:порт|орт)\w*\b",
            r"\bcaliper\s+piston\b",
        ),
    ),
    (
        "brake_caliper",
        "caliper_repair_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,30}суп(?:порт|орт)\w*\b",
            r"\bсуп(?:порт|орт)\w*[^\n]{0,30}ремкомплект\w*\b",
            r"\bcaliper\s+repair\s+kit\b",
        ),
    ),
    (
        "brake_caliper",
        "caliper_guide",
        "component",
        (
            r"\b(?:направл|напрямн|спрямовуюч)\w*[^\n]{0,30}суп(?:порт|орт)\w*\b",
            r"\bcaliper\s+guide\b",
        ),
    ),
    (
        "brake_caliper",
        "caliper_assembly",
        "complete_assembly",
        (r"\bсуппорт\w*\b", r"\bсупорт\w*\b", r"\bbrake\s+caliper\b"),
    ),
    (
        "engine_internal",
        "engine_piston",
        "single_part",
        (
            r"\b(?:поршень|поршня)\w*\b",
            r"\bengine\s+piston\b",
        ),
    ),
    (
        "thermostat",
        "thermostat_with_housing",
        "complete_assembly",
        (
            r"\bкорпус\w*\s+термостат\w*[^\n]{0,25}(?:[cсз]\s+термостат\w*|в\s+сборе|[ву]\s+зборі)\b",
            r"\bтермостат\w*[^\n]{0,25}(?:с|з|із|из)\s+корпус\w*\b",
            r"\bthermostat\s+housing\s+assembly\b",
        ),
    ),
    (
        "thermostat",
        "thermostat_housing",
        "housing",
        (
            r"\bкорпус\w*\s+термостат\w*\b",
            r"\bthermostat\s+housing\b",
        ),
    ),
    (
        "thermostat",
        "coolant_thermostat",
        "single_part",
        (r"\bтермостат\w*\b", r"\bthermostat\b"),
    ),
    (
        "shock_absorber",
        "strut_insert",
        "single_part",
        (
            r"\b(?:вкладыш|вкладиш)\w*[^\n]{0,25}амм?орт\w*\b",
            r"\bstrut\s+(?:cartridge|insert)\b",
        ),
    ),
    (
        "shock_absorber",
        "shock_absorber_rod",
        "component",
        (
            r"\bшток\w*\s+амортизатор\w*\b",
            r"\b(?:shock|strut)\s+(?:piston\s+)?rod\b",
        ),
    ),
    (
        "suspension",
        "bump_stop",
        "single_part",
        (
            r"\b(?:отбойник|відбійник|втбійник)\w*[^\n]{0,25}амм?орт\w*\b",
            r"\b(?:strut|shock)\s+bump\s+stop\b",
        ),
    ),
    (
        "suspension",
        "strut_boot",
        "single_part",
        (
            r"\b(?:пыльник|пильник)\w*[^\n]{0,25}(?:амм?орт|ст[оі]йк)\w*\b",
            r"\b(?:strut|shock)\s+(?:boot|gaiter)\b",
        ),
    ),
    (
        "shock_absorber",
        "shock_absorber",
        "single_part",
        (r"\bамортизатор\w*\b", r"\bshock\s+absorber\b"),
    ),
    (
        "sensor",
        "brake_wear_sensor",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,45}износ\w*[^\n]{0,30}колод\w*\b",
            r"\bдатчик\w*[^\n]{0,45}знос\w*[^\n]{0,30}колод\w*\b",
            r"\bbrake\s+pad\s+wear\s+sensor\b",
        ),
    ),
    (
        "sensor",
        "boost_pressure_sensor",
        "single_part",
        (
            r"\bдатчик\w*[^\n]{0,35}тиск\w*[^\n]{0,25}наддув\w*\b",
            r"\bдатчик\w*[^\n]{0,35}давлен\w*[^\n]{0,25}наддув\w*\b",
            r"\bboost\s+pressure\s+sensor\b",
        ),
    ),
    (
        "ignition_system",
        "distributor_cap",
        "component",
        (
            r"\b(?:крышк|кришк)\w*\s+трамблер\w*\b",
            r"\bdistributor\s+cap\b",
        ),
    ),
    (
        "ignition_system",
        "distributor_assembly",
        "complete_assembly",
        (r"^\s*трамблер\w*\b", r"^\s*distributor(?:\s|$)"),
    ),
    (
        "ignition_system",
        "ignition_module",
        "single_part",
        (
            r"\b(?:коммутатор|комутатор)\w*\b",
            r"\bignition\s+(?:control\s+)?module\b",
        ),
    ),
    (
        "ignition_system",
        "glow_plug",
        "single_part",
        (
            r"\b(?:свеч|свіч)\w*\s+(?:накал|розжар)\w*\b",
            r"\bglow\s+plug\b",
        ),
    ),
    (
        "ignition_system",
        "spark_plug",
        "single_part",
        (
            r"^\s*(?:свеч|свіч)\w*(?:\s|$)",
            r"\bspark\s+plug\b",
        ),
    ),
    (
        "engine_internal",
        "camshaft",
        "single_part",
        (r"^\s*(?:распредвал|розподілвал|розпредвал)\w*\b", r"\bcamshaft\b"),
    ),
    (
        "engine_internal",
        "engine_valve",
        "single_part",
        (
            r"^\s*клапан(?:а|и|ы)?\s+\((?:вп|вып|вип)",
            r"^\s*клапан\w*\s+(?:впускн|выпускн|випускн)\w*\b",
            r"\bengine\s+valve\b",
        ),
    ),
    (
        "engine_internal",
        "hydraulic_lifter",
        "single_part",
        (
            r"\b(?:гидрокомпенсатор|гідрокомпенсатор)\w*\b",
            r"\bhydraulic\s+(?:valve\s+)?lifter\b",
        ),
    ),
    (
        "engine_lubrication",
        "oil_pan",
        "complete_assembly",
        (r"^\s*(?:поддон|піддон)\w*\b", r"\boil\s+pan\b"),
    ),
    (
        "engine_lubrication",
        "oil_pump",
        "complete_assembly",
        (r"\b(?:маслонасос|(?:оливн|маслян)\w*\s+насос)\w*\b", r"\boil\s+pump\b"),
    ),
    (
        "oil_seal",
        "crankshaft_oil_seal",
        "single_part",
        (
            r"\bсальник\w*[^\n]{0,30}(?:коленвал|колінвал)\w*\b",
            r"\bcrankshaft\s+oil\s+seal\b",
        ),
    ),
    (
        "washer_system",
        "washer_pump",
        "single_part",
        (
            r"\bнасос\w*[^\n]{0,30}(?:омыв|омив|склоомив|скловимив|стеклоомыв)\w*\b",
            r"\bwasher\s+pump\b",
        ),
    ),
    (
        "suspension",
        "",
        "",
        (r"^\s*(?:сайлентблок|сал[іи]нблок)\w*\b",),
    ),
    (
        "brake_friction",
        "brake_pad",
        "set",
        (r"^\s*колодк\w*(?:\s|$)",),
    ),
    (
        "vehicle_lighting",
        "fog_lamp",
        "single_part",
        (
            r"\b(?:противотуманк|протитуманк)\w*\b",
            r"\b(?:фара|стекло)\w*[^\n]{0,20}противотуман\w*\b",
            r"\bfog\s+lamp\b",
        ),
    ),
    (
        "vehicle_lighting",
        "headlamp_housing",
        "housing",
        (
            r"\bкорпус\w*[^\n]{0,25}(?:фар|фара)\w*\b",
            r"\bheadlamp\s+housing\b",
        ),
    ),
    (
        "vehicle_lighting",
        "headlamp_lens",
        "component",
        (r"\bстекл\w*\s+фар\w*\b", r"\bheadlamp\s+lens\b"),
    ),
    (
        "vehicle_lighting",
        "headlamp",
        "complete_assembly",
        (
            r"^\s*фар\w*(?:\s|$)",
            r"^\s*(?:б\s*[./\\-]\s*у\s+)?фар(?:а|и|у|ою|е|ы)\b",
            r"\bheadlamp\b",
        ),
    ),
    (
        "vehicle_lighting",
        "turn_signal_lamp",
        "single_part",
        (
            r"\b(?:указател\w*\s+поворот|поворотник)\w*\b",
            r"\bturn\s+signal\s+lamp\b",
        ),
    ),
    (
        "vehicle_lighting",
        "rear_or_marker_lamp",
        "complete_assembly",
        (
            r"^\s*(?:фонар|ліхтар)\w*(?:\s|$)",
            r"\b(?:rear|marker)\s+lamp\b",
        ),
    ),
    (
        "body_trim",
        "moulding",
        "single_part",
        (r"^\s*(?:молдинг|молдінг)\w*\b", r"\bbody\s+moulding\b"),
    ),
    (
        "body_trim",
        "emblem",
        "single_part",
        (
            r"^\s*(?:значок|емблема|эмблема)\w*\b",
            r"\bvehicle\s+emblem\b",
        ),
    ),
    (
        "sensor",
        "",
        "",
        (r"^\s*датчик\w*(?:\s|$)", r"^\s*sensor(?:\s|$)"),
    ),
    (
        "gasket",
        "",
        "",
        (r"^\s*прокладк\w*(?:\s|$)", r"^\s*gasket(?:\s|$)"),
    ),
    (
        "door_lock",
        "hood_latch",
        "complete_assembly",
        (r"\bзамок\w*[^\n]{0,20}капот\w*\b", r"\bhood\s+latch\b"),
    ),
    (
        "interior_hardware",
        "glovebox_lock",
        "complete_assembly",
        (
            r"\bзамок\w*[^\n]{0,20}(?:бардач|речов\w*\s+ящик)\w*\b",
            r"\bglovebox\s+lock\b",
        ),
    ),
    (
        "door_lock",
        "lock_eccentric",
        "component",
        (
            r"\b(?:ексцентрик|эксцентрик)\w*[^\n]{0,25}замк\w*[^\n]{0,20}двер\w*\b",
            r"\bdoor\s+lock\s+eccentric\b",
        ),
    ),
    (
        "door_lock",
        "door_lock",
        "complete_assembly",
        (
            r"\bзамок\w*[^\n]{0,35}двер\w*\b",
            r"\bdoor\s+lock\b",
        ),
    ),
    (
        "door_hardware",
        "door_handle",
        "single_part",
        (
            r"^\s*ручк\w*[^\n]{0,100}\b(?:передн|задн|лев|прав|лів)\w*\b",
            r"^\s*ручк\w*[^\n]{0,100}(?:\bl\b|\br\b)",
        ),
    ),
    (
        "lock_cylinder",
        "door_lock_cylinder",
        "component",
        (
            r"\b(?:личинк|лічинк|серцевин)\w*[^\n]{0,35}(?:двер|дверн\w*\s+замк)\w*\b",
            r"\bdoor\s+lock\s+cylinder\b",
        ),
    ),
    (
        "throttle_control",
        "throttle_cable",
        "single_part",
        (r"\bтрос{1,2}\w*\s+газ\w*\b", r"\bthrottle\s+cable\b"),
    ),
    (
        "hood_release",
        "hood_release_cable",
        "single_part",
        (r"\bтрос{1,2}\w*\s+капот\w*\b", r"\bhood\s+release\s+cable\b"),
    ),
    (
        "instrumentation",
        "speedometer_cable",
        "single_part",
        (r"\bтрос{1,2}\w*\s+спидометр\w*\b", r"\bspeedometer\s+cable\b"),
    ),
    (
        "parking_brake",
        "parking_brake_cable",
        "single_part",
        (r"\bтрос{1,2}\w*\s+ручник\w*\b", r"\bhandbrake\s+cable\b"),
    ),
    (
        "electrical_switch",
        "hazard_switch",
        "single_part",
        (
            r"\bкнопк\w*[^\n]{0,25}(?:аварийн|аварійн|аварийк|аварійк)\w*\b",
            r"\bhazard\s+(?:light\s+)?switch\b",
        ),
    ),
    (
        "electrical_switch",
        "light_switch",
        "single_part",
        (
            r"\b(?:кнопк|включател|вимикач|перемикач|переключател)\w*[^\n]{0,30}(?:включен\w*\s+)?(?:світл|свет|фар)\w*\b",
            r"\bheadlight\s+switch\b",
        ),
    ),
    (
        "mirror_controls",
        "mirror_adjustment_switch",
        "single_part",
        (
            r"\b(?:перемикач|переключател|джойстик)\w*[^\n]{0,35}(?:зеркал|дзеркал)\w*\b",
            r"\bmirror\s+adjustment\s+switch\b",
        ),
    ),
    (
        "steering_column_switch",
        "wiper_switch",
        "single_part",
        (
            r"\b(?:перемикач|переключател)\w*[^\n]{0,25}ст\s*/\s*(?:очист|очис)\w*\b",
            r"\bwiper\s+switch\b",
        ),
    ),
    (
        "belt_drive",
        "alternator_roller",
        "single_part",
        (r"\bролик\w*[^\n]{0,20}генератор\w*\b", r"\balternator\s+roller\b"),
    ),
    (
        "belt_drive",
        "tensioner_assembly",
        "complete_assembly",
        (
            r"\bмехан[іи]зм\w*[^\n]{0,30}натяж\w*[^\n]{0,30}(?:генератор|рем(?:е|і)?н)\w*\b",
            r"\bbelt\s+tensioner\s+assembly\b",
        ),
    ),
    (
        "belt_drive",
        "v_belt",
        "single_part",
        (
            r"^\s*рем(?:е|і)?н\w*\s+(?:клиновидн|кондиц|гідропідсил|гидроусил)\w*\b",
            r"\bv[- ]belt\b",
        ),
    ),
    (
        # Gearbox wording, so it names the gearbox subtype.  Reached only when
        # the rule above it has not already claimed the same phrase.
        "engine_mount",
        "transmission_mount",
        "single_part",
        (r"\bподушк\w*[^\n]{0,25}(?:акпп|мкпп)\b",),
    ),
    (
        "intake_mount",
        "carburetor_mount",
        "single_part",
        (
            r"\bподушк\w*[^\n]{0,25}(?:карбюр|моноинжектор)\w*\b",
            r"\bcarburetor\s+mount\b",
        ),
    ),
    (
        "suspension",
        "axle_beam_mount",
        "single_part",
        (r"\bподушк\w*[^\n]{0,25}(?:балк|ресор)\w*\b",),
    ),
    (
        "body_mounting",
        "bumper_bracket",
        "component",
        (
            r"\b(?:кронштейн|направляющ|напрямн)\w*[^\n]{0,35}бампер\w*\b",
            r"\bbumper\s+(?:bracket|guide)\b",
        ),
    ),
    (
        "body_hinge",
        "hood_hinge",
        "single_part",
        (r"\bпетл\w*\s+капот\w*\b", r"\bhood\s+hinge\b"),
    ),
    (
        "body_hinge",
        "door_hinge",
        "single_part",
        (r"\bпетл\w*[^\n]{0,25}двер\w*\b", r"\bdoor\s+hinge\b"),
    ),
    (
        "charge_air_hose",
        "intercooler_hose",
        "single_part",
        (
            r"\bпатрубок\w*[^\n]{0,25}(?:интеркул|інтеркул)\w*\b",
            r"\bintercooler\s+hose\b",
        ),
    ),
    (
        "engine_timing",
        "crankshaft_gear",
        "component",
        (r"\bшестерн\w*[^\n]{0,25}(?:коленвал|колінвал)\w*\b",),
    ),
    (
        "transmission",
        "fifth_gear",
        "component",
        (r"\bшестерн\w*[^\n]{0,20}(?:5|пят|п['’]?ят)\w*[^\n]{0,15}передач\w*\b",),
    ),
    (
        "suspension",
        "steering_knuckle",
        "single_part",
        (r"\bкулак\w*\s+поворотн\w*\b", r"\bsteering\s+knuckle\b"),
    ),
    (
        "suspension",
        "leaf_spring",
        "single_part",
        (r"\bлист\w*\s+ресор\w*\b", r"\bleaf\s+spring\b"),
    ),
    (
        "brake_drum",
        "brake_drum",
        "single_part",
        (r"\bбарабан\w*\s+(?:тормоз|гальм)\w*\b", r"\bbrake\s+drum\b"),
    ),
    (
        "electrical_switch",
        "door_jamb_switch",
        "single_part",
        (
            r"\b(?:концевик|кінцевик)\w*[^\n]{0,20}двер\w*\b",
            r"\b(?:вимикач|выключател|кнопк)\w*[^\n]{0,20}(?:концевик|кінцевик)\w*[^\n]{0,20}двер\w*\b",
            r"\bdoor\s+jamb\s+switch\b",
        ),
    ),
    (
        "electrical_switch",
        "brake_light_switch",
        "single_part",
        (
            r"\bкнопк\w*[^\n]{0,20}педал\w*[^\n]{0,15}(?:тормоз|гальм)\w*\b",
            r"\bbrake\s+pedal\s+switch\b",
        ),
    ),
    (
        "body_protection",
        "mud_flap",
        "single_part",
        (r"\bбрызговик\w*\b", r"\bmud\s*flap\b"),
    ),
    (
        "ignition_system",
        "distributor_rotor",
        "single_part",
        (r"^\s*(?:бегун|бігун)\w*[^\n]{0,25}трамблер\w*\b",),
    ),
    (
        "ignition_system",
        "distributor_vacuum_advance",
        "component",
        (
            r"\bвакуум\w*[^\n]{0,20}трамблер\w*\b",
            r"\bdistributor\s+vacuum\s+advance\b",
        ),
    ),
    (
        "flywheel",
        "flywheel_ring_gear",
        "component",
        (r"\bвенец\w*[^\n]{0,20}маховик\w*\b", r"\bflywheel\s+ring\s+gear\b"),
    ),
    (
        "flywheel",
        "flywheel",
        "single_part",
        (r"^\s*маховик\w*(?:\s|$)", r"^\s*flywheel(?:\s|$)"),
    ),
    (
        "clutch_control",
        "clutch_fork",
        "component",
        (
            r"\bвилк\w*[^\n]{0,20}(?:выжим|витиск|сцепл|зчепл)\w*\b",
            r"\bclutch\s+fork\b",
        ),
    ),
    (
        "electrical_charging",
        "alternator_rectifier",
        "component",
        (
            r"\b(?:диодн|діодн)\w*\s+м[оі]ст\w*[^\n]{0,20}генератор\w*\b",
            r"\balternator\s+rectifier\b",
        ),
    ),
    (
        "electrical_charging",
        "alternator_regulator",
        "component",
        (
            r"\bрел+е\w*[^\n]{0,20}генератор\w*\b",
            r"\balternator\s+(?:voltage\s+)?regulator\b",
        ),
    ),
    (
        "engine_timing",
        "timing_cover",
        "component",
        (r"\bзащит\w*[^\n]{0,20}грм\b", r"\btiming\s+(?:belt\s+)?cover\b"),
    ),
    (
        "engine_timing",
        "crankshaft_sprocket",
        "component",
        (
            r"\b(?:звездочк|звезд|шестерн)\w*[^\n]{0,25}(?:коленчат|коленвал|колінвал)\w*\b",
        ),
    ),
    (
        "engine_timing",
        "camshaft_sprocket",
        "component",
        (
            r"\b(?:звездочк|шестерн)\w*[^\n]{0,25}(?:распредвал|розподілвал|розпредвал)\w*\b",
        ),
    ),
    (
        "fuel_system",
        "carburetor",
        "complete_assembly",
        (r"^\s*карбюратор\w*(?:\s|$)", r"^\s*carburetor(?:\s|$)"),
    ),
    (
        "fuel_system",
        "carburetor_repair_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,35}карбюратор\w*\b",
            r"\bcarburetor\s+repair\s+kit\b",
        ),
    ),
    (
        "vehicle_lighting",
        "bulb",
        "single_part",
        (
            r"^\s*ламп\w*[^\n]{0,30}(?:h[147]|\d{1,2}\s*v|\d{1,3}\s*w)\b",
            r"\bheadlamp\s+bulb\b",
        ),
    ),
    (
        "washer_system",
        "washer_reservoir_cap",
        "component",
        (r"\b(?:крышк|кришк)\w*[^\n]{0,25}бачк\w*[^\n]{0,20}(?:омыв|омив)\w*\b",),
    ),
    (
        "ignition_system",
        "distributor_cap",
        "component",
        (r"\b(?:крышк|кришк)\w*[^\n]{0,30}распределител\w*[^\n]{0,20}зажиган\w*\b",),
    ),
    (
        "door_hardware",
        "sliding_door_handle",
        "single_part",
        (r"\bручк\w*[^\n]{0,25}(?:сдвижн|зсувн|сувальн|ковзн)\w*[^\n]{0,15}двер\w*\b",),
    ),
    (
        "door_hardware",
        "sliding_door_roller",
        "single_part",
        (
            r"\bролик\w*[^\n]{0,30}двер\w*[^\n]{0,25}(?:ковзаюч|ковзн|сдвижн|зсувн|сувальн|боков)\w*\b",
        ),
    ),
    (
        "door_hardware",
        "sliding_door_bracket",
        "component",
        (
            r"^\s*кронштейн\w*[^\n]{0,30}(?:ковзн|сдвижн|зсувн|сувальн)\w*[^\n]{0,20}двер\w*\b",
        ),
    ),
    (
        "engine_mount",
        "transmission_mount",
        "single_part",
        (
            r"\bподушк\w*[^\n]{0,35}(?:коробки|кпп|мкп|акп)\b",
            r"\btransmission\s+mount\b",
        ),
    ),
    (
        "driveline",
        "propshaft_flexible_coupling",
        "single_part",
        (
            r"\bмуфт\w*\s+(?:эласт|еласт)\w*[^\n]{0,25}кардан\w*\b",
            r"\bpropshaft\s+flexible\s+coupling\b",
        ),
    ),
    (
        "window_controls",
        "window_switch",
        "single_part",
        (r"\bкнопк\w*[^\n]{0,30}стеклопідйомник\w*\b",),
    ),
    (
        "steering_column_switch",
        "wiper_switch",
        "single_part",
        (r"\bперемикач\w*[^\n]{0,20}ск\s*/\s*(?:очист|очис)\w*\b",),
    ),
    (
        "electrical_switch",
        "light_switch",
        "single_part",
        (r"\b(?:вмикач|вмикач)\w*[^\n]{0,20}світл\w*\b",),
    ),
    (
        "engine_bearing",
        "main_bearing",
        "set",
        (r"\b(?:вкладиш|вкладыш)\w*\s+кор(?:ен|інь)\w*\b",),
    ),
    (
        "belt_drive",
        "timing_belt",
        "single_part",
        (r"\bрем(?:е|і)?н\w*\s+зубчат\w*(?:[^\n]{0,25}газораспр\w*)?\b",),
    ),
    (
        "engine_lubrication",
        "oil_drain_plug",
        "component",
        (
            r"\bпробк\w*[^\n]{0,20}(?:злив|слив)\w*[^\n]{0,20}(?:масл|олив)\w*\b",
            r"\boil\s+drain\s+plug\b",
        ),
    ),
    (
        "transmission",
        "gearbox_bearing",
        "single_part",
        (r"\b(?:подшипник|підшипник)\w*[^\n]{0,20}(?:кпп|мкп|коробк\w*\s+передач)\b",),
    ),
    (
        "seat_hardware",
        "seat_back_adjuster_handle",
        "component",
        (
            r"\bручк\w*[^\n]{0,25}регулятор\w*[^\n]{0,25}спинк\w*[^\n]{0,15}(?:сиден|сидін)\w*\b",
        ),
    ),
    (
        "hood_release",
        "hood_release_handle",
        "component",
        (
            r"\bручк\w*[^\n]{0,30}(?:открыван|відкриван)\w*[^\n]{0,25}(?:капот|моторн\w*\s+отсек|моторн\w*\s+отвор)\w*\b",
        ),
    ),
    (
        "hood_release",
        "hood_handle_bracket",
        "component",
        (r"\bкронштейн\w*[^\n]{0,25}ручк\w*[^\n]{0,20}капот\w*\b",),
    ),
    (
        "interior_hardware",
        "glovebox_handle",
        "component",
        (r"\bручк\w*[^\n]{0,20}(?:бардач|речов\w*\s+ящик)\w*\b",),
    ),
    (
        "steering_hydraulics",
        "power_steering_hose",
        "single_part",
        (
            r"\bшланг\w*[^\n]{0,30}(?:гидроусил|гідропідсил|гур)\w*[^\n]{0,15}(?:рул|керм)?\w*\b",
        ),
    ),
    (
        "exhaust",
        "exhaust_manifold",
        "complete_assembly",
        (r"\bкол+ектор\w*\s+(?:выпускн|випускн)\w*\b", r"\bexhaust\s+manifold\b"),
    ),
    (
        "engine_internal",
        "valve_guide",
        "component",
        (
            r"\b(?:направл|напрямн|спрямовуюч)\w*[^\n]{0,25}клапан\w*\b",
            r"\bvalve\s+guide\b",
        ),
    ),
    (
        "fuel_system",
        "fuel_pressure_regulator",
        "single_part",
        (r"\bрегулятор\w*[^\n]{0,25}давлен\w*[^\n]{0,20}топлив\w*\b",),
    ),
    (
        "fuel_system",
        "fuel_tank_vent_valve",
        "single_part",
        (
            r"\bклапан\w*[^\n]{0,25}вентиляц\w*[^\n]{0,25}(?:топливн|паливн)\w*[^\n]{0,15}бак\w*\b",
        ),
    ),
    (
        "engine_internal",
        "intermediate_shaft",
        "single_part",
        (r"\bпромежуточн\w*\s+вал\w*[^\n]{0,20}(?:двигат|двигун)\w*\b",),
    ),
    (
        "vehicle_lighting",
        "fog_lamp_frame",
        "component",
        (
            r"\bрамк\w*[^\n]{0,25}(?:креплен|кріплен)\w*[^\n]{0,25}(?:противотуманн|протитуманн)\w*[^\n]{0,15}фар\w*\b",
        ),
    ),
    (
        "body_structure",
        "bumper_reinforcement",
        "component",
        (r"\b(?:шин|усилител|підсилювач)\w*[^\n]{0,25}бампер\w*\b",),
    ),
    (
        "body_trim",
        "wheel_arch_trim",
        "single_part",
        (r"\bнакладк\w*[^\n]{0,20}арк\w*\b",),
    ),
    (
        "clutch",
        "clutch_release_plate",
        "component",
        (r"\bдиск\w*[^\n]{0,20}выключен\w*[^\n]{0,20}сцеплен\w*\b",),
    ),
    (
        "pedal_assembly",
        "clutch_pedal",
        "single_part",
        (r"\bпедал\w*\s+(?:сцеплен|зчеплен)\w*\b",),
    ),
    (
        "pedal_assembly",
        "accelerator_pedal",
        "single_part",
        (r"\bпедал\w*\s+газ\w*\b", r"\baccelerator\s+pedal\b"),
    ),
    (
        "cooling_electrical",
        "fan_control_module",
        "component",
        (
            r"\bблок\w*[^\n]{0,20}(?:управл|керуван)\w*[^\n]{0,25}(?:эл\.?\s*)?вентилятор\w*\b",
        ),
    ),
    (
        "lighting_controls",
        "lighting_control_module",
        "component",
        (r"\bблок\w*[^\n]{0,20}(?:управл|керуван)\w*[^\n]{0,20}(?:свет|світл)\w*\b",),
    ),
    (
        "driveline",
        "drive_shaft",
        "complete_assembly",
        (
            r"\b(?:вал\w*\s+приводн|приводн\w*\s+вал|(?:шарнирн|шарнірн)\w*\s+комплект\w*[^\n]{0,25}приводн\w*\s+вал)\w*\b",
        ),
    ),
    (
        "transmission",
        "speedometer_drive_gear",
        "component",
        (r"\bшестерн\w*[^\n]{0,25}(?:привод\w*[^\n]{0,15})?спидометр\w*\b",),
    ),
    (
        "exhaust_mount",
        "exhaust_clamp",
        "component",
        (r"\bскоб\w*[^\n]{0,20}(?:глушител|глушник)\w*\b",),
    ),
    (
        "exhaust_mount",
        "exhaust_sealing_ring",
        "component",
        (r"\bкольц\w*[^\n]{0,20}(?:глушител|глушник)\w*\b",),
    ),
    (
        "fuel_system",
        "fuel_return_separator",
        "component",
        (r"\bсеп[ао]ратор\w*[^\n]{0,20}(?:обраток|обратк)\w*\b",),
    ),
    (
        "engine_bearing",
        "crankshaft_pilot_bearing",
        "single_part",
        (
            r"\b(?:подшипник|підшипник)\w*[^\n]{0,25}(?:коленвал|колінвал)\w*[^\n]{0,15}игольчат\w*\b",
        ),
    ),
    (
        "driveline_bearing",
        "propshaft_support_cushion",
        "component",
        (r"\bподушк\w*[^\n]{0,25}(?:опор+н|подвесн)\w*[^\n]{0,20}кардан\w*\b",),
    ),
    (
        "suspension",
        "strut_mount",
        "single_part",
        (r"\bподушк\w*[^\n]{0,20}стойк\w*\b",),
    ),
    (
        "steering",
        "steering_rack_boot",
        "component",
        (
            r"\b(?:пыльник|пиловик|пильник|пільник)\w*[^\n]{0,25}(?:рулев|рульов|кермов)\w*\s+тяг\w*\b",
        ),
    ),
    (
        "clutch_control",
        "clutch_ratchet",
        "component",
        (r"\b(?:трещотк|тріскавк)\w*[^\n]{0,20}(?:сцеплен|зчеплен)\w*\b",),
    ),
    (
        "vehicle_lighting",
        "rear_lamp_circuit_board",
        "component",
        (r"\bплат\w*[^\n]{0,20}задн\w*[^\n]{0,15}(?:фонар|ліхтар)\w*\b",),
    ),
    (
        "cooling",
        "coolant_distribution_flange",
        "component",
        (r"\bраспределител\w*[^\n]{0,15}вод\w*[^\n]{0,15}(?:тройник)?\w*\b",),
    ),
    (
        "transmission_controls",
        "shifter_assembly",
        "complete_assembly",
        (r"^\s*кулиса\w*[^\n]{0,15}(?:кпп|мкп|акп)\b",),
    ),
    (
        "transmission_controls",
        "shifter_boot",
        "component",
        (r"\b(?:чехол|чохол)\w*[^\n]{0,20}кул[иі]с\w*[^\n]{0,15}(?:кпп|мкп|акп)?\b",),
    ),
    (
        "engine_control",
        "diesel_stop_actuator",
        "component",
        (r"\bглушилк\w*[^\n]{0,20}(?:двигат|двигун)\w*\b",),
    ),
    (
        "steering",
        "tie_rod_end",
        "single_part",
        (r"\b(?:наконечник\w*\s+рулев|рулев\w*\s+наконечник)\w*\b",),
    ),
    (
        "window_regulator",
        "window_regulator",
        "complete_assembly",
        (r"\bстеклоподъемни\w*\b",),
    ),
    (
        "cooling_fan",
        "engine_cooling_fan",
        "complete_assembly",
        (r"\bвентилятор\w*\s+основн\w*\b",),
    ),
    (
        "electrical_connector",
        "fan_connector",
        "connector",
        (
            r"\b(?:разъем|разъём|роз['’]?єм)\w*[^\n]{0,25}(?:электро\s*)?вентилятор\w*\b",
        ),
    ),
    (
        "electrical_protection",
        "fuse",
        "single_part",
        (r"^\s*(?:предохранител|запобіжник)\w*(?:\s|$)",),
    ),
    (
        "body_grille",
        "lower_grille",
        "single_part",
        (r"^\s*(?:решетк|решотк)\w*\s+нижн\w*\b",),
    ),
    (
        "body_trim",
        "headlamp_trim",
        "component",
        (r"\bнакладк\w*[^\n]{0,15}под\s+фар\w*\b",),
    ),
    (
        "wheel_fastener",
        "wheel_bolt",
        "single_part",
        (r"\bболт\w*\s+колесн\w*\b",),
    ),
    (
        "engine_fastener",
        "crankshaft_bolt",
        "single_part",
        (r"\bболт\w*[^\n]{0,20}(?:коленвал|колінвал)\w*\b",),
    ),
    (
        "body_fastener",
        "door_hinge_bolt",
        "single_part",
        (
            r"\bболт\w*[^\n]{0,20}(?:креплен\w*[^\n]{0,20})?дверн\w*[^\n]{0,12}петл\w*\b",
        ),
    ),
    (
        "belt_drive_fastener",
        "alternator_tension_bolt",
        "single_part",
        (r"\bболт\w*[^\n]{0,20}натяж\w*[^\n]{0,20}генератор\w*\b",),
    ),
    (
        "belt_drive_fastener",
        "tensioner_roller_bolt",
        "single_part",
        (r"\bболт\w*[^\n]{0,20}натяжн\w*[^\n]{0,15}ролик\w*\b",),
    ),
    (
        "engine_fastener",
        "cylinder_head_bolt_set",
        "set",
        (r"\bкомплект\w*[^\n]{0,15}болт\w*[^\n]{0,15}гбц\b",),
    ),
    (
        "engine_mount",
        "engine_mount_bracket",
        "component",
        (r"\bкронштейн\w*[^\n]{0,25}(?:перед\w*\s+)?двиг\w*\b",),
    ),
    (
        "body_badge",
        "vehicle_badge",
        "component",
        (r"^\s*(?:надпись|знак|ш[иы]льдик)\w*(?:\s|$)",),
    ),
    (
        "cooling_fan",
        "ac_condenser_fan",
        "complete_assembly",
        (
            r"\bмотор\w*[^\n]{0,35}вентилятор\w*[^\n]{0,30}кондиционер\w*\b",
            r"\bмотор\w*[^\n]{0,35}кондиционер\w*\b",
        ),
    ),
    (
        "suspension",
        "leaf_spring_pad",
        "component",
        (r"\bподушк\w*[^\n]{0,25}ресс?ор\w*\b",),
    ),
    (
        "automotive_chemical",
        "sealant",
        "consumable",
        (r"^\s*герметик\w*(?:\s|$)",),
    ),
    (
        "door_lock",
        "lock_striker",
        "component",
        (r"^\s*скоба\w*[^\n]{0,25}двер\w*\b", r"\bфиксатор\w*[^\n]{0,20}двер\w*\b"),
    ),
    (
        "steering",
        "steering_column_bushing",
        "single_part",
        (
            r"\bвтулк\w*[^\n]{0,20}(?:сайлентблок\w*[^\n]{0,12})?(?:рулев|рульов|кермов)\w*[^\n]{0,15}вал\w*\b",
        ),
    ),
    (
        "transmission",
        "input_shaft",
        "single_part",
        (r"\b(?:первичн|первинн)\w*\s+вал\w*[^\n]{0,15}(?:кпп|мкп)?\b",),
    ),
    (
        "mirror",
        "mirror_cover",
        "component",
        (r"\bнакладк\w*[^\n]{0,20}(?:зеркал|дзеркал)\w*\b",),
    ),
    (
        "antenna",
        "electric_antenna",
        "complete_assembly",
        (r"^\s*антен+а\w*[^\n]{0,20}електричн\w*\b",),
    ),
    (
        "starting_system",
        "starter_components",
        "component",
        (r"^\s*бенд[іи]кс\w*(?:\s|$)",),
    ),
    (
        "ignition_system",
        "distributor_shaft",
        "component",
        (r"\bвал\w*[^\n]{0,15}трамблер\w*\b",),
    ),
    (
        "engine_bearing",
        "intermediate_shaft_bearing",
        "component",
        (r"\bвкладыш\w*[^\n]{0,20}пром\.?\s*вал\w*\b",),
    ),
    (
        "mirror",
        "mirror_glass",
        "component",
        (r"\bвставк\w*[^\n]{0,20}(?:заркал|зеркал|дзеркал)\w*\b",),
    ),
    (
        "wiper_system",
        "wiper_blade",
        "single_part",
        (
            r"^\s*дворник\w*[^\n]{0,15}комплект\w*\b",
            r"^\s*щ[іи]тк\w*[^\n]{0,20}склоочис\w*\b",
        ),
    ),
    (
        "clutch",
        "clutch_release_plate",
        "component",
        (r"\bдиск\w*[^\n]{0,20}вимикан\w*[^\n]{0,20}зчеплен\w*\b",),
    ),
    (
        "vehicle_lighting",
        "third_brake_light",
        "complete_assembly",
        (r"\bдополнительн\w*[^\n]{0,15}стоп\s*сигнал\w*\b",),
    ),
    (
        "body_trim",
        "bumper_cover_cap",
        "component",
        (r"\bзаглушк\w*[^\n]{0,20}бампер\w*\b",),
    ),
    (
        "interior_electrical",
        "cigarette_lighter",
        "complete_assembly",
        (r"^\s*запальничк\w*[^\n]{0,15}збор\w*\b",),
    ),
    (
        "door_lock",
        "outer_door_lock_component",
        "component",
        (
            r"\b(?:зовнішн|наружн)\w*[^\n]{0,20}част\w*[^\n]{0,20}дверн\w*[^\n]{0,15}замк\w*\b",
        ),
    ),
    (
        "exhaust_mount",
        "exhaust_sealing_ring",
        "component",
        (r"\bкільц\w*[^\n]{0,20}глушник\w*\b",),
    ),
    (
        "exhaust_emissions",
        "egr_valve",
        "single_part",
        (r"\bклапан\w*\s+egr\b", r"\begr\s+valve\b"),
    ),
    (
        "turbo_control",
        "turbo_control_valve",
        "single_part",
        (r"\bклапан\w*[^\n]{0,25}управл\w*[^\n]{0,20}турбин\w*\b",),
    ),
    (
        "door_controls",
        "trunk_release_switch",
        "single_part",
        (
            r"\bкнопк\w*[^\n]{0,25}(?:открыван|відкриван|відкритт|привод)\w*[^\n]{0,30}(?:багажник|кришк\w*\s+багажник)\w*\b",
        ),
    ),
    (
        "door_controls",
        "interior_lock_button",
        "set",
        (
            r"\bкнопк\w*[^\n]{0,25}(?:открыт|відкрит)\w*[^\n]{0,20}замк\w*[^\n]{0,20}салон\w*\b",
        ),
    ),
    (
        "wheel_trim",
        "wheel_center_cap",
        "single_part",
        (r"\bколпак\w*[^\n]{0,20}колесн\w*[^\n]{0,15}диск\w*\b",),
    ),
    (
        "door_lock",
        "lock_cylinder_set",
        "set",
        (
            r"\bкомплект\w*[^\n]{0,20}(?:личинок|особистк|серцевин)\w*[^\n]{0,15}замк\w*\b",
        ),
    ),
    (
        "timing_chain_drive",
        "timing_chain_kit",
        "kit",
        (
            r"\bкомплект\w*[^\n]{0,25}(?:цеп|цели)\w*[^\n]{0,20}привод\w*[^\n]{0,20}(?:распредвал|розподіл)\w*\b",
        ),
    ),
    (
        "ignition_lock",
        "lock_assembly",
        "complete_assembly",
        (
            r"\bкорпус\w*[^\n]{0,20}замк\w*[^\n]{0,15}заж\w*[^\n]{0,35}личинк\w*[^\n]{0,35}конт\w*[^\n]{0,10}груп\w*\b",
        ),
    ),
    (
        "driveline_bearing",
        "center_support_bearing_housing",
        "component",
        (r"\b(?:корпус|кронштейн)\w*[^\n]{0,25}подвесн\w*[^\n]{0,20}подшипник\w*\b",),
    ),
    (
        "transmission_mount",
        "gearbox_bracket",
        "component",
        (r"\bкронштейн\w*[^\n]{0,20}(?:кпп|мкп|акп)\b",),
    ),
    (
        "door_check",
        "door_check_bracket",
        "component",
        (r"\bкронштейн\w*[^\n]{0,25}обмежувач\w*[^\n]{0,20}двер\w*\b",),
    ),
    (
        "cooling_fan",
        "fan_impeller",
        "component",
        (r"^\s*кр[ыи]льчатк\w*[^\n]{0,20}\d{3}\s*мм\b",),
    ),
    (
        "filter",
        "oil_filter_cap",
        "component",
        (r"\bкрышк\w*[^\n]{0,25}(?:маслян|оливн)\w*[^\n]{0,15}фильтр\w*\b",),
    ),
    (
        "door_lock",
        "trunk_lock_cylinder",
        "component",
        (r"\b(?:личинк|серцевин)\w*[^\n]{0,25}замк\w*[^\n]{0,20}багажник\w*\b",),
    ),
    (
        "belt_drive",
        "tensioner_assembly",
        "complete_assembly",
        (r"\bмехан[іи]зм\w*[^\n]{0,20}натяг\w*[^\n]{0,20}генератор\w*\b",),
    ),
    (
        "window_regulator",
        "window_regulator_motor",
        "complete_assembly",
        (r"\bмотор\w*[^\n]{0,25}(?:стеклоп|склоп)\w*\b",),
    ),
    (
        "interior_trim",
        "dashboard_trim",
        "component",
        (r"\bнакладк\w*[^\n]{0,20}панел\w*[^\n]{0,15}прибор\w*\b",),
    ),
    (
        "body_trim",
        "bumper_trim",
        "set",
        (r"\bнакладк\w*[^\n]{0,20}бампер\w*\b",),
    ),
    (
        "body_mounting",
        "bumper_bracket",
        "component",
        (r"\b(?:направляюч|напрямн)\w*[^\n]{0,20}бампер\w*\b",),
    ),
    (
        "door_hardware",
        "sliding_door_guide",
        "component",
        (
            r"\b(?:направляющ|спрямовуюч)\w*[^\n]{0,25}(?:задн|висувн|боков)\w*[^\n]{0,20}двер\w*\b",
        ),
    ),
    (
        "cooling",
        "coolant_recirculation_pump",
        "complete_assembly",
        (r"\bнасос\w*[^\n]{0,25}рециркуляц\w*[^\n]{0,20}антифриз\w*\b",),
    ),
    (
        "washer_system",
        "washer_check_valve",
        "single_part",
        (r"\bобратн\w*[^\n]{0,15}клапан\w*[^\n]{0,20}омывател\w*\b",),
    ),
    (
        "suspension",
        "spring_seat",
        "component",
        (r"\bопорн\w*[^\n]{0,15}чашк\w*[^\n]{0,30}пруж\w*\b",),
    ),
    (
        "body_lighting",
        "bumper_reflector",
        "single_part",
        (r"\b(?:отражател|светоотражател)\w*[^\n]{0,25}бампер\w*\b",),
    ),
    (
        "belt_drive_fastener",
        "tensioner_pivot_pin",
        "component",
        (r"\bпалец\w*[^\n]{0,20}натяжн\w*[^\n]{0,15}ролик\w*\b",),
    ),
    (
        "coolant_hose",
        "heater_hose",
        "single_part",
        (r"\bпатр\w*бок\w*[^\n]{0,25}печк\w*\b",),
    ),
    (
        "air_intake_hose",
        "intake_hose",
        "single_part",
        (r"\bпатрубок\w*[^\n]{0,20}воздушн\w*\b",),
    ),
    (
        "hvac_controls",
        "heater_control_switch",
        "single_part",
        (r"\bпереключател\w*[^\n]{0,20}печк\w*\b",),
    ),
    (
        "body_hardware",
        "tow_eye",
        "single_part",
        (r"\bпетл\w*[^\n]{0,20}буксиров\w*\b",),
    ),
    (
        "suspension",
        "shock_absorber_boot",
        "component",
        (r"\b(?:пиловик|пыльник|пільник)\w*[^\n]{0,20}ам+\w*орт\w*\b",),
    ),
    (
        "clutch",
        "release_bearing",
        "single_part",
        (r"\bпідшипник\w*[^\n]{0,15}виконавч\w*\b",),
    ),
    (
        "suspension_bushing",
        "floating_bushing",
        "single_part",
        (r"\bплавающ\w*[^\n]{0,15}сайлентблок\w*\b",),
    ),
    (
        "drum_brake_hardware",
        "brake_shoe_adjuster",
        "single_part",
        (
            r"\b(?:планк|розпірн\w*\s+планк)\w*[^\n]{0,25}(?:тормозн|гальм)\w*[^\n]{0,20}колодок\w*\b",
        ),
    ),
    (
        "door_trim",
        "door_handle_trim",
        "component",
        (r"\bпластик\w*[^\n]{0,20}дверн\w*[^\n]{0,15}ручк\w*\b",),
    ),
    (
        "vehicle_lighting",
        "turn_signal_repeater",
        "complete_assembly",
        (r"^\s*повторител\w*[^\n]{0,15}поворот\w*\b",),
    ),
    (
        "vehicle_lighting",
        "license_plate_lamp",
        "complete_assembly",
        (r"\bподсветк\w*[^\n]{0,20}номер\w*\b",),
    ),
    (
        "exhaust_mount",
        "exhaust_hanger_set",
        "set",
        (r"\bподушк\w*[^\n]{0,20}(?:глушител|глушник)\w*[^\n]{0,20}комплект\w*\b",),
    ),
    (
        "wiper_system",
        "wiper_linkage",
        "complete_assembly",
        (r"\bпривод\w*[^\n]{0,20}стеклоочист\w*[^\n]{0,20}трапец\w*\b",),
    ),
    (
        "gasket",
        "engine_gasket_kit",
        "kit",
        (r"\bпро+кладк\w*[^\n]{0,20}двиг\w*[^\n]{0,15}компл\w*\b",),
    ),
    (
        "transmission_electrical",
        "transmission_connector",
        "connector",
        (r"\bразъем\w*[^\n]{0,20}(?:акп|мкп|кпп)\b",),
    ),
    (
        "belt_drive",
        "serpentine_belt",
        "single_part",
        (r"^\s*рем(?:е|і)?н\w*\s+ручейков\w*\b",),
    ),
    (
        "belt_drive",
        "timing_belt",
        "single_part",
        (r"^\s*ремінь\s+зубчаст\w*\b",),
    ),
    (
        "suspension",
        "control_arm_repair_kit",
        "kit",
        (r"\bремкомплект\w*[^\n]{0,20}(?:рычаг|важел)\w*\b",),
    ),
    (
        "steering",
        "steering_idler_repair_kit",
        "kit",
        (r"\bремкомплект\w*[^\n]{0,20}маятник\w*\b",),
    ),
    (
        "transmission_controls",
        "shifter_repair_kit",
        "kit",
        (r"\bремкомплект\w*[^\n]{0,20}(?:кулис|кулак\w*[^\n]{0,12}(?:кпп|мкп))\w*\b",),
    ),
    (
        "fuel_hose",
        "leak_off_hose_kit",
        "kit",
        (r"\bремкомплект\w*[^\n]{0,25}шланг\w*[^\n]{0,20}обратк\w*\b",),
    ),
    (
        "door_hardware",
        "sliding_door_slider_kit",
        "kit",
        (
            r"\bрем(?:к\w*|[-.\s]*к[-.\s]*т)[^\n]{0,20}саласк\w*[^\n]{0,20}бок\w*[^\n]{0,15}двер\w*\b",
        ),
    ),
    (
        "engine_internal",
        "camshaft",
        "single_part",
        (r"^\s*(?:розподвал|розподільн\w*\s+вал)\w*\b",),
    ),
    (
        "transmission_controls",
        "automatic_transmission_selector",
        "complete_assembly",
        (r"\bселектор\w*[^\n]{0,20}(?:акп|автомат)\w*\b",),
    ),
    (
        "fuel_evaporation",
        "fuel_vapor_separator",
        "component",
        (r"\bсепаратор\w*[^\n]{0,20}пар\w*[^\n]{0,20}бензин\w*\b",),
    ),
    (
        "suspension",
        "leaf_spring_shackle",
        "single_part",
        (r"\bсережк\w*[^\n]{0,20}ресс?ор\w*\b",),
    ),
    (
        "vehicle_lighting",
        "tail_lamp_lens",
        "component",
        (r"\bстекл\w*[^\n]{0,20}задн\w*[^\n]{0,15}фонар\w*\b",),
    ),
    (
        "engine_internal",
        "valve_tappet",
        "single_part",
        (r"\bтолкател\w*[^\n]{0,20}клапан\w*\b",),
    ),
    (
        "door_hardware",
        "door_lock_cable",
        "single_part",
        (
            r"\bтрос\w*[^\n]{0,35}(?:замк|открыван)\w*[^\n]{0,35}двер\w*\b",
            r"\bтрос\w*\s+двер\w*\b",
        ),
    ),
    (
        "turbo_lubrication",
        "turbo_oil_line",
        "single_part",
        (r"\bтрубк\w*[^\n]{0,20}змащен\w*[^\n]{0,15}турбін\w*\b",),
    ),
    (
        "fuel_line",
        "injection_pump_line",
        "single_part",
        (r"\bтрубк\w*[^\n]{0,20}(?:тнвд|топливн)\w*\b",),
    ),
    (
        "suspension",
        "stabilizer_link",
        "single_part",
        (r"\bтяг\w*[^\n]{0,25}стабилизатор\w*\b",),
    ),
    (
        "suspension_link",
        "rear_camber_link",
        "single_part",
        (r"\bтяг\w*[^\n]{0,20}задн\w*[^\n]{0,20}верхн\w*[^\n]{0,20}розвал\w*\b",),
    ),
    (
        "transmission_controls",
        "shift_linkage_rod",
        "single_part",
        (r"\bтяжк\w*[^\n]{0,20}(?:кпп|мкп)\b",),
    ),
    (
        "door_seal",
        "door_weatherstrip",
        "single_part",
        (r"\bуплотнител\w*[^\n]{0,20}двер\w*\b",),
    ),
    (
        "fuel_line",
        "injection_line_clip",
        "component",
        (r"\bф[іи]ксатор\w*[^\n]{0,20}трубок\w*[^\n]{0,20}тнвд\b",),
    ),
    (
        "suspension",
        "kingpin",
        "single_part",
        (r"\bшкворен\w*\b",),
    ),
    (
        "fuel_hose",
        "fuel_return_hose",
        "single_part",
        (r"\bшланг\w*[^\n]{0,20}обратк\w*[^\n]{0,20}топлив\w*\b",),
    ),
    (
        "steering_hydraulics",
        "power_steering_pump_fitting",
        "component",
        (r"\bштуцер\w*[^\n]{0,20}насос\w*[^\n]{0,15}г\s*[./-]?\s*у\b",),
    ),
    (
        "cooling_fan",
        "ac_condenser_fan",
        "complete_assembly",
        (
            r"\bмотор\w*[^\n]{0,35}вентилятор\w*[^\n]{0,30}кондиціонер\w*\b",
            r"\bмотор\w*[^\n]{0,35}кондиціонер\w*\b",
        ),
    ),
    (
        "hvac",
        "cabin_blower",
        "complete_assembly",
        (r"\bмотор\w*[^\n]{0,20}об[іи]гр[іи]в\w*\b",),
    ),
    (
        "fuel_system",
        "fuel_priming_pump",
        "complete_assembly",
        (r"\bнасос\w*[^\n]{0,20}подкачк\w*\b",),
    ),
    (
        "driveline",
        "halfshaft",
        "complete_assembly",
        (r"^\s*п[іи]вв[іи]сь\w*[^\n]{0,30}(?:збор|в\s+збор)\w*\b",),
    ),
    (
        "suspension_joint",
        "ball_joint_repair_kit",
        "kit",
        (
            r"\b(?:шаров|кульов)\w*[^\n]{0,25}ремкомплект\w*[^\n]{0,25}(?:направл|спрямов)\w*\b",
        ),
    ),
    (
        "door_lock",
        "lock_set",
        "set",
        (r"\bкомплект\W*замк\w*[^\n]{0,35}(?:речов|бардач)\w*\b",),
    ),
    (
        "washer_system",
        "washer_hose_adapter",
        "component",
        (r"\bпереходник\w*[^\n]{0,20}трубк\w*[^\n]{0,20}омывател\w*\b",),
    ),
    (
        "belt_drive",
        "",
        "",
        (
            r"\bролик\w*[^\n]{0,35}(?:поликлин|поліклін|приводн\w*\s+рем|рем(?:е|і)?н\w*\s+паразит)\w*\b",
            r"\bролик\w*\s+натяж(?:ки|іння|ения)\w*\b",
            r"\bролик\w*[^\n]{0,35}(?:модул\w*\s+)?натягувач\w*[^\n]{0,25}ремен\w*\b",
        ),
    ),
    (
        "door_hardware",
        "sliding_door_roller",
        "single_part",
        (
            r"\bролик\w*[^\n]{0,25}(?:боков|бок\.?|в[іи]дсувн|відсувн|сдвижн)\w*[^\n]{0,20}двер\w*\b",
            r"\bролик\w*[^\n]{0,20}двер\w*[^\n]{0,20}(?:нижн|средн|верхн)\w*\b",
            r"\bролик\w*[^\n]{0,20}кронштейн\w*[^\n]{0,20}(?:відсувн|сдвижн)\w*[^\n]{0,15}двер\w*\b",
        ),
    ),
    (
        "door_hardware",
        "trunk_release_handle",
        "component",
        (
            r"\bручк\w*[^\n]{0,25}(?:відкриван|замк)\w*[^\n]{0,25}(?:багажник|кришк\w*[^\n]{0,15}багажник)\w*\b",
        ),
    ),
    (
        "oil_seal",
        "transmission_oil_seal",
        "single_part",
        (r"\bсальник\w*[^\n]{0,20}(?:мкп|кпп|акп)\b",),
    ),
    (
        "oil_seal",
        "differential_pinion_oil_seal",
        "single_part",
        (r"\bсальник\w*[^\n]{0,20}хвостовик\w*[^\n]{0,20}редуктор\w*\b",),
    ),
    (
        "vacuum_system",
        "vacuum_filter",
        "single_part",
        (r"\bфильтр\w*[^\n]{0,20}вакуумн\w*[^\n]{0,15}систем\w*\b",),
    ),
    (
        "door_check",
        "door_stop",
        "component",
        (r"\bфіксатор\w*[^\n]{0,20}двер\w*\b",),
    ),
    (
        "steering",
        "steering_idler_repair_kit",
        "kit",
        (r"\bрем\.?\s*комплект\w*[^\n]{0,20}маятник\w*\b",),
    ),
    (
        "door_hardware",
        "sliding_door_rod_kit",
        "kit",
        (
            r"\bремкомплект\w*[^\n]{0,20}раздвижн\w*[^\n]{0,15}тяг\w*[^\n]{0,20}двер\w*\b",
        ),
    ),
    (
        "suspension",
        "steering_knuckle_repair_kit",
        "kit",
        (r"\bрем\.?\s*комплект\w*[^\n]{0,20}кулак\w*(?![^\n]{0,15}(?:кпп|мкп))",),
    ),
    (
        "generic_fan_motor",
        "generic_fan_motor",
        "",
        (
            r"^\s*мотор\w*\s+вентилятор\w*(?:\s|$)",
            r"^\s*fan\s+motor(?:\s|$)",
        ),
    ),
    (
        "steering",
        "",
        "",
        (r"^\s*(?:гідропідсилювач|гидроусилитель)\w*(?![^\n]{0,30}(?:гальм|тормоз))",),
    ),
    (
        "generic_handle",
        "",
        "single_part",
        (
            r"^\s*ручк\w*(?:\s+[\w./-]+){0,4}\s*$",
            r"^\s*handle(?:\s+[\w./-]+){0,4}\s*$",
        ),
    ),
)

# Some marketplace titles assert a useful coarse component family but omit the
# subsystem needed for a safe closed subtype.  These patterns are consulted
# only when the same source tier also contains explicit automotive context.
# They may disprove an unrelated family, but compatibility pairs below keep a
# plausible steering/suspension comparison UNKNOWN rather than manufacturing a
# positive identity claim.
_AUTOMOTIVE_GENERIC_PART_PATTERNS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "generic_hydraulic_pump",
        "",
        "",
        (
            r"^\s*насос\w*\s+г[іи]дравл\w*\b",
            r"^\s*г[іи]дравл\w*\s+насос\w*\b",
            r"^\s*hydraulic\s+pump\b",
        ),
    ),
    (
        "chassis_linkage",
        "",
        "",
        (
            r"^\s*(?:важ(?:іл|ел)|рычаг)\w*\s+(?:та|и)\s+тяг\w*\b",
            r"^\s*(?:control\s+arms?|levers?)\s+(?:and|&)\s+(?:rods?|links?)\b",
        ),
    ),
)

_SIDE_PATTERNS = {
    "left": (r"\bлев\w*\b", r"\bлів\w*\b", r"\bleft\b"),
    "right": (r"\bправ\w*\b", r"\bright\b"),
}
_POSITION_PATTERNS = {
    "front": (
        r"\bпередн\w*\b",
        # Strictly dotted catalogue abbreviation (``пер.маточ.``).
        # Requiring the dot avoids matching words such as ``переключатель``.
        r"\bпер\.",
        r"\bfront\b",
    ),
    "rear": (r"\bзадн\w*\b", r"\brear\b"),
}
_VERTICAL_POSITION_PATTERNS = {
    "upper": (
        r"\bверхн\w*\s+(?:шар\w*\s+)?опор\w*\b",
        r"\bопор\w*\s+(?:амортизатор\w*\s+)?верхн\w*\b",
        r"\bверхн\w*\s+ball\s+joint\b",
        r"\bball\s+joint\s+upper\b",
    ),
    "lower": (
        r"\bнижн\w*\s+(?:шар\w*\s+)?опор\w*\b",
        r"\bопор\w*\s+(?:амортизатор\w*\s+)?нижн\w*\b",
        r"\bнижн\w*\s+ball\s+joint\b",
        r"\bball\s+joint\s+lower\b",
    ),
}
_CV_JOINT_VARIANT_PATTERNS = {
    "inner": (
        r"\bвнутрішн\w*\b",
        r"\bвнутренн\w*\b",
        r"\binner\b",
    ),
    "outer": (
        r"\bзовнішн\w*\b",
        r"\bнаружн\w*\b",
        r"\bouter\b",
    ),
}
_FUEL_TYPE_PATTERNS = {
    "diesel": (
        r"\bдизел\w*\b",
        r"\bdiesel\b",
        r"\b(?:tdi|tdci|cdti|crdi|hdi|cdi|dti|jtd|dci|mjtd)\b",
    ),
    "petrol": (
        r"\bбензин\w*\b",
        r"\bpetrol\b",
        r"\bgasoline\b",
        r"\b(?:mpi|tsi|tfsi)\b",
    ),
}
_BODY_VARIANT_ALIASES = {
    "sedan": "sedan",
    "седан": "sedan",
    "hatchback": "hatchback",
    "хетчбек": "hatchback",
    "хэтчбек": "hatchback",
    "wagon": "wagon",
    "estate": "wagon",
    "station wagon": "wagon",
    "універсал": "wagon",
    "универсал": "wagon",
    "coupe": "coupe",
    "coupé": "coupe",
    "купе": "coupe",
    "cabriolet": "cabriolet",
    "convertible": "cabriolet",
    "кабріолет": "cabriolet",
    "кабриолет": "cabriolet",
    "van": "van",
    "фургон": "van",
    "minivan": "minivan",
    "мінівен": "minivan",
    "минивэн": "minivan",
    "pickup": "pickup",
    "pick-up": "pickup",
    "пікап": "pickup",
    "пикап": "pickup",
    "bus": "bus",
    "автобус": "bus",
}

# These dimensions describe one sellable variant at a time.  When one record
# contains two different values, an intersection with the other product must
# not turn contradictory source evidence into a false deterministic MATCH.
_EXCLUSIVE_DIMENSIONS = frozenset(
    {
        # A single sellable card should resolve to one typed family,
        # subtype and assembly.  If extraction finds alternatives, an
        # intersection with the reference is not enough to prove identity.
        "part_type",
        "part_subtype",
        "assembly_level",
        "side",
        "position",
        "vertical_position",
        "cv_joint_variant",
        "fuel_type",
        "body_variant",
        "condition",
        "serviceability",
        "climate_variant",
        "transmission_variant",
        "core_construction",
        "connectors_pins",
        "opening_temperature",
        "housing",
        "engine_cylinder_count",
        "power_rating",
        "operating_pressure",
        "package_quantity",
        "unit_basis",
    }
)
_CONDITION_PATTERNS = {
    "used": (
        r"(?<!\w)б\s*[./\\-]\s*у(?:\s*\.)?(?!\w)",
        r"(?<!\w)бу(?!\w)",
        r"(?<!\w)b\s*[./\\-]\s*u(?:\s*\.)?(?!\w)",
        r"(?<=\d)\s+bu(?=\s+_)",
        r"\bвживан\w*\b",
        r"\bразборк\w*\b",
        r"\bшрот\b",
        r"\bused\b",
        r"\b(?:pre[- ]?owned|second[- ]?hand)\b",
    ),
    # Bare ``new`` is a model name in ``VW New Beetle`` and ``нова`` can be a
    # A damaged/bent/parts-only offer is not a usable market price even when
    # the article number is exact. Keep it separate from ``used`` so an
    # operator can distinguish a normal second-hand listing from an unusable
    # one; both remain outside automatic pricing.
    "damaged": (
        r"\b(?:погнут|гнут|пошкодж|пошкоджен|поврежд|слом|трещин|деформ)\w*\b",
        r"\b(?:бит(?:ый|ая|ое|і|ий)|на\s+запчасти|for\s+parts)\b",
        r"\b(?:damaged|bent|broken|cracked|deformed)\b",
    ),
    # seller/name token.  Unstructured text is accepted only when it explicitly
    # states condition; exact structured values are handled separately below.
    "new": (
        r"\b(?:стан|состояние|condition)\s*:?\s*(?:новий|новая|новое|новый|new)\b",
        r"\bbrand[- ]?new\b",
    ),
}

_SERVICEABILITY_PATTERNS = {
    "non_serviceable": (
        r"\bне\s*(?:разборн|розбірн)\w*\b",
        r"\bnon[- ]?serviceable\b",
        r"\bsealed\b",
    ),
    "serviceable": (
        r"\b(?:разборн|розбірн)\w*\b",
        r"\bserviceable\b",
    ),
}

_INCLUDED_COMPONENT_PATTERNS = {
    "without_window_regulator_motor": (
        r"\bбез\s+мотор\w*[^\n]{0,35}(?:стеклоподъемник|стеклопідіймач|склопідйомник|склопідіймач|підйомник|window\s+regulator)\w*\b",
        r"\b(?:стеклоподъемник|стеклопідіймач|склопідйомник|склопідіймач|підйомник|window\s+regulator)\w*[^\n]{0,35}\bбез\s+мотор\w*\b",
    ),
    "with_window_regulator_motor": (
        r"\b(?:с|з)\s+мотор\w*[^\n]{0,35}(?:стеклоподъемник|стеклопідіймач|склопідйомник|склопідіймач|підйомник|window\s+regulator)\w*\b",
        r"\b(?:стеклоподъемник|стеклопідіймач|склопідйомник|склопідіймач|підйомник|window\s+regulator)\w*[^\n]{0,35}\b(?:с|з)\s+мотор\w*\b",
    ),
    "without_brake_wear_sensor": (
        r"\bбез\s+(?:датчик|сенсор)\w*(?:[^\n]{0,15}(?:износ|знос)\w*)?[^\n]{0,20}колодк\w*\b",
        r"\bколодк\w*[^\n]{0,35}\bбез\s+(?:датчик|сенсор)\w*(?:[^\n]{0,15}(?:износ|знос)\w*)?\b",
    ),
    "with_brake_wear_sensor": (
        r"\b(?:с|з)\s+(?:датчик|сенсор)\w*(?:[^\n]{0,15}(?:износ|знос)\w*)?[^\n]{0,20}колодк\w*\b",
        r"\bколодк\w*[^\n]{0,35}\b(?:с|з)\s+(?:датчик|сенсор)\w*(?:[^\n]{0,15}(?:износ|знос)\w*)?\b",
    ),
    "without_impeller": (
        r"\bбез\s+(?:крыльчатк|крильчатк)\w*\b",
        r"\bwithout\s+(?:fan\s+)?(?:impeller|blade)\b",
    ),
    "with_impeller": (
        r"\b(?:с|з)\s+(?:крыльчатк|крильчатк)\w*\b",
        r"\bwith\s+(?:fan\s+)?(?:impeller|blade)\b",
    ),
    "full_engine_gasket_set": (
        r"\b(?:комплект\w*[^\n]{0,25}проклад\w*|проклад\w*[^\n]{0,25}комплект\w*)[^\n]{0,25}(?:полн|повн)\w*\b",
        r"\b(?:полн|повн)\w*[^\n]{0,25}комплект\w*[^\n]{0,25}проклад\w*\b",
        r"\bfull\s+engine\s+gasket\s+(?:kit|set)\b",
    ),
    "lower_engine_gasket_set": (
        r"\bкомплект\w*[^\n]{0,25}проклад\w*[^\n]{0,20}\(?(?:нижн|низ)\w*\)?\b",
        r"\b(?:нижн|низ)\w*[^\n]{0,20}комплект\w*[^\n]{0,25}проклад\w*\b",
        r"\blower\s+engine\s+gasket\s+(?:kit|set)\b",
    ),
    "without_commutator": (r"\bбез\s+комм?утатор\w*\b",),
    "with_commutator": (r"\b(?:с|з)\s+комм?утатор\w*\b",),
    "without_mechanism": (r"\bбез\s+механизм\w*\b",),
    "with_mechanism": (r"\b(?:с|з)\s+механизм\w*\b",),
    "without_servo_sensor": (
        r"\bбез\s+серво\s*[- ]?датч\w*\b",
        r"\bбез\s+серво\s+датч\w*\b",
    ),
    "with_servo_sensor": (
        r"\b(?:с|з)\s+серво\s*[- ]?датч\w*\b",
        r"\b(?:с|з)\s+серво\s+датч\w*\b",
    ),
    "without_ac_drier": (
        r"\bбез\s+(?:осушител|осушувач|receiver\s*[- ]?drier|drier)\w*\b",
    ),
    "with_ac_drier": (
        r"\b(?:с|з)\s+(?:осушител|осушувач|receiver\s*[- ]?drier|drier)\w*\b",
    ),
    "without_steering_rack_tie_rods": (
        r"\b(?:рулев|рульов|кермов)\w*\s+рейк\w*[^\n]{0,35}\bбез\s+тяг\w*\b",
        r"\bбез\s+тяг\w*[^\n]{0,35}(?:рулев|рульов|кермов)\w*\s+рейк\w*\b",
        r"\bрейк\w*\s+(?:рулев|рульов|кермов)\w*[^\n]{0,35}\bбез\s+тяг\w*\b",
    ),
    "with_steering_rack_tie_rods": (
        r"\b(?:рулев|рульов|кермов)\w*\s+рейк\w*[^\n]{0,35}\b(?:с|з)\s+тяг\w*\b",
        r"\b(?:с|з)\s+тяг\w*[^\n]{0,35}(?:рулев|рульов|кермов)\w*\s+рейк\w*\b",
        r"\bрейк\w*\s+(?:рулев|рульов|кермов)\w*[^\n]{0,35}\b(?:с|з)\s+тяг\w*\b",
    ),
    "without_caliper_bracket": (
        r"\b(?:суппорт|супорт|brake\s+caliper)\w*[^\n]{0,35}\bбез\s+(?:скоб|кронштейн|bracket)\w*\b",
        r"\bбез\s+(?:скоб|кронштейн|bracket)\w*[^\n]{0,35}(?:суппорт|супорт|brake\s+caliper)\w*\b",
    ),
    "with_caliper_bracket": (
        r"\b(?:суппорт|супорт|brake\s+caliper)\w*[^\n]{0,35}\b(?:с|з)\s+(?:скоб|кронштейн|bracket)\w*\b",
        r"\b(?:с|з)\s+(?:скоб|кронштейн|bracket)\w*[^\n]{0,35}(?:суппорт|супорт|brake\s+caliper)\w*\b",
    ),
    "without_bracket": (r"\bбез\s+кронштейн\w*\b",),
    "with_bracket": (r"\b(?:с|з)\s+кронштейн\w*\b",),
    "without_cup": (r"\bбез\s+чашк\w*\b",),
    "with_cup": (r"\b(?:с|з)\s+чашк\w*\b",),
    "without_cover": (r"\bбез\s+(?:чохл|кожух)\w*\b",),
    "with_cover": (r"\b(?:с|з)\s+(?:чохл|кожух)\w*\b",),
}

_CLIMATE_VARIANT_PATTERNS = {
    "without_ac": (
        r"(?<![a-zа-я])(?:a/?c|ас)\s*[-−](?!\s*/)",
        r"\bбез\s+кондиц(?:іонер|ионер)\w*\b",
        r"\bwithout\s+(?:a/?c|air\s+conditioning)\b",
    ),
    "with_ac": (
        r"(?<![a-zа-я])(?:a/?c|ас)\s*\+(?!\s*/)",
        r"\b(?:с|з)\s+кондиц(?:іонер|ионер)\w*\b",
        r"\bwith\s+(?:a/?c|air\s+conditioning)\b",
    ),
}

_TRANSMISSION_VARIANT_PATTERNS = {
    "automatic": (
        r"\b[aа][kк][pп]{1,2}\b",
        r"\bautomatic\s+transmission\b",
    ),
    "manual": (
        r"\bмкпп\b",
        r"\bмех\.?\s*кпп\b",
        # Customer radiator titles use the compact form ``мех АС+``.
        r"\bмех\b(?=\s+(?:a/?c|ас)[+-−])",
        r"\bmanual\s+transmission\b",
    ),
}

_CORE_CONSTRUCTION_PATTERNS = {
    "flat_core": (
        r"\b(?:плоск|плоскі)\w*\s+(?:сот|стільник)\w*\b",
        r"\bflat\s+(?:tube|core)\b",
    ),
    "round_core": (
        r"\bкругл\w*\s+(?:сот|стільник)\w*\b",
        r"\bround\s+(?:tube|core)\b",
    ),
}

_NON_AUTOMOTIVE_PATTERNS = (
    r"\b(?:ручк|handle)\w*[^\n]{0,40}(?:мебл|furniture)\w*\b",
    r"\b(?:мебл|furniture)\w*[^\n]{0,40}(?:ручк|handle)\w*\b",
    r"\b(?:картин|живопис|репродукц)\w*[^\n]{0,30}(?:холст|полотн)\w*\b",
    r"\bнаст(?:і|и)нн\w*\s+живопис\w*\b",
    r"\bкорм\w*[^\n]{0,35}(?:кот|собак)\w*\b",
    r"\bled\s+(?:підсвіт|подсвет)\w*[^\n]{0,120}(?:tv|телевизор|hisense)\b",
    r"\b(?:трусы|труси|свитшот|світшот|шеврон)\w*\b",
    r"\b(?:компьютерн|комп['’]?ютерн)\w*\s+(?:стол|стіл)\w*\b",
    r"\bполиц\w*[^\n]{0,25}(?:рабоч|робоч)\w*\s+(?:стол|стіл)\w*\b",
    r"\bспот\w*[^\n]{0,40}\beglo\b",
    r"\bручн\w*\s+прожектор\w*[^\n]{0,60}(?:кемпінг|дач)\w*\b",
    r"\bгачок\w*[^\n]{0,30}\bgtv\b",
    r"\bсповіщувач\w*\s+пожежн\w*\b",
    r"\bпідсвіт\w*[^\n]{0,120}(?:samsung|\bue\d|\bbn\d|jl\.d|crh-bk|телевізор|\btv\b)",
    r"\bнакладк\w*\s+антиковзн\w*\s+для\s+сход\w*\b",
    r"\bшнек\w*\s+для\s+м['’]?ясоруб\w*\b",
    r"\bсковород\w*(?:-сотейник)?\b",
    r"\b(?:usb[^\n]{0,80}кабел|кабел\w*[^\n]{0,80}usb)\w*\b",
    r"\b(?:накладк|щиток)\w*[^\n]{0,35}молотильн\w*\s+барабан\w*\b",
    r"\bмашин\w*[^\n]{0,35}інерц\w*\b",
    r"\bліжк\w*[^\n]{0,40}(?:мал\w*\s+порід|пет\s+фешн)\b",
    r"\b(?:намист|бюстгальтер)\w*\b",
    r"\bциркуляційн\w*\s+насос\w*[^\n]{0,80}\bм3\s*/\s*год\b",
    r"\bламп\w*[^\n]{0,160}(?:манікюр|педикюр)\w*\b",
    r"\bкомпресор\w*[^\n]{0,35}холодильник\w*\b",
    r"\bповідець\w*[^\n]{0,35}собак\w*\b",
    r"\bщоденник\w*\s+шкільн\w*\b",
    r"\bблюд\w*\s+для\s+запікан\w*\b",
    r"\bнабір\w*\s+чайн\w*\b",
    r"\bрамк\w*\s+для\s+(?:сімейн\w*\s+)?фото\b",
    r"\bфільтр\w*\s+для\s+пилосос\w*\b",
    r"\bавтомобільн\w*\s+сонцезахисн\w*\s+парасольк\w*\b",
    r"\bмодул\w*\s+(?:швидк\w*\s+зарядк\w*|живлен\w*)\b",
    r"\bбуферн\w*\s+логічн\w*\s+елемент\w*\b",
    r"\bкомплект\w*\s+проводк\w*[^\n]{0,50}\bввг\b",
    r"\bзірочк\w*[^\n]{0,35}\bdominoni\b",
    r"\bстельов\w*\s+світильник\w*\b",
    r"\bпальт\w*\s+жіноч\w*\b",
    r"\bшаф\w*[^\n]{0,40}\bелектронмаш\b",
    r"\bсвердловинн\w*\s+електронасос\w*\b",
    r"\bарт[- ]?об['’]?єкт\w*\b",
    r"\bніж\w*\s+пласт\w*[^\n]{0,50}(?:навантаж|навант)\w*\.?\b",
    r"\bламп\w*[^\n]{0,35}інспекційн\w*\s+робіт\w*\b",
    r"\b(?:oros|manitou)\b",
    r"\bваля\s+вздульська\b",
    r"\bл(?:і|и)жк\w*[^\n]{0,35}собак\w*\b",
    r"\bм['’]?яч\w*\s+волейбол\w*\b",
    r"\bшлея\w*[^\n]{0,25}(?:нейлон|собак)\w*\b",
    r"\b(?:рулонн\w*\s+штор|скатерт)\w*\b",
    r"\bоружейн\w*\s+смазк\w*\b",
    r"\b(?:ланцюг|цепь)\w*[^\n]{0,45}(?:l\s*=\s*)?\d+(?:[.,]\d+)?\s*м(?:\b|[.])",
    r"\bп(?:и|і)гмент\w*[^\n]{0,35}(?:краск|фарб|maxicar)\w*\b",
    r"\b(?:дріт|проволок)\w*[^\n]{0,40}(?:синельн|помаранч)\w*\b",
    r"\bшнек\w*\s+для\s+насос\w*\b",
    r"\b(?:олівець|карандаш)\w*[^\n]{0,35}(?:графіт|графит)\w*\b",
    r"\bсоломинк\w*\s+для\s+напоїв\b",
    r"\bзаклепк\w*\s+алюмін\w*\b",
    r"\b(?:блокнот|альбом)\w*[^\n]{0,35}\d+\s*(?:л|lis|sheet|sheet)\b",
    r"\bгубк\w*\s+кухонн\w*\b",
    r"\bпакет\w*\s+для\s+см(?:і|и)тт\w*\b",
    r"\bтимчасов\w*\s+тату\w*\b",
    r"\bкрем\w*\s+для\s+(?:лица|обличчя)\b",
    r"\b(?:сачок\w*\s+для\s+метелик|водн\w*\s+гармат|water\s+gun)\w*\b",
    r"\b(?:ляльк|кукл)\w*\b",
    r"\bтрансформер\w*\s+\d[\w-]*\b",
    r"\bшорт\w*\b",
    r"\bшкірян\w*\s+пасок\w*[^\n]{0,30}(?:джинс|штан)\w*\b",
    r"\b(?:книг|книжк)\w*\b",
    r"\b(?:leather\s+book\s+case|phone\s+case)[^\n]{0,40}(?:samsung|iphone|xiaomi)\b",
    r"\bгеотекстил\w*\b",
    r"\bзамок\w*\s+навісн\w*\b",
    r"\b(?:фотофон|фон\s+для\s+фото)\w*\b",
    r"\b(?:сережк|кулон)\w*\b",
    r"\bголовк\w*\s+торцев\w*\b",
    r"\bручн\w*\s+ударн\w*\s+(?:инструмент|інструмент)\w*\b",
    r"\b(?:фарб|краск)\w*\s+для\s+авто\b",
    r"\bролик\w*\s+варіатор\w*\b",
)

_AUTOMOTIVE_CONTEXT_PATTERNS = (
    r"\b(?:audi|bmw|chevrolet|citroen|daewoo|fiat|ford|hyundai|iveco|mazda|mercedes|nissan|opel|peugeot|renault|seat|skoda|toyota|volkswagen|vw)\b",
    r"\b(?:автозапчаст|запчаст|oem|oe)\b",
    r"\b(?:амортиз|кузов|оптик|охлажд|нагрев|подвес|радиатор|рулев|тормоз|сцеплен|шрус|электр)\w*\b",
)

_VEHICLE_MAKE_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "audi": (r"\baudi\b", r"\bауді\b", r"\bауди\b"),
    "bedford": (r"\bbedford\b", r"\bбедфорд\b"),
    "bmw": (r"\bbmw\b", r"\bбмв\b"),
    "chevrolet": (r"\bchevrolet\b", r"\bшеврол\w*\b"),
    "chery": (r"\bchery\b", r"\bcheri\b", r"\bчер[іи]\b"),
    "citroen": (r"\bcitro[eë]n\b", r"\bситроен\w*\b"),
    "dacia": (r"\bdacia\b", r"\bдач[іи]я\b"),
    "daewoo": (r"\bdaewoo?\b", r"\bдео\b", r"\bдеу\b"),
    "dodge": (r"\bdodge\b", r"\bдодж\b"),
    "fiat": (r"\bfiat\b", r"\bф[іи]ат\b"),
    "ford": (r"\bford\b", r"\bфорд\b"),
    "geely": (r"\bgeely\b", r"\bджил[іи]\b"),
    "honda": (r"\bhonda\b", r"\bхонда\b"),
    "hyundai": (r"\bhyundai\b", r"\bhuyndai\b", r"\bх[ею]ндай\b"),
    "iveco": (r"\biveco\b", r"\bівеко\b", r"\bивеко\b"),
    "kia": (r"\bkia\b", r"\bк[іи]а\b"),
    "land_rover": (r"\bland\s+rover\b", r"\bленд\s+ровер\b"),
    "lexus": (r"\blexus\b", r"\bлексус\b"),
    "mazda": (r"\bmazda\b", r"\bмазда\b"),
    "mercedes": (
        r"\bmercedes(?:[- ]benz)?\b",
        r"\bbenz\b",
        r"\bмерседес\w*\b",
        r"\bmb\b",
    ),
    "mitsubishi": (r"\bmitsubishi\b", r"\bм[іи]цуб[іи]с[іи]\b"),
    "nissan": (r"\bnissan\b", r"\bн[іи]ссан\b"),
    "opel": (r"\bopel\b", r"\bопел\w*\b"),
    "peugeot": (r"\bpeugeot\b", r"\bпежо\b"),
    "renault": (r"\brenault\b", r"\bрено\b"),
    "seat": (r"\bseat\b", r"\bсеат\b"),
    "skoda": (r"\bskoda\b", r"\bscoda\b", r"\bшкода\b"),
    "tesla": (r"\btesla\b", r"\bтесла\b"),
    "toyota": (r"\btoyota\b", r"\bтойота\b"),
    "vauxhall": (r"\bvauxhall\b", r"\bвоксхол\w*\b"),
    "volkswagen": (
        r"\bvolkswagen\b",
        r"\bvw\b",
        r"\bфольксваген\w*\b",
    ),
    "volvo": (r"\bvolvo\b", r"\bвольво\b"),
    "zaz": (r"\bzaz\b", r"\bзаз\b"),
}

# Model names are deliberately make-bound.  Tokens such as ``100``, ``A4`` or
# ``T5`` are common in OE numbers and product specifications and therefore may
# not be interpreted without an explicitly extracted vehicle make.  These
# features are diagnostic for the semantic reviewer only; they are not allowed
# to create a deterministic hard stop because a verified cross-platform part
# can legitimately list different vehicle models.
_VEHICLE_MODEL_PATTERNS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "audi": {
        "100": (
            r"\b(?:audi|ауд[іи])\W{0,20}a?100\b",
            r"\ba?100\W{0,20}(?:audi|ауд[іи])\b",
        ),
        "a3": (
            r"\b(?:audi|ауд[іи])\W{0,20}a3\b",
            r"\ba3\W{0,20}(?:audi|ауд[іи])\b",
        ),
        "a4": (
            r"\b(?:audi|ауд[іи])\W{0,20}a4\b",
            r"\ba4\W{0,20}(?:audi|ауд[іи])\b",
        ),
        "a6": (
            r"\b(?:audi|ауд[іи])\W{0,20}a6\b",
            r"\ba6\W{0,20}(?:audi|ауд[іи])\b",
        ),
    },
    "bmw": {
        "x3": (r"\bbmw\W{0,20}x3\b", r"\bx3\W{0,20}bmw\b"),
        "x5": (r"\bbmw\W{0,20}x5\b", r"\bx5\W{0,20}bmw\b"),
    },
    "citroen": {
        "berlingo": (r"\bberlingo\b", r"\bберлінго\b", r"\bберлинго\b"),
        "jumper": (r"\bjumper\b", r"\bджампер\b"),
        "jumpy": (r"\bjumpy\b", r"\bджамп[іи]\b"),
        "nemo": (r"\bnemo\b", r"\bнемо\b"),
    },
    "dacia": {
        "logan": (r"\blogan\b", r"\bлоган\b"),
    },
    "daewoo": {
        "lanos": (r"\blanos\b", r"\bланос\b"),
        "matiz": (r"\bmatiz\b", r"\bмат[іи]з\b"),
        "nexia": (r"\bnexia\b", r"\bнексия\b", r"\bнексія\b"),
        "nubira": (r"\bnubira\b", r"\bнуб[іи]ра\b"),
        "sens": (r"\bsens\b", r"\bсенс\b"),
    },
    "fiat": {
        "doblo": (r"\bdoblo\b", r"\bдобло\b"),
        "ducato": (r"\bducato\b", r"\bдукато\b"),
        "fiorino": (r"\bfiorino\b", r"\bфіор[іи]но\b"),
        "qubo": (r"\bqubo\b", r"\bкубо\b"),
        "scudo": (r"\bscudo\b", r"\bскудо\b"),
    },
    "ford": {
        "escort": (r"\bescort\b", r"\bэскорт\b", r"\bескорт\b"),
        "fiesta": (r"\bfiesta\b", r"\bфиеста\b", r"\bфієста\b"),
        "focus": (r"\bfocus\b", r"\bфокус\b"),
        "galaxy": (r"\bgalaxy\b", r"\bгалакси\b", r"\bгалаксі\b"),
        "mondeo": (r"\bmondeo\b", r"\bмондео\b"),
        "transit": (r"\btransit\b", r"\bтранзит\b", r"\bтранзіт\b"),
    },
    "chery": {
        "amulet": (r"\bamulet\b", r"\bамулет\b"),
    },
    "geely": {
        "mk": (r"\b(?:geely|джил[іи])\W{0,20}mk\b",),
    },
    "hyundai": {
        "accent": (r"\baccent\b", r"\bакцент\b"),
        "elantra": (r"\belantra\b", r"\bэлантра\b", r"\bелантра\b"),
        "h1": (r"\bh\s*-?\s*1\b",),
        "santa_fe": (r"\bsanta\s+fe\b", r"\bсанта\s+фе\b"),
        "tucson": (r"\btucson\b", r"\bтусан\b", r"\bтусон\b"),
    },
    "iveco": {
        "daily": (r"\bdaily\b", r"\bдейлі\b", r"\bдейли\b"),
    },
    "mercedes": {
        "sprinter": (r"\bsprinter\b", r"\bспринтер\b", r"\bспрінтер\b"),
        "vito": (r"\bvito\b", r"\bвито\b", r"\bвіто\b"),
    },
    "opel": {
        "astra": (r"\bastra\b", r"\bастра\b"),
        "kadett": (r"\bkadett?\b", r"\bкадет\b"),
        "movano": (r"\bmovano\b", r"\bмовано\b"),
        "omega": (r"\bomega\b", r"\bомега\b"),
        "vectra": (r"\bvectra\b", r"\bвектра\b"),
        "vivaro": (r"\bvivaro\b", r"\bв[іи]варо\b"),
        "zafira": (r"\bzafira\b", r"\bзаф[іи]ра\b"),
    },
    "peugeot": {
        "bipper": (r"\bbipper\b", r"\bбіппер\b", r"\bбиппер\b"),
        "boxer": (r"\bboxer\b", r"\bбоксер\b"),
        "expert": (r"\bexpert\b", r"\bексперт\b"),
        "partner": (r"\bpartner\b", r"\bпартнер\b"),
    },
    "renault": {
        "clio": (r"\bclio\b", r"\bкл[іи]о\b"),
        "kangoo": (r"\bkangoo\b", r"\bканго\b"),
        "laguna": (r"\blaguna\b", r"\bлагуна\b"),
        "logan": (r"\blogan\b", r"\bлоган\b"),
        "master": (r"\bmaster\b", r"\bмастер\b"),
        "megane": (r"\bmegane\b", r"\bmegan\b", r"\bмеган\b"),
        "scenic": (r"\bscenic\b", r"\bscenik\b", r"\bсцен[іи]к\b"),
        "trafic": (r"\btrafic\b", r"\bтрафик\b", r"\bтрафік\b"),
    },
    "skoda": {
        "fabia": (r"\bfabia\b", r"\bфабия\b", r"\bфабія\b"),
        "octavia": (r"\boctavia\b", r"\bоктавия\b", r"\bоктавія\b"),
    },
    "toyota": {
        "auris": (r"\bauris\b", r"\bаур[іи]с\b"),
        "camry": (r"\bcamry\b", r"\bкамри\b", r"\bкмрі\b"),
        "corolla": (r"\bcorolla\b", r"\bкоролла\b", r"\bкорола\b"),
        "prius": (r"\bprius\b", r"\bпр[іи]ус\b"),
        "sequoia": (r"\bsequoia\b", r"\bсеквойя\b"),
        "tundra": (r"\btundra\b", r"\bтундра\b"),
        "venza": (r"\bvenza\b", r"\bвенза\b"),
    },
    "volkswagen": {
        "bora": (r"\bbora\b", r"\bбора\b"),
        "caddy": (r"\bcaddy\b", r"\bкадди\b", r"\bкадді\b"),
        "crafter": (r"\bcrafter\b", r"\bкрафтер\b"),
        "golf": (r"\bgolf\b", r"\bгольф\b"),
        "passat": (r"\bpassat\b", r"\bпассат\b", r"\bпасат\b"),
        "polo": (r"\bpolo\b", r"\bполо\b"),
        "touran": (r"\btouran\b", r"\bтуран\b"),
        "transporter": (r"\btransporter\b", r"\bтранспортер\b"),
        "touareg": (r"\btouareg\b", r"\btoureg\b", r"\bтуарег\b"),
        "sharan": (r"\bsharan\b", r"\bшаран\b"),
    },
    "zaz": {
        "forza": (r"\bforza\b", r"\bфорза\b"),
        "sens": (r"\bsens\b", r"\bсенс\b"),
    },
}

_VEHICLE_PLATFORM_BY_MODEL: Mapping[str, str] = {
    "citroen:jumper": "sevel_large_van",
    "fiat:ducato": "sevel_large_van",
    "peugeot:boxer": "sevel_large_van",
    "citroen:jumpy": "sevel_mid_van",
    "fiat:scudo": "sevel_mid_van",
    "peugeot:expert": "sevel_mid_van",
    "citroen:nemo": "tofas_small_van",
    "fiat:fiorino": "tofas_small_van",
    "fiat:qubo": "tofas_small_van",
    "peugeot:bipper": "tofas_small_van",
}

# Only model-qualified generation phrases are accepted.  Bare ``B5``, ``T5``
# or ``V40`` tokens are too easily confused with catalogue and OE fragments.
_VEHICLE_GENERATION_HINT_PATTERNS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "volkswagen:golf": {
        "3": (r"\b(?:golf|гольф)[\s-]*(?:iii|3)\b",),
        "4": (r"\b(?:golf|гольф)[\s-]*(?:iv|4)\b",),
    },
    "volkswagen:passat": {
        "b3": (r"\b(?:passat|пасс?ат)\s*b3\b",),
        "b4": (r"\b(?:passat|пасс?ат)\s*b4\b",),
        "b5": (r"\b(?:passat|пасс?ат)\s*b5\b",),
        "b6": (r"\b(?:passat|пасс?ат)\s*b6\b",),
    },
    "volkswagen:transporter": {
        "t4": (r"\b(?:transporter|транспортер)\s*t4\b",),
        "t5": (r"\b(?:transporter|транспортер)\s*t5\b",),
        "t6": (r"\b(?:transporter|транспортер)\s*t6\b",),
    },
    "toyota:camry": {
        "v40": (r"\b(?:camry|камри|камрі)\s*\(?x?v40\)?\b",),
    },
    "ford:focus": {
        "mk1": (r"\b(?:focus|фокус)\s*(?:mk\s*)?(?:i|1)\b",),
        "mk2": (r"\b(?:focus|фокус)\s*(?:mk\s*)?(?:ii|2)\b",),
        "mk3": (r"\b(?:focus|фокус)\s*(?:mk\s*)?(?:iii|3)\b",),
    },
}

_DIMENSIONS_RE = re.compile(
    r"(?<!\d)(\d{2,4})\s*[xх×*]\s*(\d{2,4})"
    r"(?:\s*[xх×*]\s*(\d{1,4}))?\s*(?:mm|мм)?(?!\d)",
    re.IGNORECASE,
)
_BRAKE_DISC_DIAMETER_RE = re.compile(
    r"(?:[ø⌀]|(?:диаметр|діаметр|diameter)\s*[:=]?)\s*(\d{2,4})\s*(?:mm|мм)?\b"
    r"|(?<!\d)(\d{2,4})\s*(?:mm|мм)\b",
    re.IGNORECASE,
)
_SINGLE_DIMENSION_RE = re.compile(
    r"^\s*(\d{1,4})(?:[.,]0+)?\s*(?:mm|мм)?\s*$",
    re.IGNORECASE,
)
_PIN_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:[- ]?pin\b|пін\w*\b|пин\w*\b|"
    r"контакт\w*\b)",
    re.IGNORECASE,
)
_PACKAGE_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:шт(?:\.|\b)|pcs?\b|pieces?\b)",
    re.IGNORECASE,
)
_OPENING_TEMP_RE = re.compile(
    r"(?<!\d)([6-9]\d|1[01]\d|120)\s*(?:°\s*)?(?:c\b|с\b|град)",
    re.IGNORECASE,
)
_YEAR_RANGE_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*[-–—/]\s*((?:19|20)\d{2})(?!\d)"
)
_SHORT_YEAR_RANGE_RE = re.compile(
    r"(?<![\d.,/–—-])(\d{2})\s*[-–—/]\s*(\d{2})(?![\d.,/–—-])"
)
_ENGINE_RE = re.compile(
    r"(?<!\d)(\d[.,]\d)\s*(TDCI|CDTI|CRDI|TFSI|MJTD|TDI|HDI|CDI|DTI|JTD|DCI|TSI|MPI|TD|D|T|I)?\b"
    r"(?!\s*(?:mm|\u043c\u043c|cm|\u0441\u043c|bar|\u0431\u0430\u0440|kw|\u043a\u0432\u0442|w|\u0432\u0442|v|\u0432|\u00b0))",
    re.IGNORECASE,
)
_ENGINE_CYLINDER_COUNT_RE = re.compile(
    r"(?<!\d)([3-8])\s*(?:-\s*(?:ти|х|тих))?\s*(?:цил|ціл)\w*\b",
    re.IGNORECASE,
)
_POWER_RATING_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,3})?)\s*(?:kw|квт)\b",
    re.IGNORECASE,
)
_OPERATING_PRESSURE_RE = re.compile(
    r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:bar|бар)\b",
    re.IGNORECASE,
)

_CHARACTERISTIC_LABELS = {
    # Prom/XLS characteristics often carry the commercial basis only as a
    # label/value pair.  Without these aliases the fields remain in the raw
    # snapshot but never reach the comparison matrix, so an unknown unit could
    # be mistaken for a one-piece offer.
    "package_quantity": (
        "package quantity",
        "quantity in package",
        "кількість в упаков",
        "количество в упаков",
        "кількість штук",
        "количество штук",
    ),
    "unit_basis": (
        "unit basis",
        "measure unit",
        "unit of measure",
        "одиниц",
        "единиц",
    ),
    "ports": ("port", "inlet", "outlet", "патруб", "вхід", "вход", "вихід", "выход"),
    "mounting": ("mount", "кріп", "креп"),
    "opening_temperature": ("temperature", "temp", "температ"),
    "operating_pressure": ("pressure", "давлен", "тиск"),
    "housing": ("housing", "корпус"),
    "dimensions": (
        "dimension",
        "size",
        "розмір",
        "размер",
        "висот",
        "ширин",
        "длин",
        "довжин",
        "глибин",
        "толщ",
        "товщ",
    ),
    "condition": ("condition", "стан", "состояние"),
    "side": (
        "installation side",
        "сторона установки",
        "сторона встановлення",
    ),
    "position": (
        "installation position",
        "розташування",
        "расположение",
        "вісь встановлення",
        "ось установки",
    ),
}

_ANALOGUE_REQUIRED = {
    "radiator": ("part_type", "technical_specs", "inlet_outlet", "engine"),
    # A shock absorber is position-specific.  A verified OE cross can prove
    # the identifier relationship, but it cannot prove that a rear-right
    # sellable unit is interchangeable with a front-left (or an unspecified)
    # unit.  Keep both dimensions explicit so UNKNOWN remains MANUAL_REVIEW.
    "shock_absorber": ("part_type", "side", "position"),
    "ignition_lock": (
        "part_type",
        "assembly_level",
        "connectors_pins",
        "included_components",
    ),
    "steering_reservoir": ("part_type", "ports", "mounting", "included_components"),
    "thermostat": ("part_type", "opening_temperature", "housing", "engine"),
}

# Commercial attributes asserted by the customer seed cannot disappear merely
# because a candidate is connected by a verified cross number. A missing
# candidate value stays UNKNOWN and therefore MANUAL_REVIEW; only an explicit
# deterministic MATCH can make the analogue priceable. Vehicle make/model are
# intentionally absent: legitimate OE crosses frequently span badge-engineered
# platforms (for example Mercedes Sprinter / Volkswagen LT).
_SEED_ASSERTED_ANALOGUE_REQUIRED: tuple[tuple[str, str], ...] = (
    ("part_subtype", "part_subtype"),
    ("assembly_level", "assembly_level"),
    ("serviceability", "serviceability"),
    ("condition", "condition"),
    ("side", "side"),
    ("position", "position"),
    ("vertical_position", "vertical_position"),
    ("cv_joint_variant", "cv_joint_variant"),
    ("fuel_type", "fuel_type"),
    ("pin_count", "connectors_pins"),
    ("dimensions", "technical_specs"),
    ("opening_temperature", "opening_temperature"),
    ("operating_pressure", "operating_pressure"),
    ("housing", "housing"),
    ("included_components", "included_components"),
    ("climate_variant", "climate_variant"),
    ("transmission_variant", "transmission_variant"),
    ("core_construction", "core_construction"),
    ("engine_cylinder_count", "engine_cylinder_count"),
    ("power_rating", "power_rating"),
)

# Exact OE identifies the part number, but it does not prove every physical
# specification from a candidate title.  These are the seed assertions that
# change the sellable configuration and therefore remain mandatory even on an
# exact-OE pricing path.  Geometry, opening temperature, pressure, cylinder
# count and power stay category/analogue requirements instead.
_EXACT_SEED_ASSERTED_REQUIRED = frozenset(
    {
        "part_subtype",
        "assembly_level",
        "serviceability",
        "condition",
        "side",
        "position",
        "vertical_position",
        "cv_joint_variant",
        "fuel_type",
        "connectors_pins",
        "included_components",
        "climate_variant",
        "transmission_variant",
    }
)


_AMBIGUOUS_TAXONOMY_PAIRS = frozenset(
    {
        ("part_type", frozenset({"generic_hydraulic_pump", "steering"})),
        (
            "part_type",
            frozenset({"generic_hydraulic_pump", "steering_hydraulics"}),
        ),
        ("part_type", frozenset({"chassis_linkage", "suspension"})),
        ("part_type", frozenset({"chassis_linkage", "steering"})),
        ("part_type", frozenset({"chassis_linkage", "suspension_link"})),
        ("part_type", frozenset({"generic_bushing", "suspension"})),
        ("part_type", frozenset({"generic_bushing", "engine_mount"})),
        ("part_type", frozenset({"generic_bushing", "vehicle_mount"})),
        ("part_type", frozenset({"generic_handle", "door_hardware"})),
        ("part_type", frozenset({"generic_handle", "window_controls"})),
        ("part_type", frozenset({"generic_handle", "seat_hardware"})),
        ("part_type", frozenset({"generic_handle", "hood_release"})),
        ("part_type", frozenset({"generic_handle", "interior_hardware"})),
        ("part_type", frozenset({"generic_fan_motor", "cooling_fan"})),
        ("part_type", frozenset({"generic_fan_motor", "hvac"})),
        ("part_type", frozenset({"bearing", "wheel_end"})),
        ("part_subtype", frozenset({"generic_bearing", "wheel_bearing"})),
        (
            "part_subtype",
            frozenset({"generic_bushing_set", "control_arm_bushing"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_bushing_set", "axle_beam_bushing"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_bushing_set", "stabilizer_bushing"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_fan_motor", "cooling_fan_motor"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_fan_motor", "engine_cooling_fan"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_fan_motor", "fan_module"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_fan_motor", "cabin_blower"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_cooling_fan_motor", "cooling_fan_motor"}),
        ),
        (
            "part_subtype",
            frozenset({"generic_cooling_fan_motor", "fan_module"}),
        ),
        ("part_subtype", frozenset({"shock_absorber", "strut_insert"})),
        (
            "part_subtype",
            frozenset({"sliding_door_roller", "sliding_door_bracket"}),
        ),
    }
)


def _taxonomy_conflict_is_ambiguous(
    dimension: str,
    left: Sequence[str],
    right: Sequence[str],
) -> bool:
    """Demote catalogue-language overlap to UNKNOWN instead of false conflict.

    A numbered rolling bearing can be sold either by its generic bearing code or
    by its wheel-hub application.  Likewise, older catalogues call a removable
    strut cartridge both an ``insert`` and an ``absorber``, and shorten a
    sliding-door roller/bracket assembly to either component noun.  The wording
    alone cannot prove equality, but it also cannot disprove it.  Exact numbers,
    dimensions, included components and the downstream reviewer must decide.
    """

    return (
        len(left) == len(right) == 1
        and (
            dimension,
            frozenset({left[0], right[0]}),
        )
        in _AMBIGUOUS_TAXONOMY_PAIRS
    )


def build_semantic_feature_matrix(
    our_product: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Return deterministic facts, comparisons and explicit contradictions."""

    ours = extract_semantic_features(our_product)
    theirs = extract_semantic_features(candidate)
    comparisons: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, str]] = []

    def compare(
        dimension: str,
        *,
        our_key: str | None = None,
        candidate_key: str | None = None,
        conflict_is_hard: bool = True,
    ) -> None:
        left = tuple(ours.get(our_key or dimension, FeatureSet()).values)
        right = tuple(theirs.get(candidate_key or dimension, FeatureSet()).values)
        ambiguous_source_values = dimension in _EXCLUSIVE_DIMENSIONS and (
            len(set(left)) > 1 or len(set(right)) > 1
        )
        # Axis-labelled characteristics (length/width/depth) legitimately
        # produce several scalar values for one geometry vector.  Treat only
        # two or more complete vectors as competing sellable variants; this
        # preserves the existing ``680 x 270 x 23`` normalization while
        # holding a title that advertises ``680x278 / 710x330``.
        if dimension == "technical_specs":
            ambiguous_source_values = _has_multiple_geometry_vectors(left) or (
                _has_multiple_geometry_vectors(right)
            )
        if not left or not right or ambiguous_source_values:
            state = "UNKNOWN"
        elif dimension == "year_interval" and _year_intervals_overlap(left, right):
            state = "MATCH"
        elif dimension == "engine" and _engine_values_compatible(left, right):
            state = "MATCH"
        elif dimension == "technical_specs":
            dimension_result = _dimension_values_comparison(
                left,
                right,
                ours=ours,
                theirs=theirs,
            )
            state = (
                "MATCH"
                if dimension_result is True
                else "CONFLICT"
                if dimension_result is False
                else "UNKNOWN"
            )
        elif _taxonomy_conflict_is_ambiguous(dimension, left, right):
            state = "UNKNOWN"
        elif set(left) & set(right):
            state = "MATCH"
        else:
            state = "CONFLICT"
        comparisons[dimension] = {
            "state": state,
            "our_values": list(left),
            "candidate_values": list(right),
        }
        if ambiguous_source_values:
            comparisons[dimension]["source_values_ambiguous"] = True
        if state == "CONFLICT" and conflict_is_hard:
            conflicts.append(
                {
                    "dimension": dimension,
                    "our_value": ", ".join(left),
                    "candidate_value": ", ".join(right),
                    "explanation": (
                        f"Deterministic semantic extraction found conflicting {dimension}."
                    ),
                }
            )

    compare("part_type", our_key="part_family", candidate_key="part_family")
    compare("domain")
    compare("vehicle_make", conflict_is_hard=False)
    compare("vehicle_model", conflict_is_hard=False)
    compare("vehicle_platform", conflict_is_hard=False)
    compare("vehicle_generation_hint", conflict_is_hard=False)
    compare("part_subtype")
    sliding_door_wording_is_ambiguous = (
        set(ours["part_subtype"].values) | set(theirs["part_subtype"].values)
    ) == {"sliding_door_roller", "sliding_door_bracket"}
    compare(
        "assembly_level",
        conflict_is_hard=not sliding_door_wording_is_ambiguous,
    )
    compare("condition")
    compare("serviceability")
    compare("side")
    compare("position")
    compare("vertical_position")
    compare("cv_joint_variant")
    compare("fuel_type")
    compare("body_variant")
    compare("climate_variant")
    common_families = set(ours["part_family"].values) & set(
        theirs["part_family"].values
    )
    compare(
        "transmission_variant",
        conflict_is_hard="radiator" in common_families,
    )
    compare(
        "core_construction",
        conflict_is_hard="radiator" in common_families,
    )
    compare(
        "engine_cylinder_count",
        conflict_is_hard="engine_bearing" in common_families,
    )
    compare(
        "power_rating",
        conflict_is_hard="starting_system" in common_families,
    )
    compare("connectors_pins", our_key="pin_count", candidate_key="pin_count")
    compare("technical_specs", our_key="dimensions", candidate_key="dimensions")
    compare("opening_temperature")
    compare("operating_pressure")
    compare("housing")
    compare(
        "inlet_outlet", our_key="ports", candidate_key="ports", conflict_is_hard=False
    )
    compare("ports", conflict_is_hard=False)
    compare("mounting", conflict_is_hard=False)
    # Explicit with/without-component conflicts may preserve base identity but
    # never the sellable package or its price.  They are commercial hard stops:
    # downstream returns MANUAL_REVIEW/EXCLUDED rather than identity NOT_MATCH.
    compare("included_components")
    compare(
        "engine",
        conflict_is_hard=_engine_conflict_is_hard(ours, theirs),
    )
    compare("year_interval", conflict_is_hard=False)
    # Commercial conflicts do not disprove physical identity, but must stop a
    # price cohort until normalized.
    compare("package_quantity")
    compare("unit_basis")

    part_family = _single_common_or_known(ours["part_family"], theirs["part_family"])
    required = list(_ANALOGUE_REQUIRED.get(part_family or "", ("part_type",)))
    seed_asserted_dimensions: list[str] = []
    candidate_asserted_dimensions: list[str] = []
    for seed_feature, comparison_dimension in _SEED_ASSERTED_ANALOGUE_REQUIRED:
        if ours[seed_feature].values:
            if comparison_dimension in _EXACT_SEED_ASSERTED_REQUIRED:
                seed_asserted_dimensions.append(comparison_dimension)
            if comparison_dimension not in required:
                required.append(comparison_dimension)
        if (
            theirs[seed_feature].values
            and comparison_dimension in _EXACT_SEED_ASSERTED_REQUIRED
        ):
            candidate_asserted_dimensions.append(comparison_dimension)
    common_subtypes = set(ours["part_subtype"].values) & set(
        theirs["part_subtype"].values
    )
    if "fuel_filter" in common_subtypes and "operating_pressure" not in required:
        required.append("operating_pressure")
    return {
        "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
        "our_product": {key: value.as_dict() for key, value in ours.items()},
        "candidate": {key: value.as_dict() for key, value in theirs.items()},
        "comparisons": comparisons,
        "hard_stop_conflicts": conflicts,
        "analogue_required_dimensions": required,
        # This is deliberately separate from analogue_required_dimensions:
        # exact-OE matches must not invent category-specific analogue facts,
        # but they still must preserve commercial facts explicitly asserted by
        # the owned seed.  The admission layer uses this list for both exact
        # and cross-OE pricing paths.
        "seed_asserted_dimensions": seed_asserted_dimensions,
        # A candidate-only assertion is also evidence: if the seed does not
        # carry the same fact, pricing must remain manual rather than treating
        # the candidate's richer title as proof of equivalence.
        "candidate_asserted_dimensions": candidate_asserted_dimensions,
        "missing_semantics": "UNKNOWN",
        "positive_similarity_is_identity_proof": False,
    }


def ambiguous_taxonomy_conflicts(
    matrix: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return explicit taxonomy ambiguities that must stay out of pricing.

    The extractor intentionally reports a small set of catalogue-language
    collisions as ``UNKNOWN`` rather than as a hard identity contradiction.
    That is the correct identity result, but it is not sufficient evidence for
    a price cohort. This second admission-level view preserves the listing for
    review while requiring stronger evidence to resolve the subtype.
    """

    comparisons = matrix.get("comparisons")
    if not isinstance(comparisons, Mapping):
        return []
    result: list[dict[str, str]] = []
    for dimension, comparison in comparisons.items():
        if not isinstance(comparison, Mapping) or comparison.get("state") != "UNKNOWN":
            continue
        left = comparison.get("our_values")
        right = comparison.get("candidate_values")
        if not isinstance(left, (list, tuple)) or not isinstance(
            right, (list, tuple)
        ):
            continue
        left_values = tuple(str(value) for value in left if str(value).strip())
        right_values = tuple(str(value) for value in right if str(value).strip())
        if not _taxonomy_conflict_is_ambiguous(dimension, left_values, right_values):
            continue
        result.append(
            {
                "dimension": str(dimension),
                "our_value": ", ".join(left_values),
                "candidate_value": ", ".join(right_values),
                "explanation": (
                    "Deterministic taxonomy marks this wording as ambiguous; "
                    "it is visible for review but not admitted to pricing."
                ),
            }
        )
    return result


def extract_semantic_features(record: Mapping[str, Any]) -> dict[str, FeatureSet]:
    """Extract a closed set of review facts from one product record."""

    flattened = _flatten_record(record)
    sources = _text_sources(flattened)
    combined = "\n".join(value for _, value in sources)
    normalized = _normalize_text(combined)
    engine_sources = [item for item in sources if item[0] != "category"]
    engine_text = _normalize_text("\n".join(value for _, value in engine_sources))
    values: dict[str, list[FeatureEvidence]] = {
        name: []
        for name in (
            "part_family",
            "part_subtype",
            "assembly_level",
            "serviceability",
            "side",
            "position",
            "vertical_position",
            "cv_joint_variant",
            "fuel_type",
            "body_variant",
            "pin_count",
            "dimensions",
            "opening_temperature",
            "package_quantity",
            "unit_basis",
            "included_components",
            "ports",
            "mounting",
            "housing",
            "year_interval",
            "engine",
            "condition",
            "availability",
            "climate_variant",
            "transmission_variant",
            "core_construction",
            "engine_cylinder_count",
            "power_rating",
            "operating_pressure",
            "domain",
            "vehicle_make",
            "vehicle_model",
            "vehicle_platform",
            "vehicle_generation_hint",
        )
    }

    # Product identity in an explicit title/name outranks a broad marketplace
    # category and marketing description.  Searching one concatenated blob
    # allowed e.g. a precise "timing-belt roller" title to be reclassified as
    # a wheel bearing solely because its category was "Bearings / Hubs".
    # Category and description remain conservative fallbacks when the title is
    # genuinely silent.
    part_source_tiers = (
        tuple(item for item in sources if item[0] in {"name", "title"}),
        tuple(item for item in sources if item[0] == "category"),
        tuple(item for item in sources if item[0] == "description"),
        tuple(item for item in sources if item[0] in {"fitment", "engine"}),
    )
    part_found = False
    for tier_sources in part_source_tiers:
        if not tier_sources:
            continue
        tier_text = _normalize_text("\n".join(value for _, value in tier_sources))
        for family, subtype, assembly, patterns in _PART_PATTERNS:
            match = _first_match(patterns, tier_text)
            if match is None:
                continue
            source_field = _source_for_excerpt(match.group(0), tier_sources)
            _append(values, "part_family", family, source_field, match.group(0))
            _append(values, "part_subtype", subtype, source_field, match.group(0))
            _append(values, "assembly_level", assembly, source_field, match.group(0))
            part_found = True
            break
        if (
            not part_found
            and _first_match(_AUTOMOTIVE_CONTEXT_PATTERNS, tier_text) is not None
        ):
            for (
                family,
                subtype,
                assembly,
                patterns,
            ) in _AUTOMOTIVE_GENERIC_PART_PATTERNS:
                match = _first_match(patterns, tier_text)
                if match is None:
                    continue
                source_field = _source_for_excerpt(match.group(0), tier_sources)
                _append(values, "part_family", family, source_field, match.group(0))
                _append(values, "part_subtype", subtype, source_field, match.group(0))
                _append(
                    values,
                    "assembly_level",
                    assembly,
                    source_field,
                    match.group(0),
                )
                part_found = True
                break
        if part_found:
            break

    # Inner and outer CV joints share the same broad family but are not the
    # same sellable part. Keep this separate from front/rear installation
    # position: a title may truthfully assert both without making either fact
    # ambiguous.
    if "cv_joint" in {item.normalized_value for item in values["part_family"]}:
        for variant, patterns in _CV_JOINT_VARIANT_PATTERNS.items():
            match = _first_match(patterns, normalized)
            if match is not None:
                _append(
                    values,
                    "cv_joint_variant",
                    variant,
                    _source_for_excerpt(match.group(0), sources),
                    match.group(0),
                )

    non_automotive = _first_match(_NON_AUTOMOTIVE_PATTERNS, normalized)
    if non_automotive is not None:
        _append(
            values,
            "domain",
            "non_automotive",
            _source_for_excerpt(non_automotive.group(0), sources),
            non_automotive.group(0),
        )
    elif (
        values["part_family"]
        or (automotive := _first_match(_AUTOMOTIVE_CONTEXT_PATTERNS, normalized))
        is not None
    ):
        excerpt = (
            values["part_family"][0].excerpt
            if values["part_family"]
            else automotive.group(0)
        )
        _append(
            values,
            "domain",
            "automotive",
            _source_for_excerpt(excerpt, sources),
            excerpt,
        )

    for make, patterns in _VEHICLE_MAKE_PATTERNS.items():
        match = _first_match(patterns, normalized)
        if match is not None:
            _append(
                values,
                "vehicle_make",
                make,
                _source_for_excerpt(match.group(0), sources),
                match.group(0),
            )

    detected_makes = {item.normalized_value for item in values["vehicle_make"]}
    for make in sorted(detected_makes):
        for model, patterns in _VEHICLE_MODEL_PATTERNS.get(make, {}).items():
            match = _first_match(patterns, normalized)
            if match is None:
                continue
            canonical_model = f"{make}:{model}"
            _append(
                values,
                "vehicle_model",
                canonical_model,
                _source_for_excerpt(match.group(0), sources),
                match.group(0),
            )

    detected_models = {item.normalized_value for item in values["vehicle_model"]}
    for model_evidence in values["vehicle_model"]:
        platform = _VEHICLE_PLATFORM_BY_MODEL.get(model_evidence.normalized_value)
        if platform is not None:
            _append(
                values,
                "vehicle_platform",
                platform,
                model_evidence.source_field,
                model_evidence.excerpt,
            )
    for canonical_model in sorted(detected_models):
        generation_patterns = _VEHICLE_GENERATION_HINT_PATTERNS.get(canonical_model, {})
        for generation, patterns in generation_patterns.items():
            match = _first_match(patterns, normalized)
            if match is None:
                continue
            _append(
                values,
                "vehicle_generation_hint",
                f"{canonical_model}:{generation}",
                _source_for_excerpt(match.group(0), sources),
                match.group(0),
            )

    for feature, patterns_by_value in (
        ("side", _SIDE_PATTERNS),
        ("position", _POSITION_PATTERNS),
        ("vertical_position", _VERTICAL_POSITION_PATTERNS),
        ("condition", _CONDITION_PATTERNS),
    ):
        for feature_value, patterns in patterns_by_value.items():
            match = _first_match(patterns, normalized)
            if match is not None:
                _append(
                    values,
                    feature,
                    feature_value,
                    _source_for_excerpt(match.group(0), sources),
                    match.group(0),
                )

    for fuel_value, patterns in _FUEL_TYPE_PATTERNS.items():
        match = _first_match(patterns, normalized)
        if match is not None:
            _append(
                values,
                "fuel_type",
                fuel_value,
                _source_for_excerpt(match.group(0), sources),
                match.group(0),
            )

    explicit_fuel, fuel_source = _first_explicit_value(
        flattened,
        ("fuel_type", "fuelType", "fuel", "fuel_type_raw"),
    )
    if explicit_fuel is not None:
        normalized_fuel = _normalize_text(str(explicit_fuel))
        for fuel_value, patterns in _FUEL_TYPE_PATTERNS.items():
            if _first_match(patterns, normalized_fuel) is not None:
                _append(
                    values,
                    "fuel_type",
                    fuel_value,
                    fuel_source,
                    str(explicit_fuel),
                )

    for feature, aliases, patterns_by_value in (
        ("side", ("side",), _SIDE_PATTERNS),
        ("position", ("position", "axle"), _POSITION_PATTERNS),
        (
            "vertical_position",
            ("vertical_position", "verticalPosition", "mounting_position"),
            _VERTICAL_POSITION_PATTERNS,
        ),
    ):
        raw_value, source_field = _first_explicit_value(flattened, aliases)
        if raw_value is None:
            continue
        normalized_value = (
            _normalize_text(str(raw_value)).replace("_", " ").replace("-", " ")
        )
        for feature_value, patterns in patterns_by_value.items():
            if _first_match(patterns, normalized_value) is not None:
                _append(
                    values,
                    feature,
                    feature_value,
                    source_field,
                    str(raw_value),
                )

    explicit_body, body_source = _first_explicit_value(
        flattened,
        ("body_variant", "bodyVariant", "body_type", "bodyType"),
    )
    normalized_body = _normalize_body_variant(explicit_body)
    if normalized_body is not None:
        _append(
            values,
            "body_variant",
            normalized_body,
            body_source,
            str(explicit_body),
        )

    explicit_condition = _normalize_text(str(flattened.get("condition") or ""))
    normalized_condition = _normalize_condition_value(explicit_condition)
    if normalized_condition is not None:
        _append(
            values,
            "condition",
            normalized_condition,
            "condition",
            explicit_condition,
        )

    # A negative phrase contains the positive adjective as a substring, so it
    # must win before the positive pattern is considered.  Recording both would
    # turn an explicit fact into a self-contradictory feature set.
    non_serviceable = _first_match(
        _SERVICEABILITY_PATTERNS["non_serviceable"], normalized
    )
    if non_serviceable is not None:
        _append(
            values,
            "serviceability",
            "non_serviceable",
            _source_for_excerpt(non_serviceable.group(0), sources),
            non_serviceable.group(0),
        )
    else:
        serviceable = _first_match(_SERVICEABILITY_PATTERNS["serviceable"], normalized)
        if serviceable is not None:
            _append(
                values,
                "serviceability",
                "serviceable",
                _source_for_excerpt(serviceable.group(0), sources),
                serviceable.group(0),
            )

    for component_value, patterns in _INCLUDED_COMPONENT_PATTERNS.items():
        match = _first_match(patterns, normalized)
        if match is not None:
            _append(
                values,
                "included_components",
                component_value,
                _source_for_excerpt(match.group(0), sources),
                match.group(0),
            )

    # ``AC+/-`` explicitly means that both variants are applicable.  Treating it
    # as either side of the binary would manufacture a conflict, so ambiguous
    # notation remains UNKNOWN.
    if not re.search(r"(?<![a-zа-я])(?:a/?c|ас)\s*\+\s*/\s*-", normalized):
        for feature_value, patterns in _CLIMATE_VARIANT_PATTERNS.items():
            match = _first_match(patterns, normalized)
            if match is not None:
                _append(
                    values,
                    "climate_variant",
                    feature_value,
                    _source_for_excerpt(match.group(0), sources),
                    match.group(0),
                )

    for feature, patterns_by_value in (
        ("transmission_variant", _TRANSMISSION_VARIANT_PATTERNS),
        ("core_construction", _CORE_CONSTRUCTION_PATTERNS),
    ):
        for feature_value, patterns in patterns_by_value.items():
            match = _first_match(patterns, normalized)
            if match is not None:
                _append(
                    values,
                    feature,
                    feature_value,
                    _source_for_excerpt(match.group(0), sources),
                    match.group(0),
                )

    for match in _DIMENSIONS_RE.finditer(normalized):
        parts = [int(value) for value in match.groups() if value]
        _append(
            values,
            "dimensions",
            _normalize_dimensions(parts),
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )
    # A brake-disc title frequently gives only the nominal diameter (for
    # example ``256mm``).  It is physical identity evidence, not an arbitrary
    # number, so extract it only after the title was typed as a brake disc.
    if "brake_disc" in {item.normalized_value for item in values["part_subtype"]}:
        for match in _BRAKE_DISC_DIAMETER_RE.finditer(normalized):
            raw_diameter = next((group for group in match.groups() if group), None)
            if raw_diameter is None:
                continue
            _append(
                values,
                "dimensions",
                f"{int(raw_diameter)}mm",
                _source_for_excerpt(match.group(0), sources),
                match.group(0),
            )
    for match in _PIN_RE.finditer(normalized):
        _append(
            values,
            "pin_count",
            str(int(match.group(1))),
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )
    for match in _PACKAGE_RE.finditer(normalized):
        source_field = _source_for_excerpt(match.group(0), sources)
        package_quantity = int(match.group(1))
        _append(
            values,
            "package_quantity",
            str(package_quantity),
            source_field,
            match.group(0),
        )
        if package_quantity == 1:
            _append(values, "unit_basis", "piece", source_field, match.group(0))

    explicit_quantity, quantity_source = _first_explicit_value(
        flattened,
        ("package_quantity", "packageQuantity"),
    )
    normalized_quantity = _normalize_package_quantity(explicit_quantity)
    if normalized_quantity is not None:
        _append(
            values,
            "package_quantity",
            normalized_quantity,
            quantity_source,
            str(explicit_quantity),
        )
    for match in _OPENING_TEMP_RE.finditer(normalized):
        _append(
            values,
            "opening_temperature",
            match.group(1) + "c",
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )
    for match in _YEAR_RANGE_RE.finditer(normalized):
        _append(
            values,
            "year_interval",
            f"{match.group(1)}-{match.group(2)}",
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )
    for match in _SHORT_YEAR_RANGE_RE.finditer(normalized):
        interval = _normalize_short_year_interval(match.group(1), match.group(2))
        if interval is None:
            continue
        _append(
            values,
            "year_interval",
            interval,
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )

    explicit_year_from, year_from_source = _first_explicit_value(
        flattened,
        ("year_from", "yearFrom"),
    )
    explicit_year_to, year_to_source = _first_explicit_value(
        flattened,
        ("year_to", "yearTo"),
    )
    normalized_year_from = _normalize_year(explicit_year_from)
    normalized_year_to = _normalize_year(explicit_year_to)
    if normalized_year_from is not None and normalized_year_to is not None:
        start, end = sorted((normalized_year_from, normalized_year_to))
        _append(
            values,
            "year_interval",
            f"{start}-{end}",
            f"{year_from_source}+{year_to_source}",
            f"{explicit_year_from}-{explicit_year_to}",
        )
    for match in _ENGINE_RE.finditer(engine_text):
        suffix = (match.group(2) or "").upper()
        _append(
            values,
            "engine",
            match.group(1).replace(",", ".") + suffix,
            _source_for_excerpt(match.group(0), engine_sources),
            match.group(0),
        )
    for match in _ENGINE_CYLINDER_COUNT_RE.finditer(engine_text):
        _append(
            values,
            "engine_cylinder_count",
            match.group(1),
            _source_for_excerpt(match.group(0), engine_sources),
            match.group(0),
        )
    for match in _POWER_RATING_RE.finditer(normalized):
        _append(
            values,
            "power_rating",
            match.group(1).replace(",", ".") + "kw",
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )
    for match in _OPERATING_PRESSURE_RE.finditer(normalized):
        _append(
            values,
            "operating_pressure",
            match.group(1).replace(",", ".") + "bar",
            _source_for_excerpt(match.group(0), sources),
            match.group(0),
        )

    if re.search(r"\b(?:в\s+зборі|в\s+сборе|complete\s+assembly)\b", normalized):
        _append(
            values,
            "included_components",
            "complete_assembly",
            "text",
            "assembly phrase",
        )
    if re.search(r"\b(?:комплект|kit|set)\b", normalized):
        _append(values, "unit_basis", "set", "text", "set phrase")
    if re.search(r"\b(?:пара|pair)\b", normalized):
        _append(values, "unit_basis", "pair", "text", "pair phrase")
    if re.search(r"\b(?:без\s+корпуса|without\s+housing)\b", normalized):
        _append(values, "housing", "without_housing", "text", "without housing")
    elif re.search(r"\b(?:з\s+корпусом|с\s+корпусом|with\s+housing)\b", normalized):
        _append(values, "housing", "with_housing", "text", "with housing")

    explicit_unit, unit_source = _first_explicit_value(
        flattened,
        ("unit_basis", "unitBasis", "measure_unit", "measureUnit"),
    )
    measure_unit = str(explicit_unit or "").strip().casefold()
    if measure_unit:
        unit = _normalize_unit_basis(measure_unit)
        explicit_package_basis = {
            item.normalized_value for item in values["unit_basis"]
        } & {"set", "pair"}
        # Marketplace ``шт.`` describes one listing unit and does not disprove
        # an explicit title saying that the listing unit is a set or pair.
        # Keeping both values would make ``piece`` intersect a true single-part
        # offer and incorrectly erase the commercial conflict.
        if unit and not (unit == "piece" and explicit_package_basis):
            _append(values, "unit_basis", unit, unit_source, measure_unit)

    _canonicalize_unit_basis_evidence(values)

    explicit_available = flattened.get("is_available")
    if isinstance(explicit_available, bool):
        _append(
            values,
            "availability",
            "available" if explicit_available else "unavailable",
            "is_available",
            str(explicit_available),
        )
    else:
        presence = _normalize_text(str(flattened.get("presence") or ""))
        if presence in {"available", "in stock", "в наличии", "в наявності"}:
            _append(values, "availability", "available", "presence", presence)
        elif presence in {
            "unavailable",
            "out of stock",
            "нет в наличии",
            "немає в наявності",
        }:
            _append(values, "availability", "unavailable", "presence", presence)

    for label, raw_value in _characteristics(flattened.get("characteristics")):
        normalized_label = _normalize_text(label)
        feature = next(
            (
                name
                for name, markers in _CHARACTERISTIC_LABELS.items()
                if any(marker in normalized_label for marker in markers)
            ),
            None,
        )
        if feature is None:
            continue
        normalized_value = _normalize_text(str(raw_value))
        if not normalized_value:
            continue
        if feature == "dimensions" and any(
            marker in normalized_label
            for marker in ("упаков", "пакув", "package", "shipping", "транспорт")
        ):
            # Parcel dimensions describe logistics, not the physical part.
            # Treating ``Висота упаковки: 270`` as radiator geometry created a
            # false hard stop against the seed's real ``680x278`` core size.
            continue
        if feature == "opening_temperature":
            match = _OPENING_TEMP_RE.search(normalized_value)
            if match:
                normalized_value = match.group(1) + "c"
        elif feature == "operating_pressure":
            match = _OPERATING_PRESSURE_RE.search(normalized_value)
            if match:
                normalized_value = match.group(1).replace(",", ".") + "bar"
            elif re.fullmatch(r"\d{1,2}(?:[.,]\d{1,2})?", normalized_value):
                normalized_value = normalized_value.replace(",", ".") + "bar"
            else:
                continue
        elif feature == "dimensions":
            match = _DIMENSIONS_RE.search(normalized_value)
            if match:
                normalized_value = _normalize_dimensions(
                    [int(part) for part in match.groups() if part]
                )
            elif single_dimension := _SINGLE_DIMENSION_RE.fullmatch(normalized_value):
                normalized_value = f"{int(single_dimension.group(1))}mm"
            else:
                # A label containing a broad marker such as ``size`` is not
                # sufficient to turn arbitrary text into comparable geometry.
                continue
        elif feature == "condition":
            condition_value = _normalize_condition_value(normalized_value)
            if condition_value is None:
                continue
            normalized_value = condition_value
        elif feature == "package_quantity":
            match = re.search(r"(?<!\d)(\d{1,3})(?:[.,]0+)?(?!\d)", normalized_value)
            if match is None:
                continue
            normalized_value = str(int(match.group(1)))
        elif feature == "unit_basis":
            unit = _normalize_unit_basis(normalized_value)
            if unit is None:
                continue
            normalized_value = unit
        elif feature in {"side", "position"}:
            patterns_by_value = (
                _SIDE_PATTERNS if feature == "side" else _POSITION_PATTERNS
            )
            matched_values = [
                feature_value
                for feature_value, patterns in patterns_by_value.items()
                if _first_match(patterns, normalized_value) is not None
            ]
            for matched_value in matched_values:
                _append(
                    values,
                    feature,
                    matched_value,
                    f"characteristics.{label}",
                    str(raw_value),
                )
            continue
        _append(
            values,
            feature,
            normalized_value,
            f"characteristics.{label}",
            str(raw_value),
        )

    # A listing sold per piece is a listing of one piece.  Owner decision
    # 2026-08-15: ``unit_basis = piece`` establishes ``package_quantity = 1``.
    #
    # Neither our catalogue nor the marketplace ever states a pack size --
    # UNKNOWN on both sides in nine comparisons out of nine -- so while
    # ``package_quantity`` sits in SEMANTIC_PRICING_BASE_REQUIRED_DIMENSIONS no
    # offer can ever be admitted to a price.  The unit basis already carries the
    # fact that requirement protects: two prices are comparable when both are
    # per piece.
    #
    # Runs last, after both the explicit-field pass and the characteristics
    # pass, so it sees the final unit basis whichever source stated it.
    # ``_canonicalize_unit_basis_evidence`` has already stripped ``piece`` from
    # anything that is really a ``комплект`` or a ``пара``, so a kit never
    # reaches here and is never priced as one part.  An explicit pack size
    # always wins; this only fills a blank.
    if not values["package_quantity"] and {
        item.normalized_value for item in values["unit_basis"]
    } == {"piece"}:
        _append(values, "package_quantity", "1", "unit_basis", "piece")

    # Side, axle position and condition describe one sellable variant.  Old
    # marketplace descriptions are often templates containing both sides or
    # another product variant.  They must not contaminate an explicit title or
    # a structured characteristic.  At the same time, disagreement *within*
    # the primary tier (e.g. title says right while parser field says left)
    # remains visible as ambiguous evidence and therefore fails closed.
    for feature in ("side", "position", "condition"):
        evidence = values[feature]
        if not evidence:
            continue
        best_priority = min(_variant_evidence_priority(item) for item in evidence)
        values[feature] = [
            item
            for item in evidence
            if _variant_evidence_priority(item) == best_priority
        ]

    # Diagnostic fitment benefits from description fallback, but a generic SEO
    # template must not expand an explicit title/fitment into unrelated makes
    # or models.  Retain all facts within the best available provenance tier so
    # genuine multi-model and cross-platform titles remain intact.
    for feature in (
        "vehicle_make",
        "vehicle_model",
        "vehicle_platform",
        "vehicle_generation_hint",
    ):
        evidence = values[feature]
        if not evidence:
            continue
        best_priority = min(_fitment_evidence_priority(item) for item in evidence)
        values[feature] = [
            item
            for item in evidence
            if _fitment_evidence_priority(item) == best_priority
        ]

    return {
        name: FeatureSet(
            values=tuple(dict.fromkeys(item.normalized_value for item in evidence)),
            evidence=tuple(_deduplicate_evidence(evidence)),
        )
        for name, evidence in values.items()
    }


def _flatten_record(record: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    product = record.get("product")
    if isinstance(product, Mapping):
        result.update(product)
    result.update({key: value for key, value in record.items() if key != "product"})
    return result


def _text_sources(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for key in ("name", "title", "category", "description", "fitment", "engine"):
        value = record.get(key)
        if value is not None and str(value).strip():
            result.append((key, str(value).strip()))
    return result


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(value.replace("\u00a0", " ").split())


def _first_match(patterns: Sequence[str], text: str) -> re.Match[str] | None:
    for pattern in patterns:
        match = _compiled_pattern(pattern).search(text)
        if match is not None:
            return match
    return None


@lru_cache(maxsize=None)
def _compiled_pattern(pattern: str) -> re.Pattern[str]:
    """Compile the closed extractor vocabulary once instead of thrashing re's cache."""

    return re.compile(pattern, re.IGNORECASE)


def _source_for_excerpt(excerpt: str, sources: Sequence[tuple[str, str]]) -> str:
    needle = _normalize_text(excerpt)
    for source_field, source_value in sources:
        if needle and needle in _normalize_text(source_value):
            return source_field
    return "combined_text"


def _append(
    values: dict[str, list[FeatureEvidence]],
    feature: str,
    normalized_value: str,
    source_field: str,
    excerpt: str,
) -> None:
    normalized_value = _normalize_text(normalized_value)
    if not normalized_value:
        return
    values[feature].append(
        FeatureEvidence(
            value=excerpt[:240],
            normalized_value=normalized_value[:120],
            source_field=source_field[:160],
            excerpt=excerpt[:240],
        )
    )


def _normalize_unit_basis(value: str) -> str | None:
    compact = re.sub(r"[^a-zа-яіїє]", "", value.casefold())
    if compact in {"шт", "штука", "штуки", "piece", "pieces", "pcs", "unit"}:
        return "piece"
    if compact in {"комплект", "kit", "set"}:
        return "set"
    if compact in {"пара", "pair"}:
        return "pair"
    return None


def _canonicalize_unit_basis_evidence(
    values: dict[str, list[FeatureEvidence]],
) -> None:
    """Separate package cardinality from the listing's commercial unit."""

    evidence = values["unit_basis"]
    normalized = {item.normalized_value for item in evidence}
    if normalized & {"set", "pair"}:
        # Marketplace ``шт.`` and title ``N шт.`` describe the elements
        # inside a package; they do not turn that package into a per-piece offer.
        evidence = [item for item in evidence if item.normalized_value != "piece"]
    if "pair" in {item.normalized_value for item in evidence}:
        # ``комплект`` is a generic noun; an explicit pair is its more
        # precise two-item commercial basis, not a contradictory second unit.
        evidence = [item for item in evidence if item.normalized_value != "set"]
    values["unit_basis"] = evidence


def _variant_evidence_priority(evidence: FeatureEvidence) -> int:
    """Rank provenance tiers without hiding primary-source contradictions."""

    source = evidence.source_field.casefold()
    if source in {
        "name",
        "title",
        "side",
        "position",
        "axle",
        "condition",
        "condition_raw",
        "conditionraw",
    } or source.startswith("characteristics."):
        return 0
    if source in {"fitment", "engine"}:
        return 1
    if source == "description":
        return 2
    if source == "category":
        return 3
    return 4


def _fitment_evidence_priority(evidence: FeatureEvidence) -> int:
    """Prefer explicit product/fitment sources over marketplace SEO prose."""

    source = evidence.source_field.casefold()
    if source in {"name", "title", "fitment", "engine"}:
        return 0
    if source.startswith("characteristics."):
        return 0
    if source == "description":
        return 1
    if source == "category":
        return 2
    return 3


def _first_explicit_value(
    record: Mapping[str, Any], aliases: Sequence[str]
) -> tuple[Any | None, str]:
    for alias in aliases:
        value = record.get(alias)
        if value is not None and str(value).strip():
            return value, alias
    return None, aliases[0]


def _normalize_package_quantity(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = _normalize_text(str(value)).replace(",", ".")
    match = re.fullmatch(r"(?:qty\s*[:=]?\s*)?(\d{1,3})(?:\.0+)?", text)
    if match is None:
        return None
    quantity = int(match.group(1))
    return str(quantity) if quantity > 0 else None


def _normalize_year(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    match = re.fullmatch(r"\s*((?:19|20)\d{2})(?:\.0+)?\s*", str(value))
    return int(match.group(1)) if match is not None else None


def _normalize_short_year_interval(start_raw: str, end_raw: str) -> str | None:
    """Expand compact catalogue years while rejecting codes and implausible spans."""

    def expand(raw: str) -> int:
        value = int(raw)
        return 2000 + value if value <= 40 else 1900 + value

    start = expand(start_raw)
    end = expand(end_raw)
    if start < 1950 or end < start or end > 2040 or end - start > 35:
        return None
    return f"{start}-{end}"


def _year_intervals_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    def parse(value: str) -> tuple[int, int] | None:
        match = re.fullmatch(r"((?:19|20)\d{2})-((?:19|20)\d{2})", value)
        if match is None:
            return None
        start, end = int(match.group(1)), int(match.group(2))
        return (min(start, end), max(start, end))

    return any(
        max(left_interval[0], right_interval[0])
        <= min(left_interval[1], right_interval[1])
        for left_value in left
        if (left_interval := parse(left_value)) is not None
        for right_value in right
        if (right_interval := parse(right_value)) is not None
    )


def _normalize_body_variant(value: Any) -> str | None:
    if value is None:
        return None
    normalized = (
        _normalize_text(str(value)).replace("_", " ").replace("-", " ")
    ).strip(" .,:;/")
    return _BODY_VARIANT_ALIASES.get(normalized)


def _normalize_condition_value(value: str) -> str | None:
    normalized = _normalize_text(value)
    if normalized in {
        "new",
        "новий",
        "новая",
        "новое",
        "новый",
        "нове",
    }:
        return "new"
    if normalized in {
        "used",
        "б/у",
        "б у",
        "вживаний",
        "вживана",
        "вживане",
        "вживаний товар",
    }:
        return "used"
    if normalized in {
        "damaged",
        "пошкоджений",
        "пошкоджена",
        "пошкоджене",
    }:
        return "damaged"
    for condition_value, patterns in _CONDITION_PATTERNS.items():
        if _first_match(patterns, normalized) is not None:
            return condition_value
    return None


def _normalize_dimensions(parts: Sequence[int]) -> str:
    """Canonicalize unnamed dimensions without pretending orientation is known.

    Marketplace titles commonly swap width and height (``652x415`` versus
    ``415x652``).  They are the same unordered physical measurements unless a
    structured characteristic names the axes, which this extractor does not
    currently have.  Sorting prevents a false deterministic contradiction.
    """

    return "x".join(str(value) for value in sorted(parts)) + "mm"


def _dimension_values_comparison(
    left: Sequence[str],
    right: Sequence[str],
    *,
    ours: Mapping[str, FeatureSet],
    theirs: Mapping[str, FeatureSet],
) -> bool | None:
    """Compare geometry, returning ``None`` when the evidence is incomplete.

    Prom titles frequently omit radiator thickness and suppliers disagree by a
    few millimetres on fin/core versus overall dimensions.  Precision bearing
    catalogues also round the final thickness by one millimetre.  Exact string
    comparison created false hard stops in both real saved cases.  The
    tolerance is deliberately category-bound and still rejects materially
    different geometry.
    """

    common_families = set(ours["part_family"].values) & set(
        theirs["part_family"].values
    )
    if "radiator" in common_families:
        absolute_tolerance = 20
        relative_tolerance = 0.05
    elif "wheel_bearing" in common_families:
        absolute_tolerance = 1
        relative_tolerance = 0.0
    else:
        absolute_tolerance = 1
        relative_tolerance = 0.01

    left_sequences = _dimension_sequences(left)
    right_sequences = _dimension_sequences(right)
    comparable = False
    for left_parts in left_sequences:
        for right_parts in right_sequences:
            # One anonymous scalar cannot disprove or prove a multi-axis part.
            # Multiple axis-labelled scalar characteristics are combined by
            # ``_dimension_sequences`` before reaching this branch.
            if (len(left_parts) == 1) != (len(right_parts) == 1):
                continue
            if abs(len(left_parts) - len(right_parts)) > 1:
                continue
            comparable = True
            if _dimension_sequences_compatible(
                left_parts,
                right_parts,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            ):
                return True
    return False if comparable else None


def _has_multiple_geometry_vectors(values: Sequence[str]) -> bool:
    """Return whether one source advertises multiple complete geometries.

    Structured length/width/depth fields arrive as several scalar values and
    are intentionally assembled into one vector by ``_dimension_sequences``.
    A second full vector, however, represents an alternative sellable variant
    and must not be rescued by a partial intersection.
    """

    return sum(len(parts) >= 2 for parts in _dimension_sequences(values)) >= 2


def _dimension_values_compatible(
    left: Sequence[str],
    right: Sequence[str],
    *,
    ours: Mapping[str, FeatureSet],
    theirs: Mapping[str, FeatureSet],
) -> bool:
    """Backward-compatible boolean helper for callers outside the matrix."""

    return (
        _dimension_values_comparison(
            left,
            right,
            ours=ours,
            theirs=theirs,
        )
        is True
    )


def _dimension_sequences(values: Sequence[str]) -> tuple[tuple[int, ...], ...]:
    parsed = tuple(
        parts for value in values if (parts := _parse_normalized_dimensions(value))
    )
    vectors = [parts for parts in parsed if len(parts) >= 2]
    scalars = sorted({parts[0] for parts in parsed if len(parts) == 1})
    if len(scalars) >= 2:
        vectors.append(tuple(scalars))
    elif len(scalars) == 1 and not vectors:
        vectors.append((scalars[0],))
    return tuple(dict.fromkeys(vectors))


def _parse_normalized_dimensions(value: str) -> tuple[int, ...]:
    if not value.endswith("mm"):
        return ()
    try:
        return tuple(int(part) for part in value[:-2].split("x"))
    except ValueError:
        return ()


def _dimension_sequences_compatible(
    left: Sequence[int],
    right: Sequence[int],
    *,
    absolute_tolerance: int,
    relative_tolerance: float,
) -> bool:
    smaller, larger = (left, right) if len(left) <= len(right) else (right, left)
    # At most one omitted measurement is tolerated (normally thickness).
    if len(larger) - len(smaller) > 1:
        return False
    for candidate in combinations(larger, len(smaller)):
        if all(
            abs(a - b) <= max(absolute_tolerance, round(max(a, b) * relative_tolerance))
            for a, b in zip(smaller, candidate, strict=True)
        ):
            return True
    return False


def _engine_conflict_is_hard(
    ours: Mapping[str, FeatureSet],
    theirs: Mapping[str, FeatureSet],
) -> bool:
    """Allow only narrow, category-aware engine contradictions to hard-stop.

    Different titles often list different *subsets* of a broad fitment, so a
    generic non-overlap is not disproof.  A single explicit displacement on
    each side is decisive for high-variant components where the saved Prom
    benchmark contains real false matches: radiators, thermostats and engine
    gaskets.  Multi-engine lists remain review evidence rather than a hard stop.
    """

    left = ours["engine"].values
    right = theirs["engine"].values
    if len(left) != 1 or len(right) != 1 or _engine_values_compatible(left, right):
        return False
    common_families = set(ours["part_family"].values) & set(
        theirs["part_family"].values
    )
    return bool(common_families & {"radiator", "thermostat", "gasket"})


_NORMALIZED_ENGINE_RE = re.compile(
    r"^(\d[.]\d)(tdci|cdti|crdi|tfsi|mjtd|tdi|hdi|cdi|dti|jtd|dci|tsi|mpi|td|d|t|i)?$",
    re.IGNORECASE,
)


def _engine_values_compatible(left: Sequence[str], right: Sequence[str]) -> bool:
    """Treat an omitted fuel/induction suffix as UNKNOWN, not a contradiction."""

    for left_value in left:
        left_match = _NORMALIZED_ENGINE_RE.fullmatch(left_value)
        if left_match is None:
            continue
        for right_value in right:
            right_match = _NORMALIZED_ENGINE_RE.fullmatch(right_value)
            if right_match is None or left_match.group(1) != right_match.group(1):
                continue
            left_suffix = left_match.group(2) or ""
            right_suffix = right_match.group(2) or ""
            if not left_suffix or not right_suffix or left_suffix == right_suffix:
                return True
    return False


def _characteristics(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped[0] not in "[{":
            return []
        try:
            decoded = json.loads(stripped)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        return _characteristics(decoded)
    if isinstance(value, Mapping):
        return [
            (str(key), nested)
            for key, item in value.items()
            for nested in (item if isinstance(item, list | tuple) else (item,))
        ]
    if isinstance(value, list):
        result: list[tuple[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            label = item.get("name") or item.get("label")
            if label is not None:
                raw_value = item.get("value")
                result.extend(
                    (str(label), nested)
                    for nested in (
                        raw_value
                        if isinstance(raw_value, list | tuple)
                        else (raw_value,)
                    )
                )
        return result
    return []


def _deduplicate_evidence(
    evidence: Sequence[FeatureEvidence],
) -> list[FeatureEvidence]:
    unique: dict[tuple[str, str], FeatureEvidence] = {}
    for item in evidence:
        unique.setdefault((item.normalized_value, item.source_field), item)
    return list(unique.values())


def _single_common_or_known(left: FeatureSet, right: FeatureSet) -> str | None:
    common = set(left.values) & set(right.values)
    if len(common) == 1:
        return next(iter(common))
    values = tuple(dict.fromkeys((*left.values, *right.values)))
    return values[0] if len(values) == 1 else None


__all__ = [
    "FeatureEvidence",
    "FeatureSet",
    "SEMANTIC_FEATURE_EXTRACTOR_VERSION",
    "ambiguous_taxonomy_conflicts",
    "build_semantic_feature_matrix",
    "extract_semantic_features",
]
