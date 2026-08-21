part of '../recommendations_page.dart';

class CustomerPriceAdvisory extends StatelessWidget {
  const CustomerPriceAdvisory({super.key, required this.recommendation});

  final PricingRecommendation recommendation;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final target = recommendation.advisoryRecommendedPrice!;
    final marketMinimum = recommendation.advisoryMarketMinimum;
    final bandLow = recommendation.advisoryTargetBandLow;
    final bandHigh = recommendation.advisoryTargetBandHigh;
    final excludedImplausible = recommendation.customerExcludedImplausibleCount;
    final plausibilityFloor = recommendation.customerPlausibilityFloor;
    final direction = recommendation.advisoryAction == 'LOWER'
        ? context.localized(ru: 'Снизить', uk: 'Знизити')
        : context.localized(ru: 'Поднять', uk: 'Підвищити');
    return Container(
      key: const ValueKey('customer-price-advisory'),
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.tertiaryContainer.withValues(alpha: 0.42),
        border: Border.all(color: colors.tertiary.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.localized(
              ru: 'Ценовой ориентир заказчика',
              uk: 'Ціновий орієнтир замовника',
            ),
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
              color: colors.onTertiaryContainer,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '$direction: ${_recommendationMoney(recommendation, target)}',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
          if (marketMinimum != null && bandLow != null && bandHigh != null) ...[
            const SizedBox(height: 4),
            Text(
              context.localized(
                ru:
                    'Минимальная сопоставимая цена: '
                    '${_recommendationMoney(recommendation, marketMinimum)}. '
                    'Цель −5%: '
                    '${_recommendationMoney(recommendation, bandLow)} — '
                    '${_recommendationMoney(recommendation, bandHigh)}.',
                uk:
                    'Мінімальна зіставна ціна: '
                    '${_recommendationMoney(recommendation, marketMinimum)}. '
                    'Ціль −5%: '
                    '${_recommendationMoney(recommendation, bandLow)} — '
                    '${_recommendationMoney(recommendation, bandHigh)}.',
              ),
            ),
          ],
          if (excludedImplausible > 0 && plausibilityFloor != null) ...[
            const SizedBox(height: 4),
            Text(
              context.localized(
                ru:
                    'Из ценовой цели исключено подозрительно дешёвых '
                    'предложений: $excludedImplausible (ниже '
                    '${_recommendationMoney(recommendation, plausibilityFloor)}). '
                    'Они остаются в доказательствах.',
                uk:
                    'Із цінової цілі виключено підозріло дешевих '
                    'пропозицій: $excludedImplausible (нижче '
                    '${_recommendationMoney(recommendation, plausibilityFloor)}). '
                    'Вони залишаються в доказах.',
              ),
            ),
          ],
          if (recommendation.advisoryDecision?['status'] ==
              'INCOMPLETE_EVIDENCE_REVIEW_REQUIRED') ...[
            const SizedBox(height: 6),
            Text(
              context.localized(
                ru:
                    'Требует проверки оператором. Основание: '
                    '${recommendation.advisoryDecision?['basis_offer_count'] ?? '—'} '
                    'карточек, '
                    '${recommendation.advisoryDecision?['basis_independent_sellers'] ?? '—'} '
                    'продавцов. Проверьте комплект, состояние и единицу '
                    'перед решением.',
                uk:
                    'Потребує перевірки оператором. Підстава: '
                    '${recommendation.advisoryDecision?['basis_offer_count'] ?? '—'} '
                    'карток, '
                    '${recommendation.advisoryDecision?['basis_independent_sellers'] ?? '—'} '
                    'продавців. Перевірте комплект, стан і одиницю '
                    'перед рішенням.',
              ),
            ),
          ],
          const SizedBox(height: 6),
          Text(
            context.localized(
              ru:
                  'Формула: минимальная подтверждённая цена конкурента минус 5%. '
                  'Перед решением учтите закупку, комиссию Prom, эквайринг, налоги, упаковку, '
                  'доставку, возвраты, гарантию и минимальную маржу. Цена автоматически не применяется.',
              uk:
                  'Формула: мінімальна підтверджена ціна конкурента мінус 5%. '
                  'Перед рішенням врахуйте закупівлю, комісію Prom, еквайринг, податки, пакування, '
                  'доставку, повернення, гарантію та мінімальну маржу. Ціна автоматично не застосовується.',
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
