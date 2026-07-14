import 'package:flutter/material.dart';

import '../../../core/app_theme.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../store_models.dart';

class ProductCard extends StatefulWidget {
  const ProductCard({required this.product, super.key});

  final StoreProduct product;

  @override
  State<ProductCard> createState() => _ProductCardState();
}

class _ProductCardState extends State<ProductCard> {
  bool _hovered = false;

  StoreProduct get product => widget.product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final radius = BorderRadius.circular(16);

    return Semantics(
      label: '${product.name}, ${product.priceLabel}, $_availabilityLabel',
      image: true,
      excludeSemantics: true,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: AnimatedScale(
          scale: _hovered ? 1.006 : 1,
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOutCubic,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: colors.ink,
              borderRadius: radius,
              border: Border.all(
                color: _hovered
                    ? colors.ink.withValues(alpha: 0.28)
                    : colors.border,
              ),
              boxShadow: [
                BoxShadow(
                  color: colors.ink.withValues(alpha: _hovered ? 0.14 : 0.07),
                  blurRadius: _hovered ? 22 : 12,
                  offset: Offset(0, _hovered ? 7 : 3),
                ),
              ],
            ),
            child: RepaintBoundary(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AspectRatio(
                    aspectRatio: 1,
                    child: ColoredBox(
                      color: colors.surfaceMuted,
                      child: MarkoCachedImage(
                        imageUrl: product.imageUrl,
                        fit: BoxFit.cover,
                      ),
                    ),
                  ),
                  Expanded(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: colors.ink,
                        border: Border(
                          top: BorderSide(
                            color: Colors.white.withValues(alpha: 0.10),
                          ),
                        ),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(14, 12, 14, 13),
                        child: _CardDetails(product: product),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  String get _availabilityLabel => product.isAvailable == true
      ? 'В наличии'
      : product.isAvailable == false
      ? 'Нет в наличии'
      : 'Наличие неизвестно';
}

class _CardDetails extends StatelessWidget {
  const _CardDetails({required this.product});

  final StoreProduct product;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_metadata.isNotEmpty) ...[
          Text(
            _metadata,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.52),
              fontSize: 10.5,
              height: 1.1,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.3,
            ),
          ),
          const SizedBox(height: 5),
        ],
        Text(
          product.name,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: Colors.white.withValues(alpha: 0.92),
            height: 1.25,
            fontWeight: FontWeight.w600,
          ),
        ),
        const Spacer(),
        Container(height: 1, color: Colors.white.withValues(alpha: 0.11)),
        const SizedBox(height: 8),
        if (product.price == null)
          Text(
            'Цена не указана',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: Colors.white.withValues(alpha: 0.72),
            ),
          )
        else
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Flexible(
                child: Text(
                  product.price!.toStringAsFixed(2),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    color: Colors.white,
                    fontSize: 21,
                    height: 1,
                    letterSpacing: -0.4,
                    fontFeatures: const [FontFeature.tabularFigures()],
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: 7),
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(
                  product.currency,
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                    color: Colors.white.withValues(alpha: 0.52),
                    fontSize: 10.5,
                    letterSpacing: 0.45,
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }

  String get _metadata => [
    ?product.brand,
    if (product.sku != null) 'SKU ${product.sku}',
  ].join('  ·  ');
}
