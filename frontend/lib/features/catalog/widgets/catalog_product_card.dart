import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_language.dart';
import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../catalog_models.dart';

class CatalogProductCard extends StatelessWidget {
  const CatalogProductCard({
    required this.product,
    required this.onShowDetails,
    this.onOpenListing,
    super.key,
  });

  final CatalogProduct product;
  final VoidCallback onShowDetails;
  final ValueChanged<String>? onOpenListing;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final listingUrl = product.primaryStore?.listingUrl;
    final compact = MediaQuery.sizeOf(context).width < 700;
    final card = MarkoPanel(
      key: ValueKey('catalog-product-card-${product.id}'),
      padding: EdgeInsets.zero,
      onTap: listingUrl == null ? null : () => _openListing(listingUrl),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(10),
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
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(2, 12, 14, 12),
                child: compact
                    ? Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _ProductIdentity(product: product, showOe: true),
                          const SizedBox(height: 9),
                          _CatalogPriceSummary(product: product),
                        ],
                      )
                    : Row(
                        children: [
                          Expanded(
                            child: _ProductIdentity(
                              product: product,
                              showOe: false,
                            ),
                          ),
                          if (product.oe != null) ...[
                            const SizedBox(width: 16),
                            SizedBox(
                              width: 145,
                              child: _OeIdentity(product: product),
                            ),
                          ],
                          const SizedBox(width: 16),
                          SizedBox(
                            width: 150,
                            child: _CatalogPriceSummary(product: product),
                          ),
                        ],
                      ),
              ),
            ),
            _DetailsButton(productId: product.id, onPressed: onShowDetails),
          ],
        ),
      ),
    );
    if (listingUrl == null) return card;
    return Semantics(
      button: true,
      label: context.localized(
        ru: 'Открыть объявление ${product.name} на Prom.ua',
        uk: 'Відкрити оголошення ${product.name} на Prom.ua',
      ),
      child: MouseRegion(cursor: SystemMouseCursors.click, child: card),
    );
  }

  void _openListing(String value) {
    final callback = onOpenListing;
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

class _ProductIdentity extends StatelessWidget {
  const _ProductIdentity({required this.product, required this.showOe});

  final CatalogProduct product;
  final bool showOe;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          product.name,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 4),
        Text(
          _metadata(context, product),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (showOe && product.oe != null) ...[
          const SizedBox(height: 4),
          _OeIdentity(product: product),
        ],
        if (product.isDuplicate) ...[
          const SizedBox(height: 4),
          Text(
            _duplicateLabel(context, product.listingCount),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: colors.positive,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ],
    );
  }
}

class _OeIdentity extends StatelessWidget {
  const _OeIdentity({required this.product});

  final CatalogProduct product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'OE/OEM',
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
        const SizedBox(height: 2),
        Text(
          product.oe!,
          key: ValueKey('catalog-product-oe-${product.id}'),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: colors.ink,
            fontWeight: FontWeight.w700,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }
}

class _CatalogPriceSummary extends StatelessWidget {
  const _CatalogPriceSummary({required this.product});

