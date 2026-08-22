import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api_client.dart';
import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../../../core/marko_motion.dart';
import '../../../core/marko_ui.dart';
import '../../../core/presentation_formatters.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../catalog_models.dart';
import 'catalog_competitor_section.dart';
import 'catalog_recommendation_banner.dart';

Future<void> showCatalogProductDetailsSheet({
  required BuildContext context,
  required CatalogProduct product,
  required Future<CatalogCompetitorComparison> Function() loadCompetitors,
  Future<CatalogCompetitorComparison> Function()? discoverCompetitors,
  Future<CatalogMatchRun?> Function()? startMatch,
  Future<CatalogMatchRun> Function(String matchRunId)? matchStatus,
  VoidCallback? onOpenPricing,
  ValueChanged<String>? onOpenListing,
}) {
  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: context.localized(ru: 'Закрыть', uk: 'Закрити'),
    barrierColor: Colors.black.withValues(alpha: 0.22),
    transitionDuration: const Duration(milliseconds: 320),
    pageBuilder: (dialogContext, _, _) => CatalogProductDetailsSheet(
      product: product,
      loadCompetitors: loadCompetitors,
      discoverCompetitors: discoverCompetitors,
      startMatch: startMatch,
      matchStatus: matchStatus,
      onOpenPricing: onOpenPricing == null
          ? null
          : () {
              Navigator.of(dialogContext).pop();
              onOpenPricing();
            },
      onOpenListing: onOpenListing,
    ),
    transitionBuilder: (context, animation, secondaryAnimation, child) {
      final curved = CurvedAnimation(
        parent: animation,
        curve: Curves.easeOutCubic,
        reverseCurve: Curves.easeInCubic,
      );
      return FadeTransition(
        opacity: Tween<double>(begin: 0.7, end: 1).animate(curved),
        child: SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(1, 0),
            end: Offset.zero,
          ).animate(curved),
          child: child,
        ),
      );
    },
  );
}

class CatalogProductDetailsSheet extends StatefulWidget {
  const CatalogProductDetailsSheet({
    required this.product,
    required this.loadCompetitors,
    this.discoverCompetitors,
    this.startMatch,
    this.matchStatus,
    this.onOpenPricing,
    this.onOpenListing,
    super.key,
  });

  final CatalogProduct product;
  final Future<CatalogCompetitorComparison> Function() loadCompetitors;
  final Future<CatalogCompetitorComparison> Function()? discoverCompetitors;

  /// Запуск платного отсева. `null` в результате означает, что дорожка
  /// выключена в этой среде — карточка тогда работает как прежде.
  final Future<CatalogMatchRun?> Function()? startMatch;
  final Future<CatalogMatchRun> Function(String matchRunId)? matchStatus;
  final VoidCallback? onOpenPricing;
  final ValueChanged<String>? onOpenListing;

  @override
  State<CatalogProductDetailsSheet> createState() =>
      _CatalogProductDetailsSheetState();
}

