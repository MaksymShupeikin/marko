import 'package:flutter/material.dart';

import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../catalog_models.dart';

class CatalogCompetitorSection extends StatelessWidget {
  const CatalogCompetitorSection({
    required this.comparison,
    required this.onOpenListing,
    super.key,
  });

  final CatalogCompetitorComparison comparison;
  final ValueChanged<String> onOpenListing;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          context.localized(
            ru: 'Конкурентные объявления',
            uk: 'Конкурентні оголошення',
          ),
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 5),
        Text(
          _summary(context),
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
        const SizedBox(height: 14),
        if (comparison.items.isEmpty)
          _EmptyCompetitors(hasComparison: comparison.hasComparison)
        else
          ...comparison.items.map(
            (offer) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _CompetitorListingCard(
                offer: offer,
                onOpen: () => onOpenListing(offer.url),
              ),
            ),
          ),
      ],
    );
  }

  String _summary(BuildContext context) {
    final count = comparison.items.length;
    final comparedAt = comparison.comparedAt;
    if (count == 0) {
      return context.localized(
        ru:
            'Собственные магазины здесь не показываются. Отображаются только '
            'конкуренты, вошедшие в расчёт.',
        uk:
            'Власні магазини тут не показуються. Відображаються лише '
            'конкуренти, що увійшли до розрахунку.',
      );
    }
    final dateSuffix = comparedAt == null
        ? ''
        : context.localized(
            ru: ' от ${_dateTime(comparedAt)}',
            uk: ' від ${_dateTime(comparedAt)}',
          );
    return context.localized(
      ru:
          'В последнем расчёте цены$dateSuffix учтено: $count. '
          'Собственные магазины и отклонённые кандидаты исключены.',
      uk:
          'В останньому розрахунку ціни$dateSuffix враховано: $count. '
          'Власні магазини та відхилені кандидати виключені.',
    );
  }
}

class _CompetitorListingCard extends StatelessWidget {
  const _CompetitorListingCard({required this.offer, required this.onOpen});

  final CatalogCompetitorOffer offer;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final canOpen = offer.url.isNotEmpty;
    final availabilityColor = switch (offer.isAvailable) {
      true => colors.positive,
      false => colors.negative,
      null => colors.muted,
    };
    final availability = switch (offer.isAvailable) {
      true => context.localized(ru: 'В наличии', uk: 'В наявності'),
      false => context.localized(ru: 'Нет в наличии', uk: 'Немає в наявності'),
      null => context.localized(
        ru: 'Наличие не указано',
        uk: 'Наявність не вказана',
      ),
    };
    final normalizedPrice = offer.normalizedPrice;
    final showsNormalizedPrice =
        normalizedPrice != null &&
        (normalizedPrice - offer.price).abs() >= 0.005;

    return Material(
      color: colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(11),
        side: BorderSide(color: colors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        key: ValueKey('catalog-competitor-listing-${offer.observationId}'),
        onTap: canOpen ? onOpen : null,
        child: Padding(
          padding: const EdgeInsets.all(15),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: colors.surfaceMuted,
                  borderRadius: BorderRadius.circular(9),
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.storefront_outlined,
                  size: 19,
                  color: colors.muted,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      offer.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      offer.sellerName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.muted),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 10,
                      runSpacing: 5,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          '${offer.price.toStringAsFixed(2)} ${offer.currency}',
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(
                                fontFeatures: const [
                                  FontFeature.tabularFigures(),
                                ],
                              ),
                        ),
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 6,
                              height: 6,
                              decoration: BoxDecoration(
                                color: availabilityColor,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 6),
                            Text(
                              availability,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 7),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        _ComparisonBadge(),
                        if (showsNormalizedPrice)
                          Text(
                            context.localized(
                              ru: 'Для расчёта: ${normalizedPrice.toStringAsFixed(2)} ${offer.currency}',
                              uk: 'Для розрахунку: ${normalizedPrice.toStringAsFixed(2)} ${offer.currency}',
                            ),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                      ],
                    ),
                  ],
                ),
              ),
              if (canOpen) ...[
                const SizedBox(width: 8),
                Tooltip(
                  message: context.localized(
                    ru: 'Открыть на Prom.ua',
                    uk: 'Відкрити на Prom.ua',
                  ),
                  child: Icon(
                    Icons.open_in_new_rounded,
                    size: 19,
                    color: colors.brand,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ComparisonBadge extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: colors.positive.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        context.localized(
          ru: 'Учитывается в сравнении',
          uk: 'Враховується у порівнянні',
        ),
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
          color: colors.positive,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class CatalogCompetitorLoading extends StatelessWidget {
  const CatalogCompetitorLoading({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          context.localized(
            ru: 'Конкурентные объявления',
            uk: 'Конкурентні оголошення',
          ),
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 14),
        const LinearProgressIndicator(minHeight: 2),
        const SizedBox(height: 12),
        Text(
          context.localized(
            ru: 'Загружаем данные последнего сравнения…',
            uk: 'Завантажуємо дані останнього порівняння…',
          ),
          textAlign: TextAlign.center,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
      ],
    );
  }
}

class CatalogCompetitorError extends StatelessWidget {
  const CatalogCompetitorError({required this.onRetry, super.key});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        children: [
          Text(
            context.localized(
              ru: 'Не удалось загрузить конкурентные объявления.',
              uk: 'Не вдалося завантажити конкурентні оголошення.',
            ),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: onRetry,
            child: Text(context.localized(ru: 'Повторить', uk: 'Повторити')),
          ),
        ],
      ),
    );
  }
}

class _EmptyCompetitors extends StatelessWidget {
  const _EmptyCompetitors({required this.hasComparison});

  final bool hasComparison;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      key: const ValueKey('catalog-competitors-empty'),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        children: [
          Icon(Icons.search_off_rounded, color: colors.muted, size: 24),
          const SizedBox(height: 8),
          Text(
            hasComparison
                ? context.localized(
                    ru:
                        'В последнем расчёте не осталось подходящих '
                        'конкурентных объявлений.',
                    uk:
                        'В останньому розрахунку не залишилося відповідних '
                        'конкурентних оголошень.',
                  )
                : context.localized(
                    ru:
                        'Для этого товара конкурентные объявления ещё не '
                        'собраны. Запустите сравнение цен.',
                    uk:
                        'Для цього товару конкурентні оголошення ще не '
                        'зібрані. Запустіть порівняння цін.',
                  ),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

String _dateTime(DateTime value) {
  final local = value.toLocal();
  String twoDigits(int number) => number.toString().padLeft(2, '0');
  return '${twoDigits(local.day)}.${twoDigits(local.month)}.${local.year} '
      '${twoDigits(local.hour)}:${twoDigits(local.minute)}';
}
