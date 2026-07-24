import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../catalog_models.dart';

class CatalogProductCard extends StatelessWidget {
  const CatalogProductCard({
    required this.product,
    required this.onCompare,
    this.onOpenListing,
    super.key,
  });

  final CatalogProduct product;
  final VoidCallback onCompare;
  final ValueChanged<String>? onOpenListing;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final listingUrl = product.primaryStore?.listingUrl;
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
                child: Column(
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
                      _metadata,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 10,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          product.primaryPriceLabel,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(
                                fontFeatures: const [
                                  FontFeature.tabularFigures(),
                                ],
                              ),
                        ),
                        if (product.isDuplicate)
                          Text(
                            '${product.listingCount} объявления объединены',
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(
                                  color: colors.positive,
                                  fontWeight: FontWeight.w600,
                                ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            _CompareButton(onPressed: onCompare),
          ],
        ),
      ),
    );
    if (listingUrl == null) return card;
    return Semantics(
      button: true,
      label: 'Открыть объявление ${product.name} на Prom.ua',
      child: MouseRegion(cursor: SystemMouseCursors.click, child: card),
    );
  }

  String get _metadata {
    final values = <String>[
      if (product.brand != null) product.brand!,
      if (product.sku != null) 'Артикул ${product.sku}',
      if (product.oe != null && product.oe != product.sku) 'OE ${product.oe}',
      '${product.stores.length} ${_storeWord(product.stores.length)}',
    ];
    return values.join(' · ');
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

  String _storeWord(int count) {
    final tail = count % 100;
    if (tail >= 11 && tail <= 14) return 'магазинах';
    return count % 10 == 1 ? 'магазине' : 'магазинах';
  }
}

class _CompareButton extends StatelessWidget {
  const _CompareButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Tooltip(
      message: 'Сравнить цены',
      child: Material(
        color: colors.brandSoft,
        borderRadius: BorderRadius.only(
          topRight: Radius.circular(colors.panelRadius - 1),
          bottomRight: Radius.circular(colors.panelRadius - 1),
        ),
        child: InkWell(
          key: const ValueKey('catalog-compare-button'),
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
