import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../catalog_models.dart';
import 'catalog_competitor_section.dart';

Future<void> showCatalogProductDetailsSheet({
  required BuildContext context,
  required CatalogProduct product,
  required Future<CatalogCompetitorComparison> Function() loadCompetitors,
  Future<CatalogCompetitorComparison> Function()? discoverCompetitors,
  required VoidCallback onCompare,
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
      onCompare: () {
        Navigator.of(dialogContext).pop();
        onCompare();
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
    required this.onCompare,
    this.discoverCompetitors,
    this.onOpenListing,
    super.key,
  });

  final CatalogProduct product;
  final Future<CatalogCompetitorComparison> Function() loadCompetitors;
  final Future<CatalogCompetitorComparison> Function()? discoverCompetitors;
  final VoidCallback onCompare;
  final ValueChanged<String>? onOpenListing;

  @override
  State<CatalogProductDetailsSheet> createState() =>
      _CatalogProductDetailsSheetState();
}

class _CatalogProductDetailsSheetState
    extends State<CatalogProductDetailsSheet> {
  late Future<_CatalogComparisonLoad> _comparison;
  bool _isDiscovering = false;
  String? _discoveryError;

  @override
  void initState() {
    super.initState();
    _comparison = _loadComparison();
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
                    padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _ProductSummary(product: widget.product),
                        const SizedBox(height: 24),
                        FutureBuilder<_CatalogComparisonLoad>(
                          future: _comparison,
                          builder: (context, snapshot) {
                            if (snapshot.connectionState !=
                                ConnectionState.done) {
                              return const CatalogCompetitorLoading();
                            }
                            final result = snapshot.requireData;
                            if (result.error case final error?) {
                              return MarkoAsyncErrorView(
                                error: error,
                                forbiddenResourceRu:
                                    'конкурентным объявлениям этого товара',
                                forbiddenResourceUk:
                                    'конкурентних оголошень цього товару',
                                onRetry: _retry,
                                padding: EdgeInsets.zero,
                              );
                            }
                            return CatalogCompetitorSection(
                              comparison: result.comparison!,
                              onOpenListing: _openListing,
                            );
                          },
                        ),
                      ],
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
                        onPressed: widget.onCompare,
                        style: OutlinedButton.styleFrom(
                          backgroundColor: colors.surface,
                          foregroundColor: colors.ink,
                          side: BorderSide(color: colors.border),
                        ),
                        icon: const Icon(Icons.price_check_rounded, size: 19),
                        label: Text(
                          context.localized(
                            ru: 'Сопоставление с объявлениями конкурентов',
                            uk: 'Зіставлення з оголошеннями конкурентів',
                          ),
                        ),
                      ),
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
        _discoveryError = context.localized(
          ru: 'Сбор не завершён: $error',
          uk: 'Збір не завершено: $error',
        );
      });
    }
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
