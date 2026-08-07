import 'package:flutter/material.dart';

import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../../../core/presentation_formatters.dart';
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
        if (comparison.hasComparison) ...[
          _PriceCalculationCard(comparison: comparison),
          const SizedBox(height: 16),
        ],
        if (comparison.items.isEmpty)
          _EmptyCompetitors(
            hasComparison: comparison.hasComparison,
            hasDiscovery: comparison.hasDiscovery,
          )
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
        if (comparison.hasDiscovery) ...[
          const SizedBox(height: 24),
          _DiscoverySection(
            comparison: comparison,
            onOpenListing: onOpenListing,
          ),
        ],
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
            ru: ' от ${formatLocalDateTime(comparedAt)}',
            uk: ' від ${formatLocalDateTime(comparedAt)}',
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

class _DiscoverySection extends StatelessWidget {
  const _DiscoverySection({
    required this.comparison,
    required this.onOpenListing,
  });

  final CatalogCompetitorComparison comparison;
  final ValueChanged<String> onOpenListing;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final collectedAt = comparison.discoveredAt;
    final dateSuffix = collectedAt == null
        ? ''
        : ' · ${formatLocalDateTime(collectedAt)}';
    final ownedSuffix = comparison.ownedExcludedCount == 0
        ? ''
        : context.localized(
            ru:
                ' Собственных объявлений исключено: '
                '${comparison.ownedExcludedCount}.',
            uk:
                ' Власних оголошень виключено: '
                '${comparison.ownedExcludedCount}.',
          );
    final classifiedOfferIds = {
      ...comparison.pricingEvidence.map((offer) => offer.discoveryOfferId),
      ...comparison.referenceOnly.map((offer) => offer.discoveryOfferId),
    };
    final remainingParsedOffers = comparison.discoveryItems
        .where((offer) => !classifiedOfferIds.contains(offer.discoveryOfferId))
        .toList(growable: false);

    return Column(
      key: const ValueKey('catalog-discovery-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          context.localized(ru: 'Найдено парсером', uk: 'Знайдено парсером'),
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 5),
        Text(
          context.localized(
            ru:
                'По запросу ${comparison.discoveryQuery ?? '—'} найдено '
                '${comparison.discoveredTotal} внешних кандидатов$dateSuffix.'
                '$ownedSuffix Они ещё не считаются доказанно '
                'сопоставимыми и не влияют на цену.',
            uk:
                'За запитом ${comparison.discoveryQuery ?? '—'} знайдено '
                '${comparison.discoveredTotal} зовнішніх кандидатів$dateSuffix.'
                '$ownedSuffix Вони ще не вважаються доведено '
                'зіставними та не впливають на ціну.',
          ),
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
        if (comparison.promReportedTotal != null) ...[
          const SizedBox(height: 9),
          _CoverageNotice(comparison: comparison),
        ],
        if (comparison.selectionHistogram.isNotEmpty) ...[
          const SizedBox(height: 12),
          _SelectionHistogram(comparison: comparison),
        ],
        if (remainingParsedOffers.isNotEmpty) ...[
          const SizedBox(height: 18),
          _OutcomeBlock(
            key: const ValueKey('catalog-parser-candidates-block'),
            title: context.localized(
              ru: 'Остальные объявления из выдачи парсера',
              uk: 'Інші оголошення з видачі парсера',
            ),
            subtitle: context.localized(
              ru:
                  'Они сохранены и показаны для ручной проверки. '
                  'Статус и причина указаны в каждой карточке; на цену '
                  'эти объявления не влияют.',
              uk:
                  'Вони збережені й показані для ручної перевірки. '
                  'Статус і причину вказано в кожній картці; на ціну '
                  'ці оголошення не впливають.',
            ),
            emptyLabel: '',
            offers: remainingParsedOffers,
            onOpenListing: onOpenListing,
            accent: colors.warning,
          ),
        ],
        const SizedBox(height: 18),
        _OutcomeBlock(
          key: const ValueKey('catalog-pricing-evidence-block'),
          title: context.localized(
            ru: 'Предварительно прошли ворота · пока не в расчёте',
            uk: 'Попередньо пройшли ворота · поки не в розрахунку',
          ),
          subtitle: context.localized(
            ru:
                'Даже успешный discovery-отбор не является рыночным '
                'наблюдением. Для цены нужна отдельная frozen evidence-запись.',
            uk:
                'Навіть успішний discovery-відбір не є ринковим '
                'спостереженням. Для ціни потрібен окремий frozen evidence-запис.',
          ),
          emptyLabel: context.localized(
            ru:
                'Discovery-кандидаты не допускаются к расчёту цены. '
                'Они показаны для проверки; причины перечислены выше.',
            uk:
                'Discovery-кандидати не допускаються до розрахунку ціни. '
                'Вони показані для перевірки; причини наведені вище.',
          ),
          offers: comparison.pricingEvidence,
          onOpenListing: onOpenListing,
          accent: colors.positive,
        ),
        const SizedBox(height: 20),
        _OutcomeBlock(
          key: const ValueKey('catalog-reference-only-block'),
          title: context.localized(
            ru: 'Показаны справочно · в расчёт не входят',
            uk: 'Показані довідково · у розрахунок не входять',
          ),
          subtitle: context.localized(
            ru:
                'Та же деталь, но уровень не определён или его нельзя '
                'привести к вашему. Проверьте по ссылке и решите сами.',
            uk:
                'Та сама деталь, але рівень не визначено або його не можна '
                'привести до вашого. Перевірте за посиланням і вирішіть самі.',
          ),
          emptyLabel: context.localized(
            ru: 'Справочных объявлений нет.',
            uk: 'Довідкових оголошень немає.',
          ),
          offers: comparison.referenceOnly,
          onOpenListing: onOpenListing,
          accent: colors.muted,
        ),
      ],
    );
  }
}

