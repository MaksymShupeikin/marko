import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/formatters.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../products_models.dart';

export '../../../core/formatters.dart';

/// Висота рядка й сторона мініатюри в горизонтальному (мобільному) вигляді.
const double productRowHeight = 104;

class ProductCard extends StatefulWidget {
  const ProductCard({
    required this.product,
    this.onTap,
    this.onLongPress,
    this.selected = false,
    this.checked = false,
    this.onCheckChanged,
    this.alwaysShowCheck = false,
    this.horizontal = false,
    super.key,
  });

  final StoreProduct product;
  final VoidCallback? onTap;

  /// Утримання на дотику вмикає режим вибору.
  final VoidCallback? onLongPress;
  final bool selected;

  /// Вузький екран: мала мініатюра зліва, текст справа на всю ширину.
  final bool horizontal;

  /// Ticked for a bulk action (distinct from [selected], the open card).
  final bool checked;
  final VoidCallback? onCheckChanged;

  /// Keep the tick visible where there is no hover to reveal it.
  final bool alwaysShowCheck;

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
          onLongPress: widget.onLongPress,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOutCubic,
            transform: Matrix4.translationValues(0, _hovered ? -3 : 0, 0),
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: radius,
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
            foregroundDecoration: BoxDecoration(
              borderRadius: radius,
              border: Border.all(
                color: widget.selected
                    ? colors.brand
                    : _hovered
                    ? colors.brand.withValues(alpha: 0.55)
                    : colors.border,
                width: widget.selected ? 1.5 : 1.0,
              ),
            ),
            child: ClipRRect(
              borderRadius: radius,
              child: RepaintBoundary(
                child: widget.horizontal
                    ? Row(
                        children: [
                          SizedBox(
                            width: productRowHeight,
                            child: _image(colors),
                          ),
                          Expanded(
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: colors.surface,
                                border: Border(
                                  left: BorderSide(color: colors.border),
                                ),
                              ),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: MarkoSpace.md,
                                  vertical: MarkoSpace.sm,
                                ),
                                child: _CardDetails(product: product),
                              ),
                            ),
                          ),
                        ],
                      )
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          AspectRatio(aspectRatio: 1, child: _image(colors)),
                          Expanded(
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: colors.surface,
                                border: Border(
                                  top: BorderSide(color: colors.border),
                                ),
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
      ),
    );
  }

  Widget _image(MarkoTheme colors) {
    return Stack(
      fit: StackFit.expand,
      children: [
        ClipRect(
          child: ColoredBox(
            color: colors.surfaceMuted,
            child: AnimatedScale(
              duration: const Duration(milliseconds: 240),
              curve: Curves.easeOutCubic,
              scale: _hovered ? 1.04 : 1.0,
              child: MarkoCachedImage(
                imageUrl: product.imageUrl,
                fit: BoxFit.cover,
              ),
            ),
          ),
        ),
        if (widget.onCheckChanged != null)
          Positioned(
            top: widget.horizontal ? 6 : MarkoSpace.sm,
            left: widget.horizontal ? 6 : null,
            right: widget.horizontal ? null : MarkoSpace.sm,
            child: AnimatedOpacity(
              duration: const Duration(milliseconds: 160),
              // Ticked marks stay visible: the selection has to be readable
              // without hovering every card.
              opacity: _hovered || widget.checked || widget.alwaysShowCheck
                  ? 1
                  : 0,
              child: _SelectMark(
                checked: widget.checked,
                onPressed: widget.onCheckChanged!,
              ),
            ),
          ),
      ],
    );
  }

  String get _availabilityLabel => product.isAvailable == true
      ? 'В наявності'
      : product.isAvailable == false
      ? 'Немає в наявності'
      : 'Наявність невідома';
}

/// A card-shaped placeholder with a sweeping shimmer: same square image block
/// and text bars as [ProductCard], so the grid keeps its rhythm while products
/// are still arriving.
class ProductCardSkeleton extends StatefulWidget {
  const ProductCardSkeleton({this.horizontal = false, super.key});

  final bool horizontal;