  final CatalogProduct product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final recommendation = product.recommendedPrice;
    if (recommendation == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            context.localized(ru: 'Цена на Prom.ua', uk: 'Ціна на Prom.ua'),
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.muted),
          ),
          const SizedBox(height: 2),
          Text(
            _primaryPriceLabel(context, product),
            key: ValueKey('catalog-current-price-${product.id}'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: _priceStyle(context, colors.ink),
          ),
        ],
      );
    }

    final tone = product.hasRaiseRecommendation
        ? colors.positive
        : product.hasLowerRecommendation
        ? colors.negative
        : colors.ink;
    final recommendationLabel = switch (product.recommendationAction) {
      'RAISE' => context.localized(
        ru: 'Можно поднять до',
        uk: 'Можна підняти до',
      ),
      'LOWER' => context.localized(
        ru: 'Рекомендуется снизить до',
        uk: 'Рекомендовано знизити до',
      ),
      _ => context.localized(
        ru: 'Рекомендуемая цена',
        uk: 'Рекомендована ціна',
      ),
    };
    final currency =
        product.recommendationCurrency ?? product.currency ?? 'UAH';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          recommendationLabel,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: tone,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          '${recommendation.toStringAsFixed(2)} $currency',
          key: ValueKey('catalog-recommended-price-${product.id}'),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: _priceStyle(context, tone),
        ),
        const SizedBox(height: 2),
        Text(
          context.localized(
            ru: 'Сейчас: ${_primaryPriceLabel(context, product)}',
            uk: 'Зараз: ${_primaryPriceLabel(context, product)}',
          ),
          key: ValueKey('catalog-current-price-${product.id}'),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: colors.muted),
        ),
      ],
    );
  }

  TextStyle? _priceStyle(BuildContext context, Color color) {
    return Theme.of(context).textTheme.titleMedium?.copyWith(
      color: color,
      fontWeight: FontWeight.w700,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
  }
}

class _DetailsButton extends StatelessWidget {
  const _DetailsButton({required this.productId, required this.onPressed});

  final String productId;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Tooltip(
      message: context.localized(
        ru: 'Показать конкурентов',
        uk: 'Показати конкурентів',
      ),
      child: Material(
        color: colors.brandSoft,
        borderRadius: BorderRadius.only(
          topRight: Radius.circular(colors.panelRadius - 1),
          bottomRight: Radius.circular(colors.panelRadius - 1),
        ),
        child: InkWell(
          key: ValueKey('catalog-details-button-$productId'),
          onTap: onPressed,
          borderRadius: BorderRadius.only(
            topRight: Radius.circular(colors.panelRadius - 1),
            bottomRight: Radius.circular(colors.panelRadius - 1),
          ),
          child: Container(
            width: 54,
            constraints: const BoxConstraints(minHeight: 102),
            decoration: BoxDecoration(
              border: Border(left: BorderSide(color: colors.border)),
            ),
            alignment: Alignment.center,
            child: Icon(
              Icons.arrow_forward_rounded,
              size: 22,
              color: colors.brand,
            ),
          ),
        ),
      ),
    );
  }
}

String _metadata(BuildContext context, CatalogProduct product) {
  final values = <String>[
    if (product.brand != null) product.brand!,
    if (product.sku != null)
      '${context.localized(ru: 'Артикул', uk: 'Артикул')} ${product.sku}',
    '${product.stores.length} ${_storeWord(context, product.stores.length)}',
  ];
  return values.join(' · ');
}

String _primaryPriceLabel(BuildContext context, CatalogProduct product) {
  final primary = product.primaryStore;
  if (primary?.price != null) return product.primaryPriceLabel;
  if (product.priceMin != null &&
      product.priceMax != null &&
      product.currency != null) {
    return product.priceLabel;
  }
  return context.localized(ru: 'Цена не указана', uk: 'Ціну не вказано');
}

String _duplicateLabel(BuildContext context, int count) {
  if (context.isUkrainian) {
    return '$count ${_ukListingWord(count)} об’єднано';
  }
  return '$count ${_ruListingWord(count)} объединены';
}

String _storeWord(BuildContext context, int count) {
  final tail = count % 100;
  if (tail >= 11 && tail <= 14) return 'магазинах';
  if (context.isUkrainian) {
    return count % 10 == 1 ? 'магазині' : 'магазинах';
  }
  return count % 10 == 1 ? 'магазине' : 'магазинах';
}

String _ruListingWord(int count) {
  final tail = count % 100;
  if (tail >= 11 && tail <= 14) return 'объявлений';
  return switch (count % 10) {
    1 => 'объявление',
    2 || 3 || 4 => 'объявления',
    _ => 'объявлений',
  };
}

String _ukListingWord(int count) {
  final tail = count % 100;
  if (tail >= 11 && tail <= 14) return 'оголошень';
  return count % 10 == 1 ? 'оголошення' : 'оголошень';
}