class _CatalogProductDetailsSheetState
    extends State<CatalogProductDetailsSheet> {
  final ScrollController _scrollController = ScrollController();
  late Future<_CatalogComparisonLoad> _comparison;
  bool _isDiscovering = false;
  String? _discoveryError;
  bool _isMatching = false;
  bool _matchRequested = false;
  String? _matchError;
  CatalogMatchRun? _matchRun;
  bool _matchCancelled = false;
  bool _stalePromptShown = false;

  /// Срок годности сохранённого сбора: старше — предлагаем повторную
  /// проверку сопоставления и оценки (требование заказчика, 2026-08-21).
  static const Duration _staleAfter = Duration(days: 14);

  @override
  void initState() {
    super.initState();
    _comparison = _loadComparison();
    _comparison.then(_maybeWarnStale);
  }

  @override
  void dispose() {
    // Опрос состояния переживёт закрытие карточки, если его не остановить:
    // работа идёт минутами, а виджета к тому времени уже нет.
    _matchCancelled = true;
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final viewportWidth = MediaQuery.sizeOf(context).width;
    final panelWidth = math.min(viewportWidth, 500.0);

    return SafeArea(
      child: Align(
        alignment: Alignment.centerRight,
        child: Material(
          key: const ValueKey('catalog-product-details-sheet'),
          color: colors.surface,
          elevation: 24,
          clipBehavior: Clip.antiAlias,
          shape: RoundedRectangleBorder(
            borderRadius: viewportWidth > 520
                ? const BorderRadius.only(
                    topLeft: Radius.circular(18),
                    bottomLeft: Radius.circular(18),
                  )
                : BorderRadius.zero,
            side: BorderSide(color: colors.border),
          ),
          child: SizedBox(
            width: panelWidth,
            height: double.infinity,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const _SheetHeader(),
                Divider(color: colors.border),
                Expanded(
                  child: SingleChildScrollView(
                    controller: _scrollController,
                    padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
                    child: FutureBuilder<_CatalogComparisonLoad>(
                      future: _comparison,
                      builder: (context, snapshot) {
                        final result =
                            snapshot.connectionState == ConnectionState.done
                            ? snapshot.requireData
                            : null;
                        final comparison = result?.comparison;
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            if (_matchRequested && comparison != null) ...[
                              CatalogRecommendationBanner(
                                comparison: comparison,
                                onOpenPricing: widget.onOpenPricing,
                              ),
                              const SizedBox(height: 20),
                            ],
                            _ProductSummary(product: widget.product),
                            const SizedBox(height: 24),
                            if (result == null)
                              const CatalogCompetitorLoading()
                            else if (result.error case final error?)
                              MarkoAsyncErrorView(
                                error: error,
                                forbiddenResourceRu:
                                    'конкурентным объявлениям этого товара',
                                forbiddenResourceUk:
                                    'конкурентних оголошень цього товару',
                                onRetry: _retry,
                                padding: EdgeInsets.zero,
                              )
                            else
                              CatalogCompetitorSection(
                                comparison: comparison!,
                                onOpenListing: _openListing,
                              ),
                          ],
                        );
                      },
                    ),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.fromLTRB(20, 14, 20, 18),
                  decoration: BoxDecoration(
                    color: colors.surface,
                    border: Border(top: BorderSide(color: colors.border)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (widget.discoverCompetitors != null) ...[
                        FilledButton.icon(
                          key: const ValueKey('catalog-details-discover'),
                          onPressed: _isDiscovering ? null : _discover,
                          icon: _isDiscovering
                              ? const SizedBox.square(
                                  dimension: 17,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(
                                  Icons.travel_explore_rounded,
                                  size: 19,
                                ),
                          label: Text(
                            _isDiscovering
                                ? context.localized(
                                    ru: 'Собираем объявления…',
                                    uk: 'Збираємо оголошення…',
                                  )
                                : context.localized(
                                    ru: 'Собрать объявления с Prom.ua',
                                    uk: 'Зібрати оголошення з Prom.ua',
                                  ),
                          ),
                        ),
                        if (_discoveryError != null) ...[
                          const SizedBox(height: 7),
                          Text(
                            _discoveryError!,
                            textAlign: TextAlign.center,
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(
                                  color: Theme.of(context).colorScheme.error,
                                ),
                          ),
                        ],
                        const SizedBox(height: 9),
                      ],
                      OutlinedButton.icon(
                        key: const ValueKey('catalog-details-compare'),
                        onPressed: _isMatching ? null : _match,
                        style: OutlinedButton.styleFrom(
                          backgroundColor: colors.surface,
                          foregroundColor: colors.ink,
                          side: BorderSide(color: colors.border),
                        ),
                        icon: _isMatching
                            ? const SizedBox.square(
                                dimension: 17,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.price_check_rounded, size: 19),
                        label: Text(
                          _isMatching
                              ? _matchProgressLabel(context)
                              : context.localized(
                                  ru: 'Сопоставить и рассчитать цену',
                                  uk: 'Зіставити та розрахувати ціну',
                                ),
                        ),
                      ),
                      if (_matchError != null) ...[
                        const SizedBox(height: 7),
                        Text(
                          _matchError!,
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(
                                color: Theme.of(context).colorScheme.error,
                              ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _matchProgressLabel(BuildContext context) {
    final run = _matchRun;
    if (run == null || run.groupCount == 0) {
      return context.localized(ru: 'Сопоставляем…', uk: 'Зіставляємо…');
    }
    // Число говорит оператору, что работа идёт и сколько её осталось: отсев
    // длится минутами, и молчащая кнопка выглядит зависшей.
    return context.localized(
      ru: 'Сопоставляем: ${run.reviewedGroupCount} из ${run.groupCount}…',
      uk: 'Зіставляємо: ${run.reviewedGroupCount} з ${run.groupCount}…',
    );
  }

  void _retry() {
    setState(() {
      _comparison = _loadComparison();
    });
  }

  Future<_CatalogComparisonLoad> _loadComparison() async {
    try {
      return _CatalogComparisonLoad.success(await widget.loadCompetitors());
    } catch (error) {
      return _CatalogComparisonLoad.failure(error);
    }
  }

  void _maybeWarnStale(_CatalogComparisonLoad load) {
    if (!mounted || _stalePromptShown) return;
    final comparison = load.comparison;
    final collectedAt = comparison?.discoveredAt;
    if (collectedAt == null) return;
    if (DateTime.now().difference(collectedAt) < _staleAfter) return;
    _stalePromptShown = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      unawaited(_showStaleDialog(collectedAt));
    });
  }

  Future<void> _showStaleDialog(DateTime collectedAt) async {
    final canRefresh = widget.discoverCompetitors != null;
    final refresh = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        key: const ValueKey('catalog-stale-discovery-dialog'),
        title: Text(
          dialogContext.localized(
            ru: 'Данные устарели',
            uk: 'Дані застаріли',
          ),
        ),
        content: Text(
          dialogContext.localized(
            ru:
                'Объявления по этому товару собраны '
                '${formatLocalDateTime(collectedAt)} — больше двух недель '
                'назад. Нужно сделать ещё одну проверку сопоставления и '
                'оценки товаров.',
            uk:
                'Оголошення за цим товаром зібрані '
                '${formatLocalDateTime(collectedAt)} — понад два тижні тому. '
                'Потрібно зробити ще одну перевірку зіставлення та оцінки '
                'товарів.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(
              dialogContext.localized(ru: 'Позже', uk: 'Пізніше'),
            ),
          ),
          if (canRefresh)
            FilledButton(
              key: const ValueKey('catalog-stale-discovery-refresh'),
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: Text(
                dialogContext.localized(
                  ru: 'Проверить заново',
                  uk: 'Перевірити заново',
                ),
              ),
            ),
        ],
      ),
    );
    if (refresh == true && mounted) {
      await _discover();
      if (mounted && _discoveryError == null) {
        await _match();
      }
    }
  }

  Future<void> _match() async {
    if (_isMatching) return;
    setState(() {
      _isMatching = true;
      _matchError = null;
      _matchRun = null;
    });
    try {
      final start = widget.startMatch;
      final poll = widget.matchStatus;
      Object? startFailure;
      if (start != null && poll != null) {
        CatalogMatchRun? started;
        try {
          // `null` значит «дорожка выключена в этой среде».
          started = await start();
        } catch (error) {
          if (markoIsSessionExpired(error)) rethrow;
          // Отсев моделью — вторая ступень, а не условие первой. Если её не
          // удалось начать, оператор всё равно обязан увидеть собранное:
          // ровно та же ошибка стоила этой карточке кнопки сбора 22.08.
          startFailure = error;
        }
        if (started != null) {
          final finished = await _awaitMatch(started, poll);
          if (finished == null) return;
          if (finished.status == 'failed') {
            throw StateError(
              finished.errorDetail ?? finished.errorCode ?? 'match failed',
            );
          }
        }
      }
      final result = await widget.loadCompetitors();
      if (!mounted) return;
      setState(() {
        _comparison = Future.value(_CatalogComparisonLoad.success(result));
        _matchRequested = true;
        _isMatching = false;
        // Оператору — одна короткая фраза, а не текст исключения: собранное
        // он всё равно видит, а разбираться с причиной будет не он.
        _matchError = startFailure == null
            ? null
            : context.localized(
                ru: 'Отсев моделью недоступен — показано собранное.',
                uk: 'Відсів моделлю недоступний — показано зібране.',
              );
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !_scrollController.hasClients) return;
        _scrollController.animateTo(
          0,
          duration: MarkoMotion.enter,
          curve: MarkoMotion.enterCurve,
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isMatching = false;
        _matchError = context.localized(
          ru: 'Сопоставление не выполнено: $error',
          uk: 'Зіставлення не виконано: $error',
        );
      });
    }
  }

  Future<void> _discover() async {
    final discover = widget.discoverCompetitors;
    if (discover == null || _isDiscovering) return;
    setState(() {
      _isDiscovering = true;
      _discoveryError = null;
    });
    try {
      final result = await discover();
      if (!mounted) return;
      setState(() {
        _comparison = Future.value(_CatalogComparisonLoad.success(result));
        _isDiscovering = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isDiscovering = false;
        // Обрыв по времени — не отказ сбора: он живёт на сервере и
        // доводится до конца независимо от клиента. Обещать оператору
        // неудачу там, где объявления уже сохранены, нельзя.
        _discoveryError = error is TimeoutException
            ? context.localized(
                ru:
                    'Сбор идёт дольше обычного и продолжается на сервере. '
                    'Откройте карточку заново через пару минут — '
                    'собранные объявления появятся здесь.',
                uk:
                    'Збір триває довше за звичайне і продовжується на '
                    'сервері. Відкрийте картку заново за пару хвилин — '
                    'зібрані оголошення з’являться тут.',
              )
            : context.localized(
                ru: 'Сбор не завершён: $error',
                uk: 'Збір не завершено: $error',
              );
      });
    }
  }

  /// Дождаться конца отсева, спрашивая сервер, а не держа запрос открытым.
  ///
  /// Возвращает `null`, если карточку закрыли: работа на сервере от этого не
  /// прекращается, но обновлять уже нечего.
  Future<CatalogMatchRun?> _awaitMatch(
    CatalogMatchRun started,
    Future<CatalogMatchRun> Function(String matchRunId) poll,
  ) async {
    var current = started;
    while (mounted && !_matchCancelled && !current.isFinished) {
      setState(() => _matchRun = current);
      await Future<void>.delayed(const Duration(seconds: 8));
      if (!mounted || _matchCancelled) return null;
      current = await poll(current.id);
    }
    if (!mounted || _matchCancelled) return null;
    setState(() => _matchRun = current);
    return current;
  }

  void _openListing(String value) {
    if (value.isEmpty) return;
    final callback = widget.onOpenListing;
    if (callback != null) {
      callback(value);
      return;
    }
    unawaited(_launchListing(value));
  }

  Future<void> _launchListing(String value) async {
    final uri = Uri.tryParse(value);
    if (uri == null) return;
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }
}

class _CatalogComparisonLoad {
  const _CatalogComparisonLoad.success(this.comparison) : error = null;

  const _CatalogComparisonLoad.failure(this.error) : comparison = null;

  final CatalogCompetitorComparison? comparison;
  final Object? error;
}

class _SheetHeader extends StatelessWidget {
  const _SheetHeader();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 14),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: colors.brandSoft,
              borderRadius: BorderRadius.circular(10),
            ),
            alignment: Alignment.center,
            child: Icon(
              Icons.compare_arrows_rounded,
              color: colors.brand,
              size: 21,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.localized(ru: 'Карточка товара', uk: 'Картка товару'),
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Text(
                  context.localized(
                    ru: 'Конкурентные объявления для сравнения цены',
                    uk: 'Конкурентні оголошення для порівняння ціни',
                  ),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          IconButton(
            key: const ValueKey('catalog-details-close'),
            tooltip: context.localized(ru: 'Закрыть', uk: 'Закрити'),
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.close_rounded, size: 21),
          ),
        ],
      ),
    );
  }
}

class _ProductSummary extends StatelessWidget {
  const _ProductSummary({required this.product});

  final CatalogProduct product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final ownPrice = product.primaryStore?.price;
    final ownCurrency = product.primaryStore?.currency;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(11),
          child: SizedBox.square(
            dimension: 78,
            child: ColoredBox(
              color: colors.surfaceMuted,
              child: MarkoCachedImage(
                imageUrl: product.imageUrl,
                fit: BoxFit.cover,
              ),
            ),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                product.name,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              if (product.sku != null) ...[
                const SizedBox(height: 7),
                _IdentityRow(
                  label: context.localized(ru: 'Артикул', uk: 'Артикул'),
                  value: product.sku!,
                ),
              ],
              if (product.oe != null) ...[
                const SizedBox(height: 4),
                _IdentityRow(label: 'OE/OEM', value: product.oe!),
              ],
              if (product.mpn != null) ...[
                const SizedBox(height: 4),
                _IdentityRow(label: 'MPN', value: product.mpn!),
              ],
              if (ownPrice != null && ownCurrency != null) ...[
                const SizedBox(height: 4),
                _IdentityRow(
                  label: context.localized(ru: 'Ваша цена', uk: 'Ваша ціна'),
                  value: '${ownPrice.toStringAsFixed(2)} $ownCurrency',
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _IdentityRow extends StatelessWidget {
  const _IdentityRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Text.rich(
      TextSpan(
        children: [
          TextSpan(
            text: '$label: ',
            style: TextStyle(color: colors.muted),
          ),
          TextSpan(
            text: value,
            style: TextStyle(color: colors.ink, fontWeight: FontWeight.w600),
          ),
        ],
      ),
      style: Theme.of(context).textTheme.bodySmall,
    );
  }
}