class _OutcomeBlock extends StatelessWidget {
  const _OutcomeBlock({
    required this.title,
    required this.subtitle,
    required this.emptyLabel,
    required this.offers,
    required this.onOpenListing,
    required this.accent,
    super.key,
  });

  final String title;
  final String subtitle;
  final String emptyLabel;
  final List<CatalogDiscoveredOffer> offers;
  final ValueChanged<String> onOpenListing;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Container(width: 3, height: 16, color: accent),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '$title · ${offers.length}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Padding(
          padding: const EdgeInsets.only(left: 11),
          child: Text(
            subtitle,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.muted),
          ),
        ),
        const SizedBox(height: 12),
        if (offers.isEmpty)
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              emptyLabel,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          )
        else
          ...offers.map(
            (offer) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _DiscoveredListingCard(
                offer: offer,
                onOpen: () => onOpenListing(offer.url),
              ),
            ),
          ),
      ],
    );
  }
}

class _DiscoveredListingCard extends StatelessWidget {
  const _DiscoveredListingCard({required this.offer, required this.onOpen});

  final CatalogDiscoveredOffer offer;
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

    return Material(
      color: colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(11),
        side: BorderSide(color: colors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        key: ValueKey('catalog-discovered-listing-${offer.discoveryOfferId}'),
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
                  color: colors.brandSoft,
                  borderRadius: BorderRadius.circular(9),
                ),
                alignment: Alignment.center,
                child: Icon(
                  Icons.travel_explore_rounded,
                  size: 19,
                  color: colors.brand,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      offer.title,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      [
                        offer.sellerName,
                        if ((offer.brand ?? '').isNotEmpty) offer.brand!,
                        if ((offer.sku ?? '').isNotEmpty) 'Арт. ${offer.sku}',
                        if ((offer.mpn ?? '').isNotEmpty) 'MPN ${offer.mpn}',
                        if ((offer.oeRaw ?? '').isNotEmpty) 'OE ${offer.oeRaw}',
                        if (offer.partNumbers.isNotEmpty)
                          'Код ${offer.partNumbers.join(', ')}',
                      ].join(' · '),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.muted),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 9,
                      runSpacing: 5,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          '${offer.salePrice.toStringAsFixed(2)} '
                          '${offer.currency}',
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(
                                fontFeatures: const [
                                  FontFeature.tabularFigures(),
                                ],
                              ),
                        ),
                        if (offer.referencePrice != null)
                          Text(
                            '${offer.referencePrice!.toStringAsFixed(2)} '
                            '${offer.currency}',
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(
                                  color: colors.muted,
                                  decoration: TextDecoration.lineThrough,
                                  fontFeatures: const [
                                    FontFeature.tabularFigures(),
                                  ],
                                ),
                          ),
                        _AvailabilityLabel(
                          color: availabilityColor,
                          label: availability,
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    _CandidateVerdictBadge(offer: offer),
                    const SizedBox(height: 5),
                    Text(
                      context.localized(
                        ru:
                            'Пройдено ворот: ${offer.passedGates.length} · '
                            'tier: ${offer.predictedTier.toUpperCase()}'
                            '${offer.titleContainsQuery ? ' · OE в заголовке' : ''}',
                        uk:
                            'Пройдено воріт: ${offer.passedGates.length} · '
                            'tier: ${offer.predictedTier.toUpperCase()}'
                            '${offer.titleContainsQuery ? ' · OE у заголовку' : ''}',
                      ),
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.muted),
                    ),
                    if (offer.selectionFlags.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        context.localized(
                          ru: 'Флаги: ${offer.selectionFlags.join(', ')}',
                          uk: 'Позначки: ${offer.selectionFlags.join(', ')}',
                        ),
                        style: Theme.of(
                          context,
                        ).textTheme.bodySmall?.copyWith(color: colors.warning),
                      ),
                    ],
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

