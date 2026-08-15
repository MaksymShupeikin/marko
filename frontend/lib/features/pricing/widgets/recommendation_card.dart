part of '../recommendations_page.dart';

class _RecommendationCard extends ConsumerStatefulWidget {
  const _RecommendationCard({
    required this.recommendation,
    required this.canAdministerWorkspace,
    required this.initiallyExpanded,
    required this.onOpenDeepLink,
  });

  final PricingRecommendation recommendation;
  final bool canAdministerWorkspace;
  final bool initiallyExpanded;
  final ValueChanged<String>? onOpenDeepLink;

  @override
  ConsumerState<_RecommendationCard> createState() =>
      _RecommendationCardState();
}

class _RecommendationCardState extends ConsumerState<_RecommendationCard> {
  Future<List<RecommendationEvidence>>? _evidence;
  bool _savingDecision = false;
  bool _verifyingReplay = false;
  RecommendationReplay? _replay;

  @override
  void initState() {
    super.initState();
    if (widget.initiallyExpanded) _evidence = _loadEvidence();
  }

  @override
  Widget build(BuildContext context) {
    final recommendation = widget.recommendation;
    final colors = MarkoTheme.of(context);
    // Каждая кнопка ниже — аутентифицированный запрос. После признанной
    // истёкшей сессии любая из них может только повторить тот же 401, поэтому
    // предлагать их — значит предлагать ошибку вместо входа.
    final sessionExpired = ref.watch(markoSessionExpiredProvider);
    final (foreground, background, icon) = recommendation.isRaise
        ? (colors.positive, colors.positiveSoft, Icons.trending_up_rounded)
        : recommendation.isLower
        ? (colors.warning, colors.warningSoft, Icons.trending_down_rounded)
        : recommendation.needsReview
        ? (colors.negative, colors.negativeSoft, Icons.fact_check_outlined)
        : (colors.muted, colors.surfaceMuted, Icons.horizontal_rule_rounded);
    return MarkoPanel(
      padding: EdgeInsets.zero,
      interactive: true,
      child: ExpansionTile(
        initiallyExpanded: widget.initiallyExpanded,
        onExpansionChanged: (expanded) {
          if (expanded && _evidence == null) _refreshEvidence();
        },
        tilePadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
        childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        leading: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: background,
            borderRadius: BorderRadius.circular(9),
          ),
          alignment: Alignment.center,
          child: Icon(icon, color: foreground, size: 21),
        ),
        title: LayoutBuilder(
          builder: (context, constraints) {
            final badge = _ActionBadge(
              label: _actionLabel(context, recommendation.action),
              foreground: foreground,
              background: background,
            );
            final compact =
                constraints.maxWidth < 360 ||
                MediaQuery.textScalerOf(context).scale(14) >= 18;
            if (compact) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    recommendation.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 6),
                  Align(alignment: Alignment.centerLeft, child: badge),
                ],
              );
            }
            return Row(
              children: [
                Expanded(
                  child: Text(
                    recommendation.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                const SizedBox(width: 12),
                badge,
              ],
            );
          },
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 7),
          child: Wrap(
            spacing: 14,
            runSpacing: 5,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                _identityLabel(recommendation),
                style: Theme.of(context).textTheme.bodySmall,
              ),
              _CatalogEvidenceBadge(
                evidence: recommendation.catalogDataEvidence,
              ),
              Text(
                _priceDecision(context, recommendation),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        children: [
          const Divider(),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 680;
              final evidence = _Evidence(recommendation: recommendation);
              final health = _DataHealth(recommendation: recommendation);
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [evidence, const SizedBox(height: 18), health],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: evidence),
                  const SizedBox(width: 28),
                  Expanded(child: health),
                ],
              );
            },
          ),
          const SizedBox(height: 16),
          _CatalogDataEvidencePanel(recommendation: recommendation),
          if (recommendation.hasAdvisoryPrice) ...[
            const SizedBox(height: 16),
            CustomerPriceAdvisory(recommendation: recommendation),
          ],
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                onPressed: _savingDecision || sessionExpired
                    ? null
                    : () => _recordDecision(
                        recommendation.automaticEligible &&
                                recommendation.recommendedPrice != null
                            ? 'accepted'
                            : 'overridden',
                      ),
                icon: Icon(
                  recommendation.automaticEligible &&
                          recommendation.recommendedPrice != null
                      ? Icons.check_rounded
                      : Icons.edit_outlined,
                  size: 18,
                ),
                label: Text(
                  recommendation.automaticEligible &&
                          recommendation.recommendedPrice != null
                      ? context.localized(ru: 'Принять', uk: 'Прийняти')
                      : recommendation.automaticEligible
                      ? context.localized(ru: 'Своя цена', uk: 'Своя ціна')
                      : context.localized(
                          ru: 'Ручная цена (audit)',
                          uk: 'Ручна ціна (audit)',
                        ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: widget.canAdministerWorkspace && !sessionExpired
                    ? _editContext
                    : null,
                icon: const Icon(Icons.inventory_2_outlined, size: 18),
                label: Text(
                  context.localized(
                    ru: 'Контекст склада',
                    uk: 'Контекст складу',
                  ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: _verifyingReplay || sessionExpired
                    ? null
                    : _verifyReplay,
                icon: _verifyingReplay
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.verified_outlined, size: 18),
                label: Text(
                  context.localized(
                    ru: 'Проверить replay',
                    uk: 'Перевірити replay',
                  ),
                ),
              ),
              if (recommendation.automaticEligible &&
                  recommendation.recommendedPrice != null)
                OutlinedButton.icon(
                  onPressed: _savingDecision || sessionExpired
                      ? null
                      : () => _recordDecision('overridden'),
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: Text(
                    context.localized(ru: 'Своя цена', uk: 'Своя ціна'),
                  ),
                ),
              TextButton(
                onPressed: _savingDecision || sessionExpired
                    ? null
                    : () => _recordDecision('rejected'),
                child: Text(
                  context.localized(ru: 'Отклонить', uk: 'Відхилити'),
                ),
              ),
              if (widget.onOpenDeepLink != null)
                OutlinedButton.icon(
                  onPressed: () => widget.onOpenDeepLink!(recommendation.id),
                  icon: const Icon(Icons.link_rounded, size: 18),
                  label: Text(
                    context.localized(
                      ru: 'Постоянная ссылка',
                      uk: 'Постійне посилання',
                    ),
                  ),
                ),
            ],
          ),
          if (_replay != null) ...[
            const SizedBox(height: 12),
            _ReplayStatus(replay: _replay!),
          ],
          if (_evidence != null) ...[
            const SizedBox(height: 18),
            const Divider(),
            const SizedBox(height: 14),
            _MarketEvidenceList(
              future: _evidence!,
              normalizedOffers: recommendation.normalizedOffersById,
              marketMinimum: recommendation.advisoryMarketMinimum,
              targetBandLow:
                  recommendation.advisoryTargetBandLow ??
                  recommendation.lowerBound,
              targetBandHigh:
                  recommendation.advisoryTargetBandHigh ??
                  recommendation.upperBound,
              onOverride: widget.canAdministerWorkspace && !sessionExpired
                  ? _overrideTier
                  : null,
              onComparabilityFeedback:
                  widget.canAdministerWorkspace && !sessionExpired
                  ? _recordComparabilityFeedback
                  : null,
              onComparabilityReview:
                  widget.canAdministerWorkspace && !sessionExpired
                  ? _rerunComparabilityReview
                  : null,
            ),
            const SizedBox(height: 18),
            const Divider(),
            const SizedBox(height: 14),
            FitmentCandidatesPanel(
              catalogItemId: recommendation.catalogItemId,
              canAdministerWorkspace: widget.canAdministerWorkspace,
            ),
          ],
        ],
      ),
    );
  }

  String _identityLabel(PricingRecommendation recommendation) {
    final identity = <String>[];
    if (recommendation.oe.trim().isNotEmpty) {
      identity.add('OE ${recommendation.oe}');
    } else if (recommendation.mpn?.trim().isNotEmpty ?? false) {
      identity.add('MPN ${recommendation.mpn}');
    } else if (recommendation.searchIdentity?.trim().isNotEmpty ?? false) {
      identity.add('Поиск ${recommendation.searchIdentity}');
    }
    final suffix = identity.isEmpty ? '' : ' · ${identity.join(' · ')}';
    return 'SKU ${recommendation.sku}$suffix';
  }

  String _priceDecision(BuildContext context, PricingRecommendation item) {
    final advisory = item.recommendedPrice == null && item.hasAdvisoryPrice;
    final target = item.recommendedPrice ?? item.advisoryRecommendedPrice;
    if (target == null && !item.automaticEligible) {
      return context.localized(
        ru: '${_recommendationMoney(item, item.currentPrice)} — автоцена не сформирована',
        uk: '${_recommendationMoney(item, item.currentPrice)} — автоціну не сформовано',
      );
    }
    if (target == null) {
      return context.localized(
        ru: '${_recommendationMoney(item, item.currentPrice)} — без изменений',
        uk: '${_recommendationMoney(item, item.currentPrice)} — без змін',
      );
    }
    final change =
        item.absoluteRecommendedChange ?? (target - item.currentPrice).abs();
    final percent =
        item.percentageRecommendedChange ??
        (item.currentPrice.isZero ? 0 : change.ratioTo(item.currentPrice));
    final sign = target >= item.currentPrice ? '+' : '−';
    final suffix = advisory
        ? context.localized(
            ru: ' · ориентир, требует проверки',
            uk: ' · орієнтир, потребує перевірки',
          )
        : '';
    return '${_recommendationMoney(item, item.currentPrice)} → '
        '${_recommendationMoney(item, target)} · '
        '$sign${_recommendationMoney(item, change)} '
        '(${(percent * 100).toStringAsFixed(1)}%)$suffix';
  }

  Future<void> _editContext() async {
    final recommendation = widget.recommendation;
    final values = await showCatalogContextDialog(
      context,
      initialStatus: recommendation.stockStatus,
      initialContext: recommendation.contextSnapshot,
    );
    if (values == null || !mounted) return;
    final saved = await ref
        .read(recommendationsControllerProvider.notifier)
        .saveCatalogContext(recommendation.catalogItemId, values);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          saved
              ? context.localized(
                  ru: 'Контекст сохранён и будет учтён в следующем прогоне.',
                  uk: 'Контекст збережено, його буде враховано в наступному прогоні.',
                )
              : context.localized(
                  ru: 'Не удалось сохранить контекст.',
                  uk: 'Не вдалося зберегти контекст.',
                ),
        ),
      ),
    );
  }

  Future<void> _recordDecision(String decision) async {
    final values = await showRecommendationDecisionDialog(
      context,
      recommendation: widget.recommendation,
      decision: decision,
    );
    if (values == null || !mounted) return;
    setState(() => _savingDecision = true);
    final saved = await ref
        .read(recommendationsControllerProvider.notifier)
        .recordDecision(widget.recommendation.id, values);
    if (!mounted) return;
    setState(() => _savingDecision = false);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          saved
              ? context.localized(
                  ru: 'Решение записано в audit trail.',
                  uk: 'Рішення записано в audit trail.',
                )
              : context.localized(
                  ru: 'Не удалось записать решение.',
                  uk: 'Не вдалося записати рішення.',
                ),
        ),
      ),
    );
  }

  Future<void> _verifyReplay() async {
    setState(() => _verifyingReplay = true);
    try {
      final replay = await ref
          .read(pricingApiProvider)
          .verifyReplay(widget.recommendation.id);
      if (!mounted) return;
      setState(() {
        _replay = replay;
        _verifyingReplay = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _verifyingReplay = false);
      // Истёкшая сессия — не «replay недоступен»: воспроизведение расчёта
      // никуда не делось, доступа к нему нет. Страница отвечает на это одним
      // предложением и одной кнопкой, а снекбар с английской строкой бэкенда
      // уехал бы через четыре секунды, ничего не предложив.
      if (ref.classifySessionExpiry(error)) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Replay недоступен: $error',
              uk: 'Replay недоступний: $error',
            ),
          ),
        ),
      );
    }
  }

  Future<void> _overrideTier(RecommendationEvidence evidence) async {
    final override = await showTierOverrideDialog(
      context,
      currentTier: evidence.tier,
    );
    if (override == null || !mounted) return;
    try {
      await ref
          .read(pricingApiProvider)
          .overrideTier(
            evidence.observationId,
            tier: override.tier,
            reason: override.reason,
          );
      if (!mounted) return;
      _refreshEvidence();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Tier override сохранён. Новый run пересчитает цену.',
              uk: 'Tier override збережено. Новий run перерахує ціну.',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      if (ref.classifySessionExpiry(error)) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Не удалось сохранить: $error',
              uk: 'Не вдалося зберегти: $error',
            ),
          ),
        ),
      );
    }
  }

  Future<void> _recordComparabilityFeedback(
    RecommendationEvidence evidence,
  ) async {
    final review = evidence.llmReview;
    if (review == null) return;
    final values = await showComparabilityFeedbackDialog(
      context,
      review: review,
    );
    if (values == null || !mounted) return;
    try {
      await ref
          .read(pricingApiProvider)
          .recordComparabilityFeedback(review.reviewId, values);
      if (!mounted) return;
      _refreshEvidence();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru:
                  'Разметка сохранена. Она станет эталоном и будет учтена '
                  'в следующем расчёте.',
              uk:
                  'Розмітку збережено. Вона стане еталоном і буде врахована '
                  'в наступному розрахунку.',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      _showEvidenceError(error);
    }
  }

  Future<void> _rerunComparabilityReview(
    RecommendationEvidence evidence,
  ) async {
    try {
      await ref
          .read(pricingApiProvider)
          .reviewComparability(evidence.observationId, force: true);
      if (!mounted) return;
      _refreshEvidence();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru:
                  'Новая проверка сохранена. Текущая рекомендация не '
                  'переписана; результат войдёт в следующий расчёт.',
              uk:
                  'Нову перевірку збережено. Поточну рекомендацію не '
                  'перезаписано; результат увійде до наступного розрахунку.',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      _showEvidenceError(error);
    }
  }

  void _refreshEvidence() {
    ref
        .read(recommendationsControllerProvider.notifier)
        .refreshEvidence(widget.recommendation.id);
    setState(() => _evidence = _loadEvidence());
  }

  /// Доказательства грузятся через ту же классификацию, что и всё остальное.
  ///
  /// [FutureBuilder] не может поднять состояние приложения из `build`, поэтому
  /// 401 признаётся здесь — там, где он приходит. Ошибка при этом не
  /// проглатывается: список сам решает, что показать вместо строки бэкенда.
  Future<List<RecommendationEvidence>> _loadEvidence() {
    return ref
        .read(recommendationsControllerProvider.notifier)
        .evidenceFor(widget.recommendation.id);
  }

  void _showEvidenceError(Object error) {
    if (ref.classifySessionExpiry(error)) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          context.localized(
            ru: 'Не удалось сохранить проверку: $error',
            uk: 'Не вдалося зберегти перевірку: $error',
          ),
        ),
      ),
    );
  }
}
