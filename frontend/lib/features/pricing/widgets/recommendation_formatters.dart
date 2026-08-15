part of '../recommendations_page.dart';

String _money(Object value, {required String currency}) =>
    formatMoney(value, currency: currency);

String _recommendationMoney(
  PricingRecommendation recommendation,
  DecimalValue value,
) => formatMoney(
  value,
  currency: recommendation.currency,
  priceTick: recommendation.priceTick,
  fractionDigits: recommendation.priceTickScale,
);

int _cohortRank(String role) => switch (role) {
  'TARGET_MARKET' => 0,
  'KEMP_REFERENCE' => 1,
  'OWNED_STORE' => 2,
  'USED_REJECTED' => 3,
  'DUMPING_DIAGNOSTIC' => 4,
  'MANUAL_REVIEW' => 5,
  _ => 6,
};

String _actionLabel(BuildContext context, String action) => switch (action) {
  'RAISE' => context.localized(ru: 'Поднять цену', uk: 'Підвищити ціну'),
  'LOWER' => context.localized(ru: 'Снизить цену', uk: 'Знизити ціну'),
  'HOLD' => context.localized(ru: 'Оставить', uk: 'Залишити'),
  'MANUAL_REVIEW' => context.localized(
    ru: 'Проверить вручную',
    uk: 'Перевірити вручну',
  ),
  'INSUFFICIENT_DATA' => context.localized(ru: 'Мало данных', uk: 'Мало даних'),
  _ => action,
};

String _priorityLabel(
  BuildContext context,
  PricingRecommendation recommendation,
) => switch (recommendation.priorityScoreType) {
  'gross_uplift_opportunity' => context.localized(
    ru: '${_recommendationMoney(recommendation, recommendation.priorityScore)}/мес. с учётом confidence',
    uk: '${_recommendationMoney(recommendation, recommendation.priorityScore)}/міс. з урахуванням confidence',
  ),
  'clearance_priority' => context.localized(
    ru: '${_recommendationMoney(recommendation, recommendation.priorityScore)} замороженного капитала',
    uk: '${_recommendationMoney(recommendation, recommendation.priorityScore)} замороженого капіталу',
  ),
  'retail_exposure_proxy' =>
    '${recommendation.priorityScore.toStringAsFixed(2)} · stock exposure proxy',
  'gap_confidence_proxy' =>
    '${recommendation.priorityScore.toStringAsFixed(3)} · gap/confidence proxy',
  _ => '—',
};

String _reasonSummary(
  BuildContext context,
  PricingRecommendation recommendation,
) {
  if (recommendation.reasonCodes.isEmpty) {
    return context.localized(ru: 'Расчёт завершён', uk: 'Розрахунок завершено');
  }
  return summarizeLimited(
    recommendation.reasonCodes.map((code) => _reasonLabel(context, code)),
    limit: 2,
    separator: ' · ',
    overflowLabel: (hidden) =>
        context.localized(ru: 'и ещё $hidden', uk: 'і ще $hidden'),
  );
}

String _reasonLabel(BuildContext context, String code) =>
    pricingReasonLabel(context, code);

String _tierLabel(BuildContext context, String tier) => switch (tier) {
  'oem' => 'OEM',
  'oes' => 'OES',
  'aftermarket_a' => 'Aftermarket A',
  'aftermarket_b' => 'Aftermarket B',
  'budget' => context.localized(ru: 'Бюджет', uk: 'Бюджет'),
  'kemp' => 'KEMP',
  'used' => context.localized(ru: 'б/у', uk: 'вживане'),
  _ => context.localized(ru: 'не определён', uk: 'не визначено'),
};

String _cohortLabel(BuildContext context, String role) => switch (role) {
  'TARGET_MARKET' => context.localized(
    ru: 'Целевой рынок',
    uk: 'Цільовий ринок',
  ),
  'KEMP_REFERENCE' => 'KEMP reference',
  'OWNED_STORE' => context.localized(ru: 'Свой магазин', uk: 'Свій магазин'),
  'USED_REJECTED' => context.localized(
    ru: 'Б/у — исключено',
    uk: 'Вживане — виключено',
  ),
  'DUMPING_DIAGNOSTIC' => 'KEMP dumping diagnostic',
  'HARD_REJECTED' => context.localized(ru: 'Отклонено', uk: 'Відхилено'),
  _ => context.localized(ru: 'Ручная проверка', uk: 'Ручна перевірка'),
};

String _factorLabel(BuildContext context, String? value) => switch (value) {
  'coverage' => context.localized(ru: 'покрытие', uk: 'покриття'),
  'dispersion' => context.localized(ru: 'разброс цен', uk: 'розкид цін'),
  'freshness' => context.localized(ru: 'свежесть', uk: 'свіжість'),
  'match' => context.localized(ru: 'совпадение', uk: 'збіг'),
  'tier' => context.localized(ru: 'уровень товара', uk: 'рівень товару'),
  'source' => context.localized(ru: 'источник', uk: 'джерело'),
  null => context.localized(ru: 'нет', uk: 'немає'),
  _ => value,
};

String _excludedSummary(
  BuildContext context,
  List<Map<String, dynamic>> excluded,
) {
  final counts = <String, int>{};
  for (final item in excluded) {
    final reason = item['reason']?.toString() ?? 'UNKNOWN';
    counts[reason] = (counts[reason] ?? 0) + 1;
  }
  final entries = counts.entries.toList()
    ..sort((left, right) {
      final byCount = right.value.compareTo(left.value);
      return byCount != 0 ? byCount : left.key.compareTo(right.key);
    });
  return summarizeLimited(
    entries.map(
      (entry) => '${_reasonLabel(context, entry.key)}: ${entry.value}',
    ),
    limit: 4,
    separator: ' · ',
    overflowLabel: (hidden) =>
        context.localized(ru: 'и ещё $hidden', uk: 'і ще $hidden'),
  );
}
