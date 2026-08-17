import 'package:flutter/material.dart';

import '../../core/app_language.dart';

class PricingReasonTranslation {
  const PricingReasonTranslation({required this.ru, required this.uk});

  final String ru;
  final String uk;
}

/// Customer-facing contract for every pricing reason the backend may emit.
///
/// Keep the literal keys explicit: the backend guard test reads this map and
/// rejects a server-side reason code that has no RU and UK copy.
const pricingReasonTranslations = <String, PricingReasonTranslation>{
  'MARKET_SUPPORTS_RAISE': PricingReasonTranslation(
    ru: 'рынок поддерживает повышение',
    uk: 'ринок підтримує підвищення',
  ),
  'EVIDENCE_REFERENCE_UNBOUND': PricingReasonTranslation(
    ru: 'часть подтверждающих цитат не сошлась с карточкой и отброшена',
    uk: 'частину підтверджувальних цитат не звірено з карткою і відкинуто',
  ),
  'MARKET_SUPPORTS_LOWER': PricingReasonTranslation(
    ru: 'рынок поддерживает снижение',
    uk: 'ринок підтримує зниження',
  ),
  'CUSTOMER_BUDGET_FLOOR_POLICY': PricingReasonTranslation(
    ru: 'применена бюджетная ценовая политика заказчика',
    uk: 'застосовано бюджетну цінову політику замовника',
  ),
  'TIER_AGNOSTIC_OWNER_POLICY': PricingReasonTranslation(
    ru: 'уровень бренда не влияет на ценовой ориентир',
    uk: 'рівень бренду не впливає на ціновий орієнтир',
  ),
  'STOCK_AND_COST_IGNORED_BY_OWNER_POLICY': PricingReasonTranslation(
    ru: 'закупка и возраст остатка не влияют на расчёт',
    uk: 'закупівля та вік залишку не впливають на розрахунок',
  ),
  'TARGET_5_PERCENT_BELOW_MINIMUM': PricingReasonTranslation(
    ru: 'цель — ровно на 5% дешевле минимальной сопоставимой цены',
    uk: 'ціль — рівно на 5% дешевше мінімальної зіставної ціни',
  ),
  'IMPLAUSIBLE_EXCLUDED_FROM_TARGET': PricingReasonTranslation(
    ru: 'часть предложений слишком дешёвая для этой детали и не влияла на цель',
    uk: 'частина пропозицій надто дешева для цієї деталі й не впливала на ціль',
  ),
  'ALL_EVIDENCE_BELOW_PLAUSIBILITY_FLOOR': PricingReasonTranslation(
    ru: 'все найденные цены слишком низкие, чтобы быть настоящими — проверьте вручную',
    uk: 'усі знайдені ціни надто низькі, щоб бути справжніми — перевірте вручну',
  ),
  'PRICE_WITHIN_CUSTOMER_TARGET_BAND': PricingReasonTranslation(
    ru: 'цена уже равна цели: 5% ниже минимальной сопоставимой цены',
    uk: 'ціна вже дорівнює цілі: 5% нижче мінімальної зіставної ціни',
  ),
  'NO_RECOMMENDATION_WITHIN_TARGET_BAND': PricingReasonTranslation(
    ru: 'изменение не требуется: цена в целевом коридоре',
    uk: 'зміна не потрібна: ціна в цільовому коридорі',
  ),
  'NO_PRICE_TICK_WITHIN_CUSTOMER_BAND': PricingReasonTranslation(
    ru: 'шаг округления не позволяет попасть в точную цель −5%',
    uk: 'крок округлення не дозволяє потрапити в точну ціль −5%',
  ),
  'FLOOR_MATERIALLY_BELOW_NEXT_SELLER': PricingReasonTranslation(
    ru:
        'минимум значительно ниже следующего независимого продавца; '
        'проверьте цену-заглушку, б/у, комплектность и точную деталь',
    uk:
        'мінімум значно нижчий за наступного незалежного продавця; '
        'перевірте ціну-заглушку, вживаний стан, комплектність і точну деталь',
  ),
  'FLOOR_RESTS_ON_ONE_SELLER': PricingReasonTranslation(
    ru: 'на минимальной цене стоит только один продавец',
    uk: 'на мінімальній ціні стоїть лише один продавець',
  ),
  'FLOOR_CORROBORATION_UNAVAILABLE': PricingReasonTranslation(
    ru: 'продавцы предложений неизвестны, подтвердить минимум было нечем',
    uk: 'продавці пропозицій невідомі, підтвердити мінімум було нічим',
  ),
  'FLOOR_CORROBORATION_BY_RELATED_SELLERS': PricingReasonTranslation(
    ru: 'минимум подтверждён только связанными между собой продавцами',
    uk: 'мінімум підтверджено лише пов’язаними між собою продавцями',
  ),
  'FLAG_FLOOR_CORROBORATION_BY_RELATED_SELLERS': PricingReasonTranslation(
    ru: 'минимум подтверждён только связанными между собой продавцами',
    uk: 'мінімум підтверджено лише пов’язаними між собою продавцями',
  ),
  'FLOOR_NOT_CORROBORATED_AS_REQUIRED': PricingReasonTranslation(
    ru: 'на минимуме нет требуемого числа независимых продавцов',
    uk: 'на мінімумі немає потрібної кількості незалежних продавців',
  ),
  'SELLER_COUNT_MISMATCH': PricingReasonTranslation(
    ru: 'список продавцов не совпал по длине со списком цен',
    uk: 'список продавців не збігся за довжиною зі списком цін',
  ),
  'MARKET_NOT_ABOVE_RAISE_THRESHOLD': PricingReasonTranslation(
    ru: 'рынок не выше текущей цены',
    uk: 'ринок не вище поточної ціни',
  ),
  'CLEARANCE_MARKDOWN': PricingReasonTranslation(
    ru: 'цена для высвобождения капитала',
    uk: 'ціна для вивільнення капіталу',
  ),
  'CLEARANCE_TARGET_NOT_ACTIONABLE': PricingReasonTranslation(
    ru: 'расчётная скидка слишком мала для действия',
    uk: 'розрахункова знижка надто мала для дії',
  ),
  'TOO_FEW_COMPETITORS': PricingReasonTranslation(
    ru: 'мало валидных конкурентов',
    uk: 'мало валідних конкурентів',
  ),
  'TOO_FEW_COMPETITORS_AFTER_CLEANING': PricingReasonTranslation(
    ru: 'после очистки осталось мало конкурентов',
    uk: 'після очищення залишилося мало конкурентів',
  ),
  'TOO_FEW_COMPETITORS_FOR_ACTION': PricingReasonTranslation(
    ru: 'мало конкурентов для автоматического действия',
    uk: 'мало конкурентів для автоматичної дії',
  ),
  'TOO_FEW_PRICING_EVIDENCE': PricingReasonTranslation(
    ru: 'мало ценовых доказательств',
    uk: 'мало цінових доказів',
  ),
  'LOW_CONFIDENCE': PricingReasonTranslation(
    ru: 'низкая уверенность',
    uk: 'низька впевненість',
  ),
  'LOW_CONFIDENCE_BASIS': PricingReasonTranslation(
    ru: 'низкая уверенность в ценовой базе',
    uk: 'низька впевненість у ціновій базі',
  ),
  'LOW_COVERAGE': PricingReasonTranslation(ru: 'мало данных', uk: 'мало даних'),
  'LOW_DISPERSION': PricingReasonTranslation(
    ru: 'слишком низкий разброс цен',
    uk: 'надто низький розкид цін',
  ),
  'HIGH_DISPERSION': PricingReasonTranslation(
    ru: 'слишком большой разброс цен',
    uk: 'надто великий розкид цін',
  ),
  'LOW_FRESHNESS': PricingReasonTranslation(
    ru: 'данные устарели',
    uk: 'дані застаріли',
  ),
  'LOW_MATCH': PricingReasonTranslation(
    ru: 'слабое совпадение товаров',
    uk: 'слабкий збіг товарів',
  ),
  'LOW_MATCH_CONFIDENCE': PricingReasonTranslation(
    ru: 'низкая уверенность в совпадении товара',
    uk: 'низька впевненість у збігу товару',
  ),
  'LOW_TIER': PricingReasonTranslation(
    ru: 'смешались уровни товара',
    uk: 'змішалися рівні товару',
  ),
  'LOW_TIER_CONFIDENCE': PricingReasonTranslation(
    ru: 'уровень бренда определён неуверенно',
    uk: 'рівень бренду визначено невпевнено',
  ),
  'LOW_SOURCE': PricingReasonTranslation(
    ru: 'низкая надёжность источника',
    uk: 'низька надійність джерела',
  ),
  'LOW_SOURCE_CONFIDENCE': PricingReasonTranslation(
    ru: 'источник подтверждён недостаточно',
    uk: 'джерело підтверджено недостатньо',
  ),
  'LOW_EFFECTIVE_SAMPLE_SIZE': PricingReasonTranslation(
    ru: 'мало независимых конкурентов',
    uk: 'мало незалежних конкурентів',
  ),
  'INVALID_CURRENT_PRICE': PricingReasonTranslation(
    ru: 'текущая цена некорректна',
    uk: 'поточна ціна некоректна',
  ),
  'CONTEXT_CURRENCY_MISMATCH': PricingReasonTranslation(
    ru: 'валюта товара не совпадает с политикой расчёта',
    uk: 'валюта товару не збігається з політикою розрахунку',
  ),
  'NON_POSITIVE_PRICE': PricingReasonTranslation(
    ru: 'цена конкурента должна быть больше нуля',
    uk: 'ціна конкурента має бути більшою за нуль',
  ),
  'NON_FINITE_PRICE': PricingReasonTranslation(
    ru: 'цена конкурента имеет недопустимое числовое значение',
    uk: 'ціна конкурента має неприпустиме числове значення',
  ),
  'CURRENCY_MISMATCH': PricingReasonTranslation(
    ru: 'валюта конкурента не совпадает',
    uk: 'валюта конкурента не збігається',
  ),
  'NOT_AVAILABLE': PricingReasonTranslation(
    ru: 'товар конкурента недоступен',
    uk: 'товар конкурента недоступний',
  ),
  'STALE_SOURCE': PricingReasonTranslation(
    ru: 'источник устарел',
    uk: 'джерело застаріло',
  ),
  'SEMANTIC_GATE_NOT_CURRENT': PricingReasonTranslation(
    ru: 'семантическая проверка устарела — предложение отправлено на повторную проверку',
    uk: 'семантична перевірка застаріла — пропозицію відправлено на повторну перевірку',
  ),
  'PERSISTED_AUTOMATIC_ELIGIBILITY_REQUIRED': PricingReasonTranslation(
    ru: 'сохранённое предложение не прошло явный допуск к автоматическому расчёту',
    uk: 'збережена пропозиція не пройшла явний допуск до автоматичного розрахунку',
  ),
  'OE_AUTOMATIC_IDENTITY_EVIDENCE_INSUFFICIENT': PricingReasonTranslation(
    ru: 'для автоматического сравнения недостаточно структурного доказательства OE',
    uk: 'для автоматичного порівняння недостатньо структурованого доказу OE',
  ),
  'USED_OR_REFURBISHED': PricingReasonTranslation(
    ru: 'товар бывший в употреблении или восстановленный',
    uk: 'товар вживаний або відновлений',
  ),
  'KEMP_DUMPING': PricingReasonTranslation(
    ru: 'цена KEMP оставлена только для диагностики демпинга',
    uk: 'ціну KEMP залишено лише для діагностики демпінгу',
  ),
  'OWNED_SELLER': PricingReasonTranslation(
    ru: 'собственный магазин исключён из рынка',
    uk: 'власний магазин виключено з ринку',
  ),
  'PERSISTED_COHORT_NOT_TARGET_ELIGIBLE': PricingReasonTranslation(
    ru: 'сохранённая группа не входит в целевой рынок',
    uk: 'збережена група не входить до цільового ринку',
  ),
  'COMMERCIAL_CONFLICT': PricingReasonTranslation(
    ru: 'товары коммерчески несопоставимы',
    uk: 'товари комерційно незрівнянні',
  ),
  'UNKNOWN_TIER': PricingReasonTranslation(
    ru: 'уровень бренда не определён',
    uk: 'рівень бренду не визначено',
  ),
  'UNVALIDATED_TIER_COEFFICIENT': PricingReasonTranslation(
    ru: 'коэффициент уровня бренда не валидирован',
    uk: 'коефіцієнт рівня бренду не валідовано',
  ),
  'INVALID_TIER_COEFFICIENT': PricingReasonTranslation(
    ru: 'коэффициент уровня бренда некорректен',
    uk: 'коефіцієнт рівня бренду некоректний',
  ),
  'LOWER_TIER_EXCLUDED': PricingReasonTranslation(
    ru: 'более низкий уровень исключён политикой',
    uk: 'нижчий рівень виключено політикою',
  ),
  'INVALID_NORMALIZED_PRICE': PricingReasonTranslation(
    ru: 'нормализованная цена некорректна',
    uk: 'нормалізована ціна некоректна',
  ),
  'SELLER_DUPLICATE': PricingReasonTranslation(
    ru: 'повтор одного продавца исключён',
    uk: 'повтор одного продавця виключено',
  ),
  'ROBUST_OUTLIER': PricingReasonTranslation(
    ru: 'ценовой выброс исключён',
    uk: 'ціновий викид виключено',
  ),
  'SEVERE_DATA_HEALTH_ISSUE': PricingReasonTranslation(
    ru: 'критическая проблема данных',
    uk: 'критична проблема даних',
  ),
  'INVALID_FAIR_PRICE': PricingReasonTranslation(
    ru: 'справедливая цена не прошла проверку',
    uk: 'справедлива ціна не пройшла перевірку',
  ),
  'ESTIMATOR_SENSITIVITY': PricingReasonTranslation(
    ru: 'оценка неустойчива к очистке данных',
    uk: 'оцінка нестійка до очищення даних',
  ),
  'ROBUST_SCALE_PARTIAL_DEGENERACY': PricingReasonTranslation(
    ru: 'разброс цен определён недостаточно надёжно',
    uk: 'розкид цін визначено недостатньо надійно',
  ),
  'ROBUST_SCALE_ALL_ZERO_WITH_VARIATION': PricingReasonTranslation(
    ru: 'нулевой разброс противоречит различающимся ценам',
    uk: 'нульовий розкид суперечить різним цінам',
  ),
  'ROBUST_ESTIMATOR_DISAGREEMENT': PricingReasonTranslation(
    ru: 'робастные оценки расходятся',
    uk: 'робастні оцінки розходяться',
  ),
  'ROBUST_MULTIMODAL_COHORT': PricingReasonTranslation(
    ru: 'обнаружены разные ценовые кластеры',
    uk: 'виявлено різні цінові кластери',
  ),
  'ROBUST_DIAGNOSTIC_UNAVAILABLE': PricingReasonTranslation(
    ru: 'диагностика ценовых кластеров недоступна',
    uk: 'діагностика цінових кластерів недоступна',
  ),
  'ROBUST_SCALE_CAPACITY_EXCEEDED': PricingReasonTranslation(
    ru: 'выборка превышает проверенный предел расчёта',
    uk: 'вибірка перевищує перевірену межу розрахунку',
  ),
  'ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE': PricingReasonTranslation(
    ru: 'новая модель не может обойти отказ базовой модели',
    uk: 'нова модель не може обійти відмову базової моделі',
  ),
  'MANUAL_POLICY_NOT_APPROVED': PricingReasonTranslation(
    ru: 'политика сопоставимости не подтверждена',
    uk: 'політику зіставності не підтверджено',
  ),
  'MANUAL_CATEGORY_POLICY_UNMAPPED': PricingReasonTranslation(
    ru: 'для категории не настроена политика сопоставимости',
    uk: 'для категорії не налаштовано політику зіставності',
  ),
  'MANUAL_MISSING_COMPARABILITY_EVIDENCE': PricingReasonTranslation(
    ru: 'нет доказательств сопоставимости',
    uk: 'немає доказів зіставності',
  ),
  'CUSTOMER_IDENTITY_MISSING': PricingReasonTranslation(
    ru:
        'заказчик не указал подтверждённый OE, MPN или кросс-номер — '
        'товар не сопоставлялся',
    uk:
        'замовник не вказав підтверджений OE, MPN або крос-номер — '
        'товар не зіставлявся',
  ),
  'MANUAL_MISSING_OE_PROVENANCE': PricingReasonTranslation(
    ru: 'нет проверенного происхождения OE',
    uk: 'немає перевіреного походження OE',
  ),
  'MANUAL_MISSING_PART_TYPE': PricingReasonTranslation(
    ru: 'не подтверждён тип детали',
    uk: 'не підтверджено тип деталі',
  ),
  'MANUAL_MISSING_BRAND': PricingReasonTranslation(
    ru: 'не подтверждён бренд или производитель',
    uk: 'не підтверджено бренд або виробника',
  ),
  'MANUAL_MISSING_FITMENT': PricingReasonTranslation(
    ru: 'не подтверждена применимость',
    uk: 'не підтверджено застосовність',
  ),
  'MANUAL_MISSING_SIDE_OR_POSITION': PricingReasonTranslation(
    ru: 'не подтверждена сторона или позиция',
    uk: 'не підтверджено бік або позицію',
  ),
  'MANUAL_MISSING_CONDITION': PricingReasonTranslation(
    ru: 'не подтверждено состояние товара',
    uk: 'не підтверджено стан товару',
  ),
  'MANUAL_MISSING_PACKAGE_QUANTITY': PricingReasonTranslation(
    ru: 'не подтверждено количество в упаковке',
    uk: 'не підтверджено кількість в упаковці',
  ),
  'MANUAL_MISSING_STABLE_SELLER_ID': PricingReasonTranslation(
    ru: 'нет стабильного ID продавца',
    uk: 'немає стабільного ID продавця',
  ),
  'MANUAL_MISSING_SOURCE_PROVENANCE': PricingReasonTranslation(
    ru: 'нет проверенного происхождения источника',
    uk: 'немає перевіреного походження джерела',
  ),
  'MANUAL_MISSING_RAW_CURRENCY': PricingReasonTranslation(
    ru: 'валюта не указана в источнике',
    uk: 'валюту не вказано в джерелі',
  ),
  'REJECTED_IDENTITY_CONFLICT': PricingReasonTranslation(
    ru: 'конфликт идентичности товара',
    uk: 'конфлікт ідентичності товару',
  ),
  'REJECTED_COMPARABILITY_CONFLICT': PricingReasonTranslation(
    ru: 'коммерчески несопоставимые товары',
    uk: 'комерційно незрівнянні товари',
  ),
  'REJECTED_LLM_NOT_COMPARABLE': PricingReasonTranslation(
    ru: 'LLM обнаружила несопоставимый товар',
    uk: 'LLM виявила незіставний товар',
  ),
  'MANUAL_LLM_COMPARABILITY_INSUFFICIENT': PricingReasonTranslation(
    ru: 'LLM не хватило данных для подтверждения сопоставимости',
    uk: 'LLM не вистачило даних для підтвердження зіставності',
  ),
  'MANUAL_LLM_COMPARABILITY_MISSING': PricingReasonTranslation(
    ru: 'обязательная LLM-проверка отсутствует',
    uk: 'обов’язкова LLM-перевірка відсутня',
  ),
  'ELIGIBLE_VERIFIED': PricingReasonTranslation(
    ru: 'сопоставимость подтверждена',
    uk: 'зіставність підтверджено',
  ),
  'MANUAL_REVIEW_REQUIRED': PricingReasonTranslation(
    ru: 'требуется ручная проверка',
    uk: 'потрібна ручна перевірка',
  ),
  'COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED': PricingReasonTranslation(
    ru: 'автовыдача заблокирована до проверки сопоставимости',
    uk: 'автовидачу заблоковано до перевірки зіставності',
  ),
  'MANUAL_OVERRIDE': PricingReasonTranslation(
    ru: 'уровень изменён оператором',
    uk: 'рівень змінено оператором',
  ),
  'STALE_NOT_BELOW_CHEAPEST_COMPETITOR': PricingReasonTranslation(
    ru: 'залежавшийся товар уже не дешевле рынка',
    uk: 'залежаний товар уже не дешевший за ринок',
  ),
  'PRICE_ALREADY_AT_OR_ABOVE_TARGET': PricingReasonTranslation(
    ru: 'цена уже достигла рыночной цели',
    uk: 'ціна вже досягла ринкової цілі',
  ),
  'CHANGE_BELOW_SIGNIFICANCE_THRESHOLD': PricingReasonTranslation(
    ru: 'изменение ниже порога значимости',
    uk: 'зміна нижче порога значущості',
  ),
  'STEP_CAPPED': PricingReasonTranslation(
    ru: 'повышение ограничено максимальным шагом',
    uk: 'підвищення обмежено максимальним кроком',
  ),
  'STALE_CAPPED_AT_CHEAPEST': PricingReasonTranslation(
    ru: 'цена ограничена самым дешёвым конкурентом',
    uk: 'ціну обмежено найдешевшим конкурентом',
  ),
  'ROUNDING_REMOVED_THE_CHANGE': PricingReasonTranslation(
    ru: 'округление убрало изменение цены',
    uk: 'округлення прибрало зміну ціни',
  ),
  'ROUNDED_BELOW_SIGNIFICANCE': PricingReasonTranslation(
    ru: 'после округления изменение стало малым',
    uk: 'після округлення зміна стала малою',
  ),
  'BELOW_COST_FLOOR': PricingReasonTranslation(
    ru: 'рекомендация ниже ценового пола',
    uk: 'рекомендація нижче цінової підлоги',
  ),
  'RECOMMENDATION_BELOW_COST_FLOOR': PricingReasonTranslation(
    ru: 'рекомендация ниже ценового пола',
    uk: 'рекомендація нижче цінової підлоги',
  ),
  'BELOW_COST_ONLY_FOR_DEAD_STOCK': PricingReasonTranslation(
    ru: 'цена ниже себестоимости доступна только для неликвида',
    uk: 'ціна нижче собівартості доступна лише для неліквіду',
  ),
  'MISSING_FLOOR': PricingReasonTranslation(
    ru: 'нужен подтверждённый ценовой пол',
    uk: 'потрібна підтверджена цінова підлога',
  ),
  'MISSING_COST': PricingReasonTranslation(
    ru: 'нужна себестоимость',
    uk: 'потрібна собівартість',
  ),
  'MISSING_BELOW_COST_AUTHORIZATION': PricingReasonTranslation(
    ru: 'нет подтверждения продажи ниже себестоимости',
    uk: 'немає підтвердження продажу нижче собівартості',
  ),
  'UNKNOWN_STOCK_STATUS': PricingReasonTranslation(
    ru: 'статус запаса неизвестен',
    uk: 'статус запасу невідомий',
  ),
  'AGE_POLICY_ENGINEERING_ASSUMPTION': PricingReasonTranslation(
    ru: 'возрастная политика пока является инженерным допущением',
    uk: 'вікова політика поки є інженерним припущенням',
  ),
  'AGE_POLICY_VERSION_APPLIED': PricingReasonTranslation(
    ru: 'применена зафиксированная версия возрастной политики',
    uk: 'застосовано зафіксовану версію вікової політики',
  ),
  'STOCK_AGE_UNKNOWN_BASE_POLICY_ONLY': PricingReasonTranslation(
    ru: 'возраст запаса неизвестен; применена базовая политика',
    uk: 'вік запасу невідомий; застосовано базову політику',
  ),
  'INVARIANT_FAIR_PRICE_NON_POSITIVE': PricingReasonTranslation(
    ru: 'внутренняя проверка: справедливая цена не положительна',
    uk: 'внутрішня перевірка: справедлива ціна не додатна',
  ),
  'INVARIANT_CONFIDENCE_OUT_OF_RANGE': PricingReasonTranslation(
    ru: 'внутренняя проверка: уверенность вне допустимого диапазона',
    uk: 'внутрішня перевірка: впевненість поза допустимим діапазоном',
  ),
  'INVARIANT_EFFECTIVE_SAMPLE_NEGATIVE': PricingReasonTranslation(
    ru: 'внутренняя проверка: размер выборки некорректен',
    uk: 'внутрішня перевірка: розмір вибірки некоректний',
  ),
  'INVARIANT_RECOMMENDED_PRICE_NON_POSITIVE': PricingReasonTranslation(
    ru: 'внутренняя проверка: рекомендация не положительна',
    uk: 'внутрішня перевірка: рекомендація не додатна',
  ),
  'INVARIANT_RAISE_NOT_ABOVE_CURRENT': PricingReasonTranslation(
    ru: 'внутренняя проверка: повышение не выше текущей цены',
    uk: 'внутрішня перевірка: підвищення не вище поточної ціни',
  ),
  'INVARIANT_LOWER_NOT_BELOW_CURRENT': PricingReasonTranslation(
    ru: 'внутренняя проверка: снижение не ниже текущей цены',
    uk: 'внутрішня перевірка: зниження не нижче поточної ціни',
  ),
  'INVARIANT_ACTION_WITHOUT_GATES': PricingReasonTranslation(
    ru: 'внутренняя проверка: действие без пройденных ворот',
    uk: 'внутрішня перевірка: дія без пройдених воріт',
  ),
  'INVARIANT_NON_TARGET_IN_FAIR_COHORT': PricingReasonTranslation(
    ru: 'внутренняя проверка: в расчёт попал нецелевой оффер',
    uk: 'внутрішня перевірка: до розрахунку потрапив нецільовий офер',
  ),
  'INVARIANT_INVALID_KEMP_REFERENCE_ROLE': PricingReasonTranslation(
    ru: 'внутренняя проверка: неверная роль справочника KEMP',
    uk: 'внутрішня перевірка: неправильна роль довідника KEMP',
  ),
  'INVARIANT_COHORT_OVERLAP': PricingReasonTranslation(
    ru: 'внутренняя проверка: ценовые группы пересекаются',
    uk: 'внутрішня перевірка: цінові групи перетинаються',
  ),
  'INVARIANT_DUPLICATE_EVIDENCE': PricingReasonTranslation(
    ru: 'внутренняя проверка: доказательство продублировано',
    uk: 'внутрішня перевірка: доказ продубльовано',
  ),
};

String pricingReasonLabel(
  BuildContext context,
  String code, {
  ValueChanged<String>? onUnknown,
}) {
  final translation = pricingReasonTranslations[code];
  if (translation != null) {
    return context.localized(ru: translation.ru, uk: translation.uk);
  }
  debugPrint('Unknown pricing reason code: $code');
  onUnknown?.call(code);
  return context.localized(
    ru: 'Неизвестная причина ($code)',
    uk: 'Невідома причина ($code)',
  );
}

String pricingReasonLabelRu(String code) =>
    pricingReasonTranslations[code]?.ru ?? 'Неизвестная причина ($code)';