  @override
  State<ProductCardSkeleton> createState() => _ProductCardSkeletonState();
}

class _ProductCardSkeletonState extends State<ProductCardSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _sweep = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1500),
  )..repeat();

  @override
  void dispose() {
    _sweep.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final radius = BorderRadius.circular(colors.panelRadius);
    final bone = colors.surfaceMuted;
    // Ink over the bone: darker in the light theme, lighter in the dark one.
    final highlight = Color.alphaBlend(
      colors.ink.withValues(alpha: 0.07),
      bone,
    );

    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radius,
        border: Border.all(color: colors.border),
        boxShadow: MarkoShadow.card,
      ),
      child: ClipRRect(
        borderRadius: radius,
        child: RepaintBoundary(
          child: AnimatedBuilder(
            animation: _sweep,
            builder: (context, child) => ShaderMask(
              blendMode: BlendMode.srcATop,
              shaderCallback: (bounds) => LinearGradient(
                colors: [bone, highlight, bone],
                stops: const [0.35, 0.5, 0.65],
                transform: _SweepTransform(_sweep.value),
              ).createShader(bounds),
              child: child,
            ),
            child: widget.horizontal
                ? Row(
                    children: [
                      SizedBox(
                        width: productRowHeight,
                        child: ColoredBox(color: bone),
                      ),
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: MarkoSpace.md,
                            vertical: MarkoSpace.sm,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              _Bone(width: 70, height: 9, color: bone),
                              const SizedBox(height: MarkoSpace.xs),
                              _Bone(
                                width: double.infinity,
                                height: 11,
                                color: bone,
                              ),
                              const Spacer(),
                              _Bone(width: 84, height: 16, color: bone),
                            ],
                          ),
                        ),
                      ),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      AspectRatio(
                        aspectRatio: 1,
                        child: ColoredBox(color: bone),
                      ),
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.all(MarkoSpace.md),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              _Bone(width: 70, height: 9, color: bone),
                              const SizedBox(height: MarkoSpace.sm),
                              _Bone(
                                width: double.infinity,
                                height: 11,
                                color: bone,
                              ),
                              const SizedBox(height: 6),
                              _Bone(width: 120, height: 11, color: bone),
                              const Spacer(),
                              _Bone(width: 84, height: 16, color: bone),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

/// Slides the shimmer band across the card, left edge to right edge.
class _SweepTransform extends GradientTransform {
  const _SweepTransform(this.progress);

  final double progress;

  @override
  Matrix4 transform(Rect bounds, {TextDirection? textDirection}) =>
      Matrix4.translationValues(bounds.width * (progress * 2 - 1), 0, 0);
}

class _Bone extends StatelessWidget {
  const _Bone({required this.width, required this.height, required this.color});

  final double width;
  final double height;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(MarkoRadius.xs),
      ),
    );
  }
}

/// The tick in the card corner that adds a product to a bulk action.
class _SelectMark extends StatelessWidget {
  const _SelectMark({required this.checked, required this.onPressed});

  final bool checked;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Semantics(
      checked: checked,
      label: 'Позначити товар',
      child: Tooltip(
        message: checked ? 'Зняти позначку' : 'Позначити',
        child: InkResponse(
          onTap: onPressed,
          radius: 20,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 160),
            width: 26,
            height: 26,
            decoration: BoxDecoration(
              color: checked ? colors.brand : colors.surface,
              shape: BoxShape.circle,
              border: Border.all(
                color: checked ? colors.brand : colors.border,
                width: 1.5,
              ),
              boxShadow: MarkoShadow.card,
            ),
            child: HeroIcon(
              HeroIcons.check,
              size: 15,
              color: checked ? colors.surface : colors.faint,
              style: HeroIconStyle.outline,
            ),
          ),
        ),
      ),
    );
  }
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
              Flexible(
                child: Text(
                  product.isAvailable!
                      ? 'В наявності'
                      : 'Немає в наявності',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: MarkoType.caption.copyWith(
                    color: product.isAvailable!
                        ? colors.positive
                        : colors.faint,
                    fontWeight: FontWeight.w500,
                    fontSize: 11.5,
                  ),
                ),
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
