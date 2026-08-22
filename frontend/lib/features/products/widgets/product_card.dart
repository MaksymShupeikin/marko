import 'package:flutter/material.dart';

import '../../../core/app_theme.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../products_models.dart';

String formatPriceNumber(double price) {
  final isWhole = price.truncateToDouble() == price;
  final fixed = price.toStringAsFixed(isWhole ? 0 : 2);
  final parts = fixed.split('.');
  final whole = parts[0].replaceAllMapped(
    RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
    (m) => '${m[1]} ',
  );
  return parts.length > 1 ? '$whole.${parts[1]}' : whole;
}

String formatCurrency(String currency) {
  return currency.toUpperCase() == 'UAH' ? '₴' : currency;
}

class ProductCard extends StatefulWidget {
  const ProductCard({
    required this.product,
    this.onTap,
    this.selected = false,
    super.key,
  });

  final StoreProduct product;
  final VoidCallback? onTap;
  final bool selected;

  @override
  State<ProductCard> createState() => _ProductCardState();
}

class _ProductCardState extends State<ProductCard> {
  bool _hovered = false;

  StoreProduct get product => widget.product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final radius = BorderRadius.circular(colors.panelRadius);

    return Semantics(
      label: '${product.name}, ${product.priceLabel}, $_availabilityLabel',
      button: widget.onTap != null,
      image: true,
      excludeSemantics: true,
      child: MouseRegion(
        cursor: widget.onTap == null
            ? MouseCursor.defer
            : SystemMouseCursors.click,
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOutCubic,
            transform: Matrix4.translationValues(0, _hovered ? -3 : 0, 0),
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: radius,
              border: Border.all(
                color: widget.selected
                    ? colors.brand
                    : _hovered
                    ? colors.brand.withValues(alpha: 0.45)
                    : colors.border,
                width: widget.selected ? 1.5 : (_hovered ? 1.2 : 1),
              ),
              boxShadow: _hovered
                  ? [
                      BoxShadow(
                        color: (widget.selected ? colors.brand : colors.ink)
                            .withValues(alpha: 0.12),
                        blurRadius: 18,
                        spreadRadius: -1,
                        offset: const Offset(0, 8),
                      ),
                      BoxShadow(
                        color: colors.ink.withValues(alpha: 0.05),
                        blurRadius: 4,
                        offset: const Offset(0, 2),
                      ),
                    ]
                  : widget.selected
                  ? MarkoShadow.hover
                  : MarkoShadow.card,
            ),
            child: RepaintBoundary(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AspectRatio(
                    aspectRatio: 1,
                    child: ColoredBox(
                      color: colors.surfaceMuted,
                      child: AnimatedScale(
                        duration: const Duration(milliseconds: 240),
                        curve: Curves.easeOutCubic,
                        scale: _hovered ? 1.05 : 1.0,
                        child: MarkoCachedImage(
                          imageUrl: product.imageUrl,
                          fit: BoxFit.cover,
                        ),
                      ),
                    ),
                  ),
                  Expanded(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        border: Border(top: BorderSide(color: colors.border)),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(MarkoSpace.md),
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
      ? 'В наявності'
      : product.isAvailable == false
      ? 'Немає в наявності'
      : 'Наявність невідома';
}

class _CardDetails extends StatelessWidget {
  const _CardDetails({required this.product});

  final StoreProduct product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_metadata.isNotEmpty) ...[
          Text(
            _metadata,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: MarkoType.caption.copyWith(color: colors.faint),
          ),
          const SizedBox(height: MarkoSpace.xs),
        ],
        Text(
          product.name,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            height: 1.3,
            fontWeight: FontWeight.w500,
          ),
        ),
        const Spacer(),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            if (product.price == null)
              Expanded(
                child: Text(
                  'Ціна не вказана',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: colors.faint),
                ),
              )
            else
              Flexible(
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Flexible(
                      child: Text(
                        formatPriceNumber(product.price!),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: MarkoType.price.copyWith(
                          color: colors.ink,
                          fontSize: 18,
                          height: 1,
                        ),
                      ),
                    ),
                    const SizedBox(width: 3),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 1),
                      child: Text(
                        formatCurrency(product.currency),
                        style: MarkoType.caption.copyWith(
                          color: colors.faint,
                          fontWeight: FontWeight.w500,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            if (product.isAvailable != null) ...[
              const SizedBox(width: MarkoSpace.xs),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: product.isAvailable!
                          ? colors.positive
                          : colors.negative,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Text(
                    product.isAvailable! ? 'В наявності' : 'Немає в наявності',
                    style: MarkoType.caption.copyWith(
                      color: product.isAvailable!
                          ? colors.positive
                          : colors.faint,
                      fontWeight: FontWeight.w500,
                      fontSize: 11.5,
                    ),
                  ),
                ],
              ),
            ],
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
