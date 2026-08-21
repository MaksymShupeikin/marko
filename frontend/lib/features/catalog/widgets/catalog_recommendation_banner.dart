import 'package:flutter/material.dart';

import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../../../core/marko_motion.dart';
import '../../../core/presentation_formatters.dart';
import '../catalog_models.dart';
import 'catalog_recommendation_labels.dart';

/// Verdict block shown at the top of the product card after the operator
/// presses "Сопоставить и рассчитать цену": the engine's recommended price
/// band and exact price, or the reason the engine stayed silent.
class CatalogRecommendationBanner extends StatelessWidget {
  const CatalogRecommendationBanner({
    required this.comparison,
    this.onOpenPricing,
    super.key,
  });

  final CatalogCompetitorComparison comparison;
  final VoidCallback? onOpenPricing;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final theme = Theme.of(context);
    final currency = comparison.currency ?? '';
    final lower = comparison.lowerBound;
    final upper = comparison.upperBound;
    final recommended = comparison.recommendedPrice;
    final hasBand = comparison.hasBand;
    final comparedAt = comparison.comparedAt;

    return MarkoFadeUp(
      child: Container(
        key: const ValueKey('catalog-recommendation-banner'),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: colors.brandSoft,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.price_check_rounded, size: 19, color: colors.brand),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    context.localized(
                      ru: 'Рекомендация по цене',
                      uk: 'Рекомендація щодо ціни',
                    ),
                    style: theme.textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            if (hasBand) ...[
              Text(
                context.localized(
                  ru: 'Рекомендованный диапазон',
                  uk: 'Рекомендований діапазон',
                ),
                style: theme.textTheme.bodySmall?.copyWith(color: colors.muted),
              ),
              const SizedBox(height: 2),
              Text(
                '${lower!.toStringAsFixed(0)}–${upper!.toStringAsFixed(0)} '
                        '$currency'
                    .trim(),
                style: theme.textTheme.headlineSmall?.copyWith(
                  color: colors.ink,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ],
            if (recommended != null) ...[
              if (hasBand) const SizedBox(height: 8),
              Text(
                _recommendedLine(context, recommended, currency),
                style: hasBand
                    ? theme.textTheme.bodyMedium?.copyWith(
                        color: colors.positive,
                        fontWeight: FontWeight.w600,
                        fontFeatures: const [FontFeature.tabularFigures()],
                      )
                    : theme.textTheme.headlineSmall?.copyWith(
                        color: colors.ink,
                        fontFeatures: const [FontFeature.tabularFigures()],
                      ),
              ),
            ],
            if (!hasBand && recommended == null) ...[
              Text(
                _silenceText(context),
                style: theme.textTheme.bodyMedium?.copyWith(color: colors.ink),
              ),
            ],
            const SizedBox(height: 10),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                if (comparedAt != null)
                  Text(
                    context.localized(
                      ru: 'Рассчитано ${formatLocalDateTime(comparedAt)}',
                      uk: 'Розраховано ${formatLocalDateTime(comparedAt)}',
                    ),
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: colors.muted,
                    ),
                  ),
                if (onOpenPricing != null)
                  TextButton(
                    key: const ValueKey('catalog-recommendation-open-pricing'),
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: const Size(0, 32),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    onPressed: onOpenPricing,
                    child: Text(
                      context.localized(
                        ru: 'Перейти к сравнению цен',
                        uk: 'Перейти до порівняння цін',
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _recommendedLine(
    BuildContext context,
    DecimalValue recommended,
    String currency,
  ) {
    final current = comparison.currentPrice;
    final price = '${recommended.toStringAsFixed(0)} $currency'.trim();
    if (current == null || !(current > 0)) {
      return context.localized(
        ru: 'Рекомендованная цена: $price',
        uk: 'Рекомендована ціна: $price',
      );
    }
    final delta = (recommended - current).ratioTo(current) * 100;
    final deltaLabel = '(${delta >= 0 ? '+' : ''}${delta.toStringAsFixed(1)}%)';
    return context.localized(
      ru: 'Рекомендованная цена: $price $deltaLabel',
      uk: 'Рекомендована ціна: $price $deltaLabel',
    );
  }

  String _silenceText(BuildContext context) {
    for (final code in comparison.reasonCodes) {
      final explained = catalogSilenceLabel(context, code);
      if (explained != null) return explained;
    }
    if (comparison.hasComparison) {
      return context.localized(
        ru: 'Рекомендация не выдаётся.',
        uk: 'Рекомендація не видається.',
      );
    }
    return context.localized(
      ru: 'Рекомендация появится после запуска проверки рынка оператором.',
      uk: 'Рекомендація з’явиться після запуску перевірки ринку оператором.',
    );
  }
}