class _CandidateVerdictBadge extends StatelessWidget {
  const _CandidateVerdictBadge({required this.offer});

  final CatalogDiscoveredOffer offer;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final (background, foreground) = switch (offer.selectionStatus) {
      'PRICING_EVIDENCE' => (colors.positiveSoft, colors.positive),
      'REJECTED' => (colors.negativeSoft, colors.negative),
      _ => (colors.warningSoft, colors.warning),
    };
    final label = switch (offer.selectionStatus) {
      'PRICING_EVIDENCE' => context.localized(
        ru: 'В расчёте цены',
        uk: 'У розрахунку ціни',
      ),
      'REJECTED' => context.localized(
        ru: 'Отброшен · ${_reasonLabel(context, offer.selectionReason)}',
        uk: 'Відкинуто · ${_reasonLabel(context, offer.selectionReason)}',
      ),
      _ => context.localized(
        ru: 'Справочно · ${_reasonLabel(context, offer.selectionReason)}',
        uk: 'Довідково · ${_reasonLabel(context, offer.selectionReason)}',
      ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
          color: foreground,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _PriceCalculationCard extends StatelessWidget {
  /// Shows the arithmetic, not only its conclusion.
  ///
  /// The prices listed are the ones already converted to our own level, so the
  /// customer can check the median by eye; when the engine stayed silent, the
  /// card says which guard stopped it instead of leaving a blank space.
  const _PriceCalculationCard({required this.comparison});

  final CatalogCompetitorComparison comparison;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final theme = Theme.of(context);
    final currency = comparison.currency ?? '';
    final normalized =
        comparison.items
            .map((offer) => offer.normalizedPrice ?? offer.price)
            .toList(growable: false)
          ..sort();
    final dispersion = comparison.dispersion;
    final grade = comparison.confidenceGrade;

    return Container(
      key: const ValueKey('catalog-price-calculation'),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.localized(
              ru:
                  'Расчёт: ${normalized.length} конкурентов вашего уровня, '
                  'цены приведены',
              uk:
                  'Розрахунок: ${normalized.length} конкурентів вашого рівня, '
                  'ціни приведені',
            ),
            style: theme.textTheme.labelMedium?.copyWith(color: colors.ink),
          ),
          if (normalized.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              normalized.map((price) => price.toStringAsFixed(0)).join('  ·  '),
              style: theme.textTheme.bodyMedium?.copyWith(
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ],
          const SizedBox(height: 8),
          _CalculationRow(
            label: context.localized(ru: 'Ваша цена', uk: 'Ваша ціна'),
            value: _price(comparison.currentPrice, currency),
          ),
          _CalculationRow(
            label: context.localized(
              ru: 'Справедливая цена',
              uk: 'Справедлива ціна',
            ),
            value: _price(comparison.fairPrice, currency),
          ),
          if (dispersion != null || grade != null)
            _CalculationRow(
              label: context.localized(
                ru: 'Разброс · уверенность',
                uk: 'Розкид · впевненість',
              ),
              value:
                  '${dispersion == null ? '—' : '${(dispersion * 100).toStringAsFixed(1)}%'}'
                  ' · ${grade ?? '—'}',
            ),
          const SizedBox(height: 8),
          Text(
            _verdict(context),
            style: theme.textTheme.bodySmall?.copyWith(
              color: comparison.recommendedPrice == null
                  ? colors.muted
                  : colors.positive,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  String _verdict(BuildContext context) {
    final recommended = comparison.recommendedPrice;
    final current = comparison.currentPrice;
    if (recommended != null && current != null && current > 0) {
      final delta = (recommended - current).ratioTo(current) * 100;
      return context.localized(
        ru:
            'Рекомендация: ${recommended.toStringAsFixed(0)} '
            '${comparison.currency ?? ''} (${delta >= 0 ? '+' : ''}'
            '${delta.toStringAsFixed(1)}%)',
        uk:
            'Рекомендація: ${recommended.toStringAsFixed(0)} '
            '${comparison.currency ?? ''} (${delta >= 0 ? '+' : ''}'
            '${delta.toStringAsFixed(1)}%)',
      );
    }
    for (final code in comparison.reasonCodes) {
      final explained = _silenceLabel(context, code);
      if (explained != null) return explained;
    }
    return context.localized(
      ru: 'Рекомендация не выдаётся.',
      uk: 'Рекомендація не видається.',
    );
  }
}

String? _silenceLabel(BuildContext context, String code) {
  return switch (code) {
    'PRICE_ALREADY_AT_OR_ABOVE_TARGET' => context.localized(
      ru: 'Рекомендация не выдаётся: вы уже в рынке.',
      uk: 'Рекомендація не видається: ви вже в ринку.',
    ),
    'CHANGE_BELOW_SIGNIFICANCE_THRESHOLD' => context.localized(
      ru: 'Рекомендация не выдаётся: изменение ниже порога значимости.',
      uk: 'Рекомендація не видається: зміна нижча за поріг значущості.',
    ),
    'STALE_NOT_BELOW_CHEAPEST_COMPETITOR' => context.localized(
      ru:
          'Рекомендация не выдаётся: товар лежалый и не дешевле самого '
          'дешёвого конкурента.',
      uk:
          'Рекомендація не видається: товар залежаний і не дешевший за '
          'найдешевшого конкурента.',
    ),
    'LOW_CONFIDENCE_BASIS' => context.localized(
      ru: 'Расчёт показан, но база слишком разнородна для рекомендации.',
      uk: 'Розрахунок показано, але база надто різнорідна для рекомендації.',
    ),
    'TOO_FEW_PRICING_EVIDENCE' => context.localized(
      ru: 'Рекомендация не выдаётся: меньше трёх приведённых цен.',
      uk: 'Рекомендація не видається: менше трьох приведених цін.',
    ),
    'ROUNDING_REMOVED_THE_CHANGE' => context.localized(
      ru: 'Рекомендация не выдаётся: после округления изменения не осталось.',
      uk: 'Рекомендація не видається: після округлення зміни не залишилось.',
    ),
    _ => null,
  };
}

class _CalculationRow extends StatelessWidget {
  const _CalculationRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.muted),
            ),
          ),
          Text(
            value,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: colors.ink,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}

String _price(DecimalValue? value, String currency) {
  if (value == null) return '—';
  return '${value.toStringAsFixed(0)} $currency'.trim();
}

class _CoverageNotice extends StatelessWidget {
  const _CoverageNotice({required this.comparison});

  final CatalogCompetitorComparison comparison;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final total = comparison.promReportedTotal ?? 0;
    final loaded = comparison.discoveryRetrievedCount;
    final ratio = comparison.coverageRatio;
    final percent = ratio == null
        ? '—'
        : '${(ratio * 100).toStringAsFixed(1)}%';
    final isPageLimit =
        {
          'SEARCH_PAGE_LIMIT',
          'SEARCH_PAGE_HARD_CAP',
        }.contains(comparison.coverageReason) &&
        comparison.unfetchedCount > 0;
    final reason = isPageLimit
        ? context.localized(
            ru:
                'Не загружено ${comparison.unfetchedCount}: достигнут '
                'защитный предел ${comparison.searchPageLimit} страниц.',
            uk:
                'Не завантажено ${comparison.unfetchedCount}: досягнуто '
                'захисної межі ${comparison.searchPageLimit} сторінок.',
          )
        : context.localized(
            ru: 'Причина покрытия: ${comparison.coverageReason ?? 'неизвестна'}.',
            uk: 'Причина покриття: ${comparison.coverageReason ?? 'невідома'}.',
          );
    return Container(
      key: const ValueKey('catalog-discovery-coverage'),
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: isPageLimit ? colors.warningSoft : colors.surfaceMuted,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        context.localized(
          ru:
              'Покрытие Prom: $loaded из $total ($percent), запросов: '
              '${comparison.searchPagesFetched}. $reason',
          uk:
              'Покриття Prom: $loaded із $total ($percent), запитів: '
              '${comparison.searchPagesFetched}. $reason',
        ),
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          color: isPageLimit ? colors.warning : colors.muted,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _SelectionHistogram extends StatelessWidget {
  const _SelectionHistogram({required this.comparison});

  final CatalogCompetitorComparison comparison;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      key: const ValueKey('catalog-discovery-histogram'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            context.localized(
              ru:
                  'Результат ворот: в расчёте '
                  '${comparison.pricingEvidenceCount} · справочно '
                  '${comparison.referenceOnlyCount} · отброшено '
                  '${comparison.rejectedCandidateCount}',
              uk:
                  'Результат воріт: у розрахунку '
                  '${comparison.pricingEvidenceCount} · довідково '
                  '${comparison.referenceOnlyCount} · відкинуто '
                  '${comparison.rejectedCandidateCount}',
            ),
            style: Theme.of(
              context,
            ).textTheme.labelMedium?.copyWith(color: colors.ink),
          ),
          const SizedBox(height: 8),
          ...comparison.selectionHistogram.entries.map(
            (entry) => Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _histogramLabel(context, entry.key),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                  Text(
                    '${entry.value}',
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: colors.ink,
                      fontFeatures: const [FontFeature.tabularFigures()],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
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
                        _AvailabilityLabel(
                          color: availabilityColor,
                          label: availability,
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

class _AvailabilityLabel extends StatelessWidget {
  const _AvailabilityLabel({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Text.rich(
      TextSpan(
        children: [
          WidgetSpan(
            alignment: PlaceholderAlignment.middle,
            child: Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
          ),
          TextSpan(text: '  $label'),
        ],
      ),
      style: Theme.of(context).textTheme.bodySmall,
      softWrap: true,
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
  const _EmptyCompetitors({
    required this.hasComparison,
    required this.hasDiscovery,
  });

  final bool hasComparison;
  final bool hasDiscovery;

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
                : hasDiscovery
                ? context.localized(
                    ru:
                        'Ни один найденный кандидат пока не допущен к '
                        'автоматическому сравнению. Поисковая выдача показана '
                        'ниже отдельно.',
                    uk:
                        'Жодного знайденого кандидата поки не допущено до '
                        'автоматичного порівняння. Пошукову видачу показано '
                        'нижче окремо.',
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

String _histogramLabel(BuildContext context, String key) {
  final separator = key.indexOf(':');
  if (separator < 0) return key;
  final status = key.substring(0, separator);
  final reason = key.substring(separator + 1);
  final prefix = switch (status) {
    'PRICING_EVIDENCE' => context.localized(
      ru: 'В расчёте',
      uk: 'У розрахунку',
    ),
    'REJECTED' => context.localized(ru: 'Отброшен', uk: 'Відкинуто'),
    _ => context.localized(ru: 'Справочно', uk: 'Довідково'),
  };
  if (reason == 'OK') return prefix;
  return '$prefix · ${_reasonLabel(context, reason)}';
}

String _reasonLabel(BuildContext context, String reason) {
  if (reason.startsWith('VARIANT_MISMATCH:')) {
    final axis = reason.split(':').last;
    return context.localized(
      ru: 'не совпадает вариант ($axis)',
      uk: 'не збігається варіант ($axis)',
    );
  }
  return switch (reason) {
    'OK' => context.localized(ru: 'ворота пройдены', uk: 'ворота пройдено'),
    'OWN_SELLER' => context.localized(
      ru: 'собственный магазин',
      uk: 'власний магазин',
    ),
    'DISMANTLER_SELLER' => context.localized(
      ru: 'продавец-разборка',
      uk: 'продавець-розбірка',
    ),
    'USED' => context.localized(ru: 'товар б/у', uk: 'товар вживаний'),
    'CONDITION_CONFLICT' => context.localized(
      ru: 'конфликт состояния',
      uk: 'конфлікт стану',
    ),
    'REMANUFACTURED' => context.localized(
      ru: 'восстановленный товар',
      uk: 'відновлений товар',
    ),
    'OEM_NOT_FOUND' => context.localized(
      ru: 'OE не подтверждён',
      uk: 'OE не підтверджено',
    ),
    'CATEGORY_NOT_AUTOPARTS' => context.localized(
      ru: 'не автозапчасть (категория Prom)',
      uk: 'не автозапчастина (категорія Prom)',
    ),
    'WEAK_NUMERIC_IDENTITY' => context.localized(
      ru: 'короткий числовой OE найден только в тексте — возможна коллизия',
      uk: 'короткий числовий OE знайдено лише в тексті — можлива колізія',
    ),
    'CATEGORY_OUTLIER_MAJORITY_VOTE' => context.localized(
      ru: 'категория не совпадает с выдачей',
      uk: 'категорія не збігається з видачею',
    ),
    'PACK_MISMATCH' => context.localized(
      ru: 'не совпадает упаковка',
      uk: 'не збігається пакування',
    ),
    'BRAND_MISMATCH' => context.localized(
      ru: 'не совпадает марка автомобиля',
      uk: 'не збігається марка автомобіля',
    ),
    'APPLICABILITY_MISMATCH' => context.localized(
      ru: 'не совпадает применимость',
      uk: 'не збігається застосовність',
    ),
    'TIER_UNKNOWN' => context.localized(
      ru: 'уровень бренда не определён',
      uk: 'рівень бренду не визначено',
    ),
    'OWN_BRAND' => context.localized(
      ru: 'наш собственный бренд',
      uk: 'наш власний бренд',
    ),
    'PREMIUM_NOT_CALIBRATED' => context.localized(
      ru: 'коэффициент уровня не откалиброван',
      uk: 'коефіцієнт рівня не відкалібровано',
    ),
    'USED_BY_TIER' => context.localized(
      ru: 'tier определён как б/у',
      uk: 'tier визначено як вживаний',
    ),
    'SAME_BRAND_KEMP' => context.localized(
      ru: 'магазин сети KEMP',
      uk: 'магазин мережі KEMP',
    ),
    'LEGACY_UNCLASSIFIED' => context.localized(
      ru: 'старый запуск без классификации',
      uk: 'старий запуск без класифікації',
    ),
    _ => reason,
  };
}
