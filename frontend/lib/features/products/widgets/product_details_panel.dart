import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../products_models.dart';
import 'product_card.dart';

/// Side sheet with everything we already know about one product. Competitor
/// prices land here next; for now it shows the catalog data and a way out to
/// the original listing.
/// Opens the product details side sheet on desktop/tablets (with full backdrop
/// blocking all background interaction like top bar, filters, modals), or as
/// a full-screen page with back arrow navigation on mobile devices.
Future<void> showProductDetails(
  BuildContext context, {
  required StoreProduct product,
  VoidCallback? onDismissed,
}) async {
  final width = MediaQuery.sizeOf(context).width;
  final isMobile = width < 700;

  await showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Закрити деталі товару',
    barrierColor: const Color(0x66000000),
    transitionDuration: const Duration(milliseconds: 240),
    pageBuilder: (dialogContext, animation, secondaryAnimation) {
      return ProductDetailsPanel(
        product: product,
        isMobile: isMobile,
        onClose: () => Navigator.of(dialogContext).pop(),
      );
    },
    transitionBuilder: (dialogContext, animation, secondaryAnimation, child) {
      final curved = CurvedAnimation(
        parent: animation,
        curve: Curves.easeOutCubic,
        reverseCurve: Curves.easeInCubic,
      );
      if (isMobile) {
        return SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(1, 0),
            end: Offset.zero,
          ).animate(curved),
          child: child,
        );
      }
      return SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(1, 0),
          end: Offset.zero,
        ).animate(curved),
        child: Align(alignment: Alignment.centerRight, child: child),
      );
    },
  );
  onDismissed?.call();
}

/// Side sheet with everything we already know about one product. Competitor
/// prices land here next; for now it shows the catalog data and a way out to
/// the original listing.
class ProductDetailsPanel extends StatelessWidget {
  const ProductDetailsPanel({
    required this.product,
    required this.onClose,
    this.isMobile = false,
    super.key,
  });

  final StoreProduct? product;
  final VoidCallback onClose;
  final bool isMobile;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final width = MediaQuery.sizeOf(context).width;
    final mobile = isMobile || width < 700;
    final item = product;

    return Material(
      color: Colors.transparent,
      child: Container(
        width: mobile ? double.infinity : (width < 560 ? width : 480),
        height: double.infinity,
        decoration: BoxDecoration(
          color: colors.canvas,
          border: mobile
              ? null
              : Border(left: BorderSide(color: colors.border)),
          boxShadow: mobile ? null : MarkoShadow.overlay,
        ),
        child: SafeArea(
          child: item == null
              ? const SizedBox.shrink()
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _Header(product: item, onClose: onClose, isMobile: mobile),
                    Expanded(
                      child: ListView(
                        padding: const EdgeInsets.fromLTRB(
                          MarkoSpace.xl,
                          MarkoSpace.lg,
                          MarkoSpace.xl,
                          MarkoSpace.xxl,
                        ),
                        children: [
                          _Preview(product: item),
                          const SizedBox(height: MarkoSpace.lg),
                          _Facts(product: item),
                          if (item.oemNumbers.length > 1) ...[
                            const SizedBox(height: MarkoSpace.lg),
                            _OemNumbers(numbers: item.oemNumbers),
                          ],
                          const SizedBox(height: MarkoSpace.lg),
                          const _CompetitorsPlaceholder(),
                        ],
                      ),
                    ),
                  ],
                ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.product,
    required this.onClose,
    required this.isMobile,
  });

  final StoreProduct product;
  final VoidCallback onClose;
  final bool isMobile;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);

    if (isMobile) {
      return Container(
        padding: const EdgeInsets.fromLTRB(
          MarkoSpace.sm,
          MarkoSpace.sm,
          MarkoSpace.lg,
          MarkoSpace.md,
        ),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(bottom: BorderSide(color: colors.border)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                IconButton(
                  tooltip: 'Назад',
                  onPressed: onClose,
                  icon: const HeroIcon(HeroIcons.arrowLeft, size: 20),
                ),
                const SizedBox(width: MarkoSpace.xs),
                Expanded(
                  child: Text(
                    'Деталі товару',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                const SizedBox(width: MarkoSpace.sm),
                MarkoStatusPill(
                  label: product.availabilityLabel,
                  tone: product.isAvailable == true
                      ? colors.positive
                      : product.isAvailable == false
                      ? colors.negative
                      : colors.faint,
                ),
              ],
            ),
            const SizedBox(height: MarkoSpace.sm),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: MarkoSpace.sm),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    product.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w500,
                      height: 1.25,
                      fontSize: 17,
                    ),
                  ),
                  const SizedBox(height: MarkoSpace.xs),
                  if (product.price != null)
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Text(
                          formatPriceNumber(product.price!),
                          style: MarkoType.price.copyWith(
                            color: colors.ink,
                            fontSize: 22,
                            height: 1,
                            letterSpacing: -0.4,
                          ),
                        ),
                        const SizedBox(width: 4),
                        Text(
                          formatCurrency(product.currency),
                          style: MarkoType.caption.copyWith(
                            color: colors.faint,
                            fontWeight: FontWeight.w600,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    )
                  else
                    Text(
                      'Ціна не вказана',
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: colors.faint),
                    ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.fromLTRB(
        MarkoSpace.xl,
        MarkoSpace.lg,
        MarkoSpace.lg,
        MarkoSpace.lg,
      ),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  product.name,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w400,
                    height: 1.3,
                    fontSize: 18,
                  ),
                ),
                const SizedBox(height: MarkoSpace.md),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    if (product.price != null) ...[
                      Text(
                        formatPriceNumber(product.price!),
                        style: MarkoType.price.copyWith(
                          color: colors.ink,
                          fontSize: 22,
                          height: 1,
                          letterSpacing: -0.4,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        formatCurrency(product.currency),
                        style: MarkoType.caption.copyWith(
                          color: colors.faint,
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                        ),
                      ),
                      const SizedBox(width: MarkoSpace.md),
                    ] else ...[
                      Text(
                        'Ціна не вказана',
                        style: Theme.of(
                          context,
                        ).textTheme.bodySmall?.copyWith(color: colors.faint),
                      ),
                      const SizedBox(width: MarkoSpace.md),
                    ],
                    MarkoStatusPill(
                      label: product.availabilityLabel,
                      tone: product.isAvailable == true
                          ? colors.positive
                          : product.isAvailable == false
                          ? colors.negative
                          : colors.faint,
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: MarkoSpace.xl),
          IconButton(
            tooltip: 'Закрити',
            onPressed: onClose,
            icon: const HeroIcon(HeroIcons.xMark, size: 20),
          ),
        ],
      ),
    );
  }
}

class _Preview extends StatelessWidget {
  const _Preview({required this.product});

  final StoreProduct product;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(colors.panelRadius),
        border: Border.all(color: colors.border),
      ),
      child: AspectRatio(
        aspectRatio: 16 / 10,
        child: ColoredBox(
          color: colors.surfaceMuted,
          child: MarkoCachedImage(
            imageUrl: product.imageUrl,
            fit: BoxFit.contain,
          ),
        ),
      ),
    );
  }
}

class _Facts extends StatelessWidget {
  const _Facts({required this.product});

  final StoreProduct product;

  @override
  Widget build(BuildContext context) {
    final updated = product.lastSeenAt?.toLocal().toString();
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Fact(label: 'Артикул', value: product.sku, mono: true),
          _Fact(label: 'Бренд', value: product.brand),
          _Fact(label: 'OEM для пошуку', value: product.primaryOem, mono: true),
          _Fact(label: 'Магазин', value: product.storeName),
          _Fact(
            label: 'Оновлено',
            value: updated == null
                ? null
                : (updated.length >= 16 ? updated.substring(0, 16) : updated),
            mono: true,
          ),
          if (product.isFromProm) ...[
            const SizedBox(height: MarkoSpace.md),
            OutlinedButton.icon(
              onPressed: () => launchUrl(
                Uri.parse(product.url),
                mode: LaunchMode.externalApplication,
              ),
              icon: const HeroIcon(HeroIcons.arrowTopRightOnSquare, size: 17),
              label: const Text('Відкрити на Prom'),
            ),
          ],
        ],
      ),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value, this.mono = false});

  final String label;
  final String? value;

  /// Article codes, OEM numbers and timestamps line up as tabular data.
  final bool mono;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final empty = value == null || value!.isEmpty;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MarkoSpace.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: colors.faint),
            ),
          ),
          Expanded(
            child: Text(
              empty ? '—' : value!,
              style: mono && !empty
                  ? MarkoType.oem.copyWith(color: colors.ink)
                  : Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: empty ? colors.faint : colors.ink,
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OemNumbers extends StatelessWidget {
  const _OemNumbers({required this.numbers});

  final List<String> numbers;

  @override
  Widget build(BuildContext context) {
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Усі номери запчастини',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: MarkoSpace.md),
          Wrap(
            spacing: MarkoSpace.sm,
            runSpacing: MarkoSpace.sm,
            children: [for (final number in numbers) MarkoOemChip(number)],
          ),
        ],
      ),
    );
  }
}

class _CompetitorsPlaceholder extends StatelessWidget {
  const _CompetitorsPlaceholder();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      color: colors.surfaceMuted,
      padding: const EdgeInsets.all(MarkoSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              HeroIcon(
                HeroIcons.presentationChartLine,
                size: 17,
                color: colors.faint,
              ),
              const SizedBox(width: MarkoSpace.sm),
              Text(
                'Ціни конкурентів',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ],
          ),
          const SizedBox(height: MarkoSpace.sm),
          Text(
            'Автоматична перевірка за avto.pro з’явиться тут: мінімальна '
            'та медіанна ціна ринку, список пропозицій і рекомендація.',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.muted),
          ),
        ],
      ),
    );
  }
}
