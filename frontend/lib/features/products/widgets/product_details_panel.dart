import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../../../core/widgets/marko_loader.dart';
import '../../../core/widgets/marko_toast.dart';
import '../../billing/paywall.dart';
import '../products_api.dart';
import '../products_controller.dart';
import '../products_models.dart';
import 'product_management_dialogs.dart';

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
class ProductDetailsPanel extends ConsumerWidget {
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
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final width = MediaQuery.sizeOf(context).width;
    final mobile = isMobile || width < 700;
    final selected = ref.watch(productsControllerProvider).value?.selected;
    final item = selected?.id == product?.id ? selected : product;

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
                    _Header(
                      product: item,
                      onClose: onClose,
                      isMobile: mobile,
                      onRefresh: item.canManage
                          ? () => _refreshProduct(context, ref, item)
                          : null,
                      onDelete: item.canManage
                          ? () => _deleteProduct(context, item)
                          : null,
                    ),
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
                          _CompetitorPrices(product: item),
                        ],
                      ),
                    ),
                  ],
                ),
        ),
      ),
    );
  }

  /// The progress lives in the button itself, so the panel keeps showing the
  /// old values until the new ones land.
  Future<void> _refreshProduct(
    BuildContext context,
    WidgetRef ref,
    StoreProduct item,
  ) async {
    try {
      final updated = await ref
          .read(productsControllerProvider.notifier)
          .refreshProduct(item.id);
      ref.invalidate(competitorPricesProvider(item.id));
      if (!context.mounted) return;
      showMarkoToast(
        context,
        title: 'Дані оновлено',
        message: '«${updated.name}» оновлено за посиланням.',
      );
    } catch (e) {
      if (!context.mounted) return;
      showMarkoToast(
        context,
        title: 'Не вдалося оновити дані',
        message: '$e',
        tone: MarkoMessageTone.error,
      );
    }
  }

  Future<void> _deleteProduct(BuildContext context, StoreProduct item) async {
    final deleted = await confirmProductDeletion(context, product: item);
    if (!deleted || !context.mounted) return;
    showMarkoToast(context, message: '«${item.name}» видалено з каталогу');
    onClose();
  }
}

/// The same details sheet, but built from data already in hand — no
/// providers, no backend. The auth page renders it inside the demo window so
/// the marketing preview is the real product UI, not a mock.
class ProductDetailsPreview extends StatelessWidget {
  const ProductDetailsPreview({
    required this.product,
    required this.report,
    this.controller,
    this.searchStage,
    super.key,
  });

  final StoreProduct product;
  final CompetitorPriceReport report;

  /// Lets the host drive the scroll (auth page auto-scrolls the demo).
  final ScrollController? controller;

  /// Non-null — show the search-in-progress state with this stage caption
  /// instead of the report (the auth demo loops a canned search).
  final String? searchStage;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return ColoredBox(
      color: colors.canvas,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Header(
            product: product,
            onClose: () {},
            isMobile: false,
            dense: true,
          ),
          Expanded(
            child: Scrollbar(
              controller: controller,
              thumbVisibility: true,
              child: ListView(
                controller: controller,
                padding: const EdgeInsets.fromLTRB(
                  MarkoSpace.xl,
                  MarkoSpace.lg,
                  MarkoSpace.xl,
                  MarkoSpace.xxl,
                ),
                children: [
                  _Preview(product: product),
                  const SizedBox(height: MarkoSpace.lg),
                  _Facts(product: product),
                  if (product.oemNumbers.length > 1) ...[
                    const SizedBox(height: MarkoSpace.lg),
                    _OemNumbers(numbers: product.oemNumbers),
                  ],
                  const SizedBox(height: MarkoSpace.lg),
                  Container(
                    decoration: BoxDecoration(
                      color: colors.surface,
                      borderRadius: BorderRadius.circular(colors.panelRadius),
                      border: Border.all(color: colors.border),
                      boxShadow: MarkoShadow.card,
                    ),
                    padding: const EdgeInsets.all(MarkoSpace.lg),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Ціни конкурентів',
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: MarkoSpace.md),
                        if (searchStage != null)
                          _CompetitorPricesLoading(
                            productId: product.id,
                            stage: searchStage,
                          )
                        else
                          CompetitorPricesReport(
                            report: report,
                            product: product,
                          ),
                      ],
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

class _Header extends StatelessWidget {
  const _Header({
    required this.product,
    required this.onClose,
    required this.isMobile,
    this.onRefresh,
    this.onDelete,
    this.dense = false,
  });

  final StoreProduct product;
  final VoidCallback onClose;
  final bool isMobile;
  final Future<void> Function()? onRefresh;
  final VoidCallback? onDelete;

  /// Tighter paddings and type for the auth-page demo window.
  final bool dense;

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
                if (product.url.isNotEmpty) ...[
                  IconButton(
                    tooltip: 'Відкрити на Prom',
                    onPressed: () => launchUrl(
                      Uri.parse(product.url),
                      mode: LaunchMode.externalApplication,
                    ),
                    icon: const HeroIcon(
                      HeroIcons.arrowTopRightOnSquare,
                      size: 19,
                    ),
                  ),
                  const SizedBox(width: MarkoSpace.xs),
                ],
                if (onRefresh != null) ...[
                  _RefreshButton(onRefresh: onRefresh!),
                  const SizedBox(width: MarkoSpace.xs),
                ],
                if (onDelete != null)
                  IconButton(
                    tooltip: 'Видалити товар',
                    onPressed: onDelete,
                    icon: HeroIcon(
                      HeroIcons.trash,
                      size: 19,
                      color: colors.negative,
                    ),
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
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      if (product.price != null)
                        Flexible(
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            crossAxisAlignment: CrossAxisAlignment.baseline,
                            textBaseline: TextBaseline.alphabetic,
                            children: [
                              Flexible(
                                child: Text(
                                  formatPriceNumber(product.price!),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: MarkoType.price.copyWith(
                                    color: colors.ink,
                                    fontSize: 22,
                                    height: 1,
                                    letterSpacing: -0.4,
                                  ),
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
                          ),
                        )
                      else
                        Flexible(
                          child: Text(
                            'Ціна не вказана',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(color: colors.faint),
                          ),
                        ),
                      const SizedBox(width: MarkoSpace.xs),
                      Flexible(
                        child: Text(
                          product.availabilityLabel,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: MarkoType.caption.copyWith(
                            color: product.isAvailable == true
                                ? colors.positive
                                : product.isAvailable == false
                                ? colors.negative
                                : colors.faint,
                            fontWeight: FontWeight.w500,
                            fontSize: 13,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      // Dense keeps the content's horizontal rhythm: left edge matches the
      // list padding (xl), right leaves room for the compact close button.
      padding: dense
          ? const EdgeInsets.fromLTRB(
              MarkoSpace.xl,
              MarkoSpace.sm,
              MarkoSpace.md,
              MarkoSpace.sm,
            )
          : const EdgeInsets.fromLTRB(
              MarkoSpace.xl,
              MarkoSpace.lg,
              MarkoSpace.lg,
              MarkoSpace.lg,
            ),
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  product.name,
                  maxLines: dense ? 1 : 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w400,
                    height: 1.3,
                    fontSize: dense ? 15 : 18,
                  ),
                ),
              ),
              const SizedBox(width: MarkoSpace.md),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (product.url.isNotEmpty)
                    IconButton(
                      tooltip: 'Відкрити на Prom',
                      onPressed: () => launchUrl(
                        Uri.parse(product.url),
                        mode: LaunchMode.externalApplication,
                      ),
                      icon: const HeroIcon(
                        HeroIcons.arrowTopRightOnSquare,
                        size: 19,
                      ),
                    ),
                  if (onRefresh != null) _RefreshButton(onRefresh: onRefresh!),
                  if (onDelete != null)
                    IconButton(
                      tooltip: 'Видалити товар',
                      onPressed: onDelete,
                      icon: HeroIcon(
                        HeroIcons.trash,
                        size: 19,
                        color: colors.negative,
                      ),
                    ),
                  if (!dense)
                    IconButton(
                      tooltip: 'Закрити',
                      onPressed: onClose,
                      icon: const HeroIcon(HeroIcons.xMark, size: 20),
                    ),
                ],
              ),
            ],
          ),
          SizedBox(height: dense ? MarkoSpace.xs : MarkoSpace.md),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              if (product.price != null)
                Flexible(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      Flexible(
                        child: Text(
                          formatPriceNumber(product.price!),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: MarkoType.price.copyWith(
                            color: colors.ink,
                            fontSize: dense ? 17 : 22,
                            height: 1,
                            letterSpacing: -0.4,
                          ),
                        ),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        formatCurrency(product.currency),
                        style: MarkoType.caption.copyWith(
                          color: colors.faint,
                          fontWeight: FontWeight.w600,
                          fontSize: dense ? 12 : 13,
                        ),
                      ),
                    ],
                  ),
                )
              else
                Flexible(
                  child: Text(
                    'Ціна не вказана',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(
                      context,
                    ).textTheme.bodySmall?.copyWith(color: colors.faint),
                  ),
                ),
              const SizedBox(width: MarkoSpace.xs),
              Flexible(
                child: Text(
                  product.availabilityLabel,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: MarkoType.caption.copyWith(
                    color: product.isAvailable == true
                        ? colors.positive
                        : product.isAvailable == false
                        ? colors.negative
                        : colors.faint,
                    fontWeight: FontWeight.w500,
                    fontSize: dense ? 12 : 13,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Re-parses the source listing; spins in place until the new data lands.
class _RefreshButton extends StatefulWidget {
  const _RefreshButton({required this.onRefresh});

  final Future<void> Function() onRefresh;

  @override
  State<_RefreshButton> createState() => _RefreshButtonState();
}

class _RefreshButtonState extends State<_RefreshButton> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: 'Оновити дані за посиланням',
      onPressed: _busy ? null : _run,
      icon: _busy
          ? const MarkoLoader(size: 18)
          : const HeroIcon(HeroIcons.arrowPath, size: 19),
    );
  }

  Future<void> _run() async {
    setState(() => _busy = true);
    try {
      await widget.onRefresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
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
    final updated = product.lastSeenAt == null
        ? null
        : formatDateTimeUk(product.lastSeenAt!);
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Інформація про товар',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: MarkoSpace.md),
          _Fact(label: 'Артикул', value: product.sku, mono: true),
          _Fact(label: 'Бренд', value: product.brand),
          _Fact(label: 'OEM для пошуку', value: product.primaryOem, mono: true),
          _Fact(label: 'Магазин', value: product.storeName),
          _Fact(label: 'Синхронізовано', value: updated),
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
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
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

class _CompetitorPrices extends ConsumerWidget {
  const _CompetitorPrices({required this.product});

  final StoreProduct product;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final prices = ref.watch(competitorPricesProvider(product.id));
    return Container(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(colors.panelRadius),
        border: Border.all(color: colors.border),
        boxShadow: MarkoShadow.card,
      ),
      padding: const EdgeInsets.all(MarkoSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Ціни конкурентів',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: MarkoSpace.xs),
              IconButton(
                tooltip: 'Оновити ціни',
                onPressed: prices.isLoading
                    ? null
                    : () => ref
                          .read(competitorPricesProvider(product.id).notifier)
                          .refresh(),
                icon: prices.isLoading
                    ? const MarkoLoader(size: 18)
                    : const HeroIcon(HeroIcons.arrowPath, size: 19),
              ),
            ],
          ),
          const SizedBox(height: MarkoSpace.md),
          if (showPaywallDemo)
            const Center(child: PaywallCard())
          else
            prices.when(
              loading: () => _CompetitorPricesLoading(productId: product.id),
              error: (error, _) => isPaywallError(error)
                  ? const Center(child: PaywallCard())
                  : MarkoInlineMessage(
                      message: error.toString(),
                      tone: MarkoMessageTone.error,
                      action: TextButton(
                        onPressed: () =>
                            ref.refresh(competitorPricesProvider(product.id)),
                        child: const Text('Повторити'),
                      ),
                    ),
              data: (report) =>
                  CompetitorPricesReport(report: report, product: product),
            ),
        ],
      ),
    );
  }
}

class _CompetitorPricesLoading extends ConsumerStatefulWidget {
  const _CompetitorPricesLoading({required this.productId, this.stage});

  final String productId;

  /// Canned stage caption (auth-page demo); null — live provider value.
  final String? stage;

  @override
  ConsumerState<_CompetitorPricesLoading> createState() =>
      _CompetitorPricesLoadingState();
}

class _CompetitorPricesLoadingState
    extends ConsumerState<_CompetitorPricesLoading>
    with SingleTickerProviderStateMixin {
  late final AnimationController _shimmer;

  @override
  void initState() {
    super.initState();
    _shimmer = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    )..repeat();
  }

  @override
  void dispose() {
    _shimmer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final stage =
        widget.stage ??
        ref.watch(competitorStageProvider(widget.productId)) ??
        'Скануємо актуальні ціни на ринку...';
    return AnimatedBuilder(
      animation: _shimmer,
      builder: (context, _) {
        final shimmerValue = _shimmer.value;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: colors.surfaceMuted,
                borderRadius: BorderRadius.circular(MarkoRadius.md),
                border: Border.all(
                  color: colors.brand.withValues(
                    alpha:
                        0.15 +
                        0.25 *
                            (0.5 + 0.5 * math.sin(shimmerValue * 2 * math.pi)),
                  ),
                ),
              ),
              child: Row(
                children: [
                  const MarkoLoader(size: 14),
                  const SizedBox(width: MarkoSpace.sm),
                  Expanded(
                    child: AnimatedSwitcher(
                      duration: const Duration(milliseconds: 250),
                      layoutBuilder: (currentChild, previousChildren) => Stack(
                        alignment: Alignment.centerLeft,
                        children: <Widget>[...previousChildren, ?currentChild],
                      ),
                      child: SizedBox(
                        key: ValueKey(stage),
                        width: double.infinity,
                        child: Text(
                          stage,
                          textAlign: TextAlign.left,
                          style: MarkoType.caption.copyWith(
                            color: colors.ink,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: MarkoSpace.md),
            Row(
              children: [
                Expanded(child: _shimmerCard(colors, shimmerValue, height: 52)),
                const SizedBox(width: MarkoSpace.sm),
                Expanded(child: _shimmerCard(colors, shimmerValue, height: 52)),
                const SizedBox(width: MarkoSpace.sm),
                Expanded(child: _shimmerCard(colors, shimmerValue, height: 52)),
              ],
            ),
            const SizedBox(height: MarkoSpace.md),
            _shimmerCard(colors, shimmerValue, height: 8, radius: 999),
            const SizedBox(height: MarkoSpace.lg),
            _shimmerCard(colors, shimmerValue, height: 58),
            const SizedBox(height: MarkoSpace.sm),
            _shimmerCard(colors, shimmerValue, height: 58),
          ],
        );
      },
    );
  }

  Widget _shimmerCard(
    MarkoTheme colors,
    double value, {
    required double height,
    double? radius,
  }) {
    final baseColor = colors.surfaceMuted;
    final highlightColor = Color.lerp(baseColor, colors.border, 0.6)!;

    return Container(
      height: height,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius ?? MarkoRadius.md),
        gradient: LinearGradient(
          begin: Alignment(-1.5 + value * 3, 0),
          end: Alignment(-0.5 + value * 3, 0),
          colors: [baseColor, highlightColor, baseColor],
          stops: const [0.0, 0.5, 1.0],
        ),
      ),
    );
  }
}

/// Market report body: benchmark banner, min/median/max gauge and offer
/// cards. Reused by the OEM lookup modal, where there is no own product
/// (pass `product: null` — the "your price" comparisons just disappear).
/// Копії того самого товару у власних магазинах. Тягнемо лише коли картка
/// справді групова — зайвого запиту на кожен товар не робимо.
final _siblingsProvider = FutureProvider.autoDispose
    .family<List<SiblingListing>, String>(
      (ref, productId) => ref.watch(productsApiProvider).getSiblings(productId),
    );

class CompetitorPricesReport extends StatefulWidget {
  const CompetitorPricesReport({required this.report, this.product, super.key});

  final CompetitorPriceReport report;
  final StoreProduct? product;

  @override
  State<CompetitorPricesReport> createState() => _CompetitorPricesReportState();
}

class _CompetitorPricesReportState extends State<CompetitorPricesReport> {
  bool _expanded = false;

  /// Симуляція «а якщо знизити ціну на N%»: 0 — показуємо реальну ціну.
  int _discountPercent = 0;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final stats = widget.report.stats;
    final currency = widget.report.currency;
    final userPrice = widget.product?.price;
    // Всі порівняння нижче рахуємо від симульованої ціни — банер, шкала
    // і картки пропозицій миттєво перераховуються рухом повзунка.
    final simPrice = userPrice == null
        ? null
        : userPrice * (1 - _discountPercent / 100);

    if (stats.offersTotal == 0) {
      return const MarkoInlineMessage(
        message:
            'Цін із маркетплейсів поки не знайдено. Спробуйте оновити пізніше.',
      );
    }

    // Одна цінова драбина на всі джерела: оригінал і аналоги поруч, від
    // дешевшого. Що є що — видно з позначки на картці.
    final allOffers = widget.report.sources.expand((s) => s.offers).toList()
      ..sort((a, b) => a.price.compareTo(b.price));
    final visibleOffers = _expanded ? allOffers : allOffers.take(4).toList();

    // Своя ціна + межі ринку — без них ні вердикт, ні симуляція не мають сенсу.
    final hasOwnPrice =
        simPrice != null && stats.minPrice != null && stats.medianPrice != null;
    final rowDivider = Divider(height: 36, thickness: 1, color: colors.border);

    // Один блок замість чотирьох різностильних карток: рядки на спільній
    // поверхні, розділені лініями. Колір несе сенс лише у вердикті та
    // рекомендованій ціні — решта в нейтральній типографіці.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.all(MarkoSpace.xl),
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: BorderRadius.circular(MarkoRadius.md),
            border: Border.all(color: colors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (hasOwnPrice) ...[
                _PriceBenchmarkBanner(
                  userPrice: simPrice,
                  minPrice: stats.minPrice!,
                  medianPrice: stats.medianPrice!,
                  maxPrice: stats.maxPrice ?? stats.medianPrice!,
                  currency: currency,
                ),
                rowDivider,
              ],
              _MarketSpectrumGauge(
                stats: stats,
                userPrice: simPrice,
                currency: currency,
              ),
              if (stats.thinMarket) ...[
                rowDivider,
                const _ThinMarketBanner(),
              ] else if (stats.recommendedPrice != null) ...[
                rowDivider,
                _RecommendedPriceBanner(
                  price: stats.recommendedPrice!,
                  userPrice: userPrice,
                  currency: currency,
                  discountPercent: stats.recommendedDiscountPercent,
                ),
              ],
              if (hasOwnPrice) ...[
                rowDivider,
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Expanded(
                      child: Text(
                        'А якщо знизити ціну?',
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const SizedBox(width: MarkoSpace.md),
                    Text(
                      _discountPercent == 0
                          ? 'Потягніть для розрахунку'
                          : '${formatPriceNumber(simPrice)} ${formatCurrency(currency)}',
                      style: _discountPercent == 0
                          ? MarkoType.caption.copyWith(color: colors.muted)
                          : MarkoType.price.copyWith(
                              color: colors.brand,
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                            ),
                    ),
                  ],
                ),
                const SizedBox(height: MarkoSpace.md),
                SliderTheme(
                  data: SliderTheme.of(context).copyWith(
                    trackHeight: 4,
                    activeTrackColor: colors.brand,
                    inactiveTrackColor: colors.border,
                    thumbColor: colors.brand,
                    overlayColor: colors.brand.withValues(alpha: 0.10),
                    thumbShape: const RoundSliderThumbShape(
                      enabledThumbRadius: 7,
                    ),
                    valueIndicatorColor: colors.brand,
                  ),
                  child: Slider(
                    value: _discountPercent.toDouble(),
                    max: 30,
                    divisions: 30,
                    label: '−$_discountPercent%',
                    // Прибирає вбудовані бічні поля Material-слайдера, щоб
                    // трек тягнувся на всю ширину картки. Симетрично, щоб
                    // трек лишався по центру хіт-зони.
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    onChanged: (v) =>
                        setState(() => _discountPercent = v.round()),
                  ),
                ),
              ],
            ],
          ),
        ),
        if (stats.recommendedPrice != null &&
            (widget.product?.groupSize ?? 1) > 1) ...[
          const SizedBox(height: MarkoSpace.xl),
          _OwnStoresGuidance(
            productId: widget.product!.id,
            recommended: stats.recommendedPrice!,
            currency: currency,
          ),
        ],
        if (allOffers.isNotEmpty) ...[
          const SizedBox(height: MarkoSpace.xxxl),
          Text(
            'Пропозиції на ринку',
            style: Theme.of(
              context,
            ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: MarkoSpace.md),
          for (final offer in visibleOffers) ...[
            _ModernOfferCard(
              offer: offer,
              userPrice: simPrice,
              currency: currency,
            ),
            const SizedBox(height: MarkoSpace.sm),
          ],
          if (allOffers.length > 4) ...[
            const SizedBox(height: MarkoSpace.xs),
            Center(
              child: TextButton.icon(
                style: TextButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 6,
                  ),
                ),
                onPressed: () => setState(() => _expanded = !_expanded),
                icon: HeroIcon(
                  _expanded ? HeroIcons.chevronUp : HeroIcons.chevronDown,
                  size: 15,
                  color: colors.brand,
                ),
                label: Text(
                  _expanded
                      ? 'Згорнути'
                      : 'Показати всі ${allOffers.length} пропозицій',
                  style: TextStyle(
                    color: colors.brand,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          ],
        ],
      ],
    );
  }
}

/// Конкретна сума до виставлення: трохи нижче мінімальної ціни конкурентів.
class _ThinMarketBanner extends StatelessWidget {
  /// Менше трьох підтверджених цін: чесніше не давати точну суму, ніж
  /// рахувати її від випадкових грошей (контракт C2/B8 аудиту).
  const _ThinMarketBanner();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.all(7),
          decoration: BoxDecoration(
            color: colors.warning.withValues(alpha: 0.16),
            borderRadius: BorderRadius.circular(MarkoRadius.sm),
          ),
          child: HeroIcon(
            HeroIcons.exclamationTriangle,
            size: 16,
            color: colors.warning,
          ),
        ),
        const SizedBox(width: MarkoSpace.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Ринок тонкий',
                style: Theme.of(
                  context,
                ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              Text(
                'Менше трьох підтверджених цін — точну рекомендацію не даємо',
                style: MarkoType.caption.copyWith(
                  color: colors.muted,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _RecommendedPriceBanner extends StatelessWidget {
  const _RecommendedPriceBanner({
    required this.price,
    required this.userPrice,
    required this.currency,
    required this.discountPercent,
  });

  final double price;
  final double? userPrice;
  final String currency;

  /// Скільки відсотків нижче за мінімум ринку — цифра приходить з бекенду.
  final int discountPercent;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final diff = userPrice == null ? null : price - userPrice!;
    final subtitle = diff == null || diff.abs() < 1
        ? 'На $discountPercent% нижче мінімальної ціни конкурентів'
        : diff < 0
        ? 'На ${formatPriceNumber(diff.abs())} ${formatCurrency(currency)} нижче за вашу поточну ціну'
        : 'На ${formatPriceNumber(diff)} ${formatCurrency(currency)} вище за вашу поточну ціну';

    // Рядок на спільній поверхні звіту: бренд-колір лише на іконці та сумі.
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.all(7),
          decoration: BoxDecoration(
            color: colors.brand.withValues(alpha: 0.16),
            borderRadius: BorderRadius.circular(MarkoRadius.sm),
          ),
          child: HeroIcon(HeroIcons.lightBulb, size: 16, color: colors.brand),
        ),
        const SizedBox(width: MarkoSpace.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Рекомендована ціна',
                style: Theme.of(
                  context,
                ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: MarkoType.caption.copyWith(
                  color: colors.muted,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: MarkoSpace.md),
        Text(
          '${formatPriceNumber(price)} ${formatCurrency(currency)}',
          style: MarkoType.price.copyWith(
            color: colors.brand,
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _PriceBenchmarkBanner extends StatelessWidget {
  const _PriceBenchmarkBanner({
    required this.userPrice,
    required this.minPrice,
    required this.medianPrice,
    required this.maxPrice,
    required this.currency,
  });

  final double userPrice;
  final double minPrice;
  final double medianPrice;
  final double maxPrice;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isBest = userPrice <= minPrice * 1.01;
    final isBelowMedian = userPrice <= medianPrice;
    final diffFromMedian = userPrice - medianPrice;
    final pctFromMedian = ((diffFromMedian / medianPrice) * 100).abs();

    Color tone;
    HeroIcons icon;
    String title;
    String subtitle;

    // Заголовок — факт (вердикт), підзаголовок — на скільки гривень і від
    // чого саме: від найнижчої ціни або від медіани.
    if (isBest) {
      tone = colors.positive;
      icon = HeroIcons.sparkles;
      title = 'Найкраща ціна на ринку';
      final belowMin = minPrice - userPrice;
      subtitle = belowMin < 1
          ? 'Нарівні з найнижчою ціною конкурентів'
          : 'На ${formatPriceNumber(belowMin)} ${formatCurrency(currency)} нижче за найнижчу ціну конкурентів';
    } else if (isBelowMedian) {
      tone = colors.positive;
      icon = HeroIcons.scale;
      title = 'В оптимальному діапазоні';
      subtitle =
          'На ${formatPriceNumber(medianPrice - userPrice)} ${formatCurrency(currency)} нижче медіани ринку';
    } else if (pctFromMedian > 15) {
      tone = colors.negative;
      icon = HeroIcons.arrowTrendingUp;
      title = 'Значно дорожче за ринок';
      subtitle =
          'На ${formatPriceNumber(diffFromMedian)} ${formatCurrency(currency)} вище медіани ринку';
    } else {
      tone = colors.warning;
      icon = HeroIcons.arrowTrendingUp;
      title = 'Дорожче за медіану ринку';
      subtitle =
          'На ${formatPriceNumber(diffFromMedian)} ${formatCurrency(currency)} вище медіани ринку';
    }

    // Рядок без власного фону: живе на спільній поверхні звіту, тон несуть
    // лише іконка й заголовок.
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(7),
          decoration: BoxDecoration(
            color: tone.withValues(alpha: 0.16),
            borderRadius: BorderRadius.circular(MarkoRadius.sm),
          ),
          child: HeroIcon(icon, size: 16, color: tone),
        ),
        const SizedBox(width: MarkoSpace.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: tone,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: MarkoType.caption.copyWith(
                  color: colors.muted,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _MarketSpectrumGauge extends StatelessWidget {
  const _MarketSpectrumGauge({
    required this.stats,
    required this.userPrice,
    required this.currency,
  });

  final CompetitorPriceStats stats;
  final double? userPrice;
  final String currency;

  String _money(double? value) => value == null
      ? '—'
      : '${formatPriceNumber(value)} ${formatCurrency(currency)}';

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final min = stats.minPrice;
    final median = stats.medianPrice;
    final max = stats.maxPrice;

    double medianFraction = 0.5;
    if (min != null && max != null && median != null && max > min) {
      medianFraction = ((median - min) / (max - min)).clamp(0.0, 1.0);
    }

    double? userFraction;
    if (userPrice != null && min != null && max != null && max > min) {
      userFraction = ((userPrice! - min) / (max - min)).clamp(0.0, 1.0);
    }

    // Підпис над треком: мін зліва, медіана по центру, макс справа — без
    // окремих карток, самою типографікою.
    Widget stat(String label, double? value, CrossAxisAlignment align) =>
        Column(
          crossAxisAlignment: align,
          children: [
            Text(
              label,
              style: MarkoType.caption.copyWith(
                color: colors.muted,
                fontSize: 11,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              _money(value),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: MarkoType.price.copyWith(
                color: colors.ink,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        LayoutBuilder(
          builder: (context, constraints) {
            final w = constraints.maxWidth;
            const pinWidth = 64.0;
            final userLeft = userFraction == null
                ? 0.0
                : (userFraction * (w - 14)).clamp(0.0, w - 14);
            final userPillLeft = (userLeft - pinWidth / 2 + 7).clamp(
              0.0,
              w - pinWidth,
            );

            return Column(
              children: [
                if (userPrice != null) ...[
                  SizedBox(
                    height: 22,
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        Positioned(
                          left: userPillLeft,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 6,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: colors.surface,
                              borderRadius: BorderRadius.circular(
                                MarkoRadius.xs,
                              ),
                              border: Border.all(color: colors.border),
                              boxShadow: MarkoShadow.card,
                            ),
                            child: Text(
                              'Ваша ціна',
                              style: TextStyle(
                                color: colors.ink,
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                height: 1.1,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 6),
                ],
                SizedBox(
                  height: 14,
                  child: Stack(
                    alignment: Alignment.centerLeft,
                    children: [
                      Container(
                        height: 6,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(999),
                          gradient: LinearGradient(
                            colors: [
                              colors.positive,
                              colors.warning,
                              colors.negative,
                            ],
                            stops: const [0.0, 0.5, 1.0],
                          ),
                        ),
                      ),
                      Positioned(
                        left: (w - 3) * medianFraction,
                        child: Container(
                          width: 3,
                          height: 14,
                          decoration: BoxDecoration(
                            color: colors.ink,
                            borderRadius: BorderRadius.circular(2),
                            border: Border.all(
                              color: colors.surface,
                              width: 0.5,
                            ),
                          ),
                        ),
                      ),
                      if (userPrice != null)
                        Positioned(
                          left: userLeft,
                          child: Container(
                            width: 14,
                            height: 14,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: colors.surface,
                              border: Border.all(color: colors.ink, width: 3.0),
                              boxShadow: [
                                BoxShadow(
                                  color: Colors.black.withValues(alpha: 0.25),
                                  blurRadius: 3,
                                  offset: const Offset(0, 1),
                                ),
                              ],
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
        const SizedBox(height: MarkoSpace.md),
        Row(
          children: [
            Expanded(child: stat('Мінімум', min, CrossAxisAlignment.start)),
            Expanded(child: stat('Медіана', median, CrossAxisAlignment.center)),
            Expanded(child: stat('Максимум', max, CrossAxisAlignment.end)),
          ],
        ),
      ],
    );
  }
}

class _OfferCardSurface extends StatelessWidget {
  const _OfferCardSurface({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.md,
        vertical: 11,
      ),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
      ),
      child: child,
    );
  }
}

class _ModernOfferCard extends StatelessWidget {
  const _ModernOfferCard({
    required this.offer,
    required this.userPrice,
    required this.currency,
  });

  final MarketPriceOffer offer;
  final double? userPrice;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isCheaper = userPrice != null && offer.price < userPrice!;
    final diff = userPrice != null ? (offer.price - userPrice!).abs() : null;

    return _OfferCardSurface(
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  offer.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (offer.seller != null && offer.seller!.isNotEmpty)
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          HeroIcon(
                            HeroIcons.buildingStorefront,
                            size: 12,
                            color: colors.faint,
                          ),
                          const SizedBox(width: 3),
                          Flexible(
                            child: Text(
                              offer.seller!,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: MarkoType.caption.copyWith(
                                color: colors.faint,
                                fontSize: 11,
                              ),
                            ),
                          ),
                        ],
                      ),
                    if (offer.city != null && offer.city!.isNotEmpty)
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          HeroIcon(
                            HeroIcons.mapPin,
                            size: 12,
                            color: colors.faint,
                          ),
                          const SizedBox(width: 3),
                          Flexible(
                            child: Text(
                              offer.city!,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: MarkoType.caption.copyWith(
                                color: colors.faint,
                                fontSize: 11,
                              ),
                            ),
                          ),
                        ],
                      ),
                    if (offer.isAnalog)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 4,
                          vertical: 1,
                        ),
                        decoration: BoxDecoration(
                          color: colors.warning.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(MarkoRadius.xs),
                        ),
                        child: Text(
                          'аналог',
                          style: MarkoType.caption.copyWith(
                            color: colors.warning,
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    // Б/в видно, але воно не ринок: бейдж мусить сам
                    // пояснити, чому дешева картка не збиває рекомендацію.
                    if (offer.condition == 'used')
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: colors.negative.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(MarkoRadius.xs),
                        ),
                        child: Text(
                          'б/в — не в ціні',
                          style: MarkoType.caption.copyWith(
                            color: colors.negative,
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      )
                    else if (offer.condition != null)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 4,
                          vertical: 1,
                        ),
                        decoration: BoxDecoration(
                          color: colors.surfaceMuted,
                          borderRadius: BorderRadius.circular(MarkoRadius.xs),
                        ),
                        child: Text(
                          'нове',
                          style: MarkoType.caption.copyWith(
                            color: colors.ink,
                            fontSize: 10,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                  ],
                ),
                if (offer.source == 'avtopro') ...[
                  const SizedBox(height: 4),
                  Text(
                    offer.city != null && offer.city!.isNotEmpty
                        ? 'Посилання відкриє всіх продавців — ця ціна в рядку міста ${offer.city}'
                        : 'Посилання відкриє всіх продавців деталі',
                    style: MarkoType.caption.copyWith(color: colors.muted),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${formatPriceNumber(offer.price)} ${formatCurrency(currency)}',
                style: MarkoType.price.copyWith(
                  // Сіра цифра = довідкова: б/в не бере участі в розрахунку.
                  color: offer.condition == 'used' ? colors.muted : colors.ink,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (diff != null && diff > 0 && offer.condition != 'used') ...[
                const SizedBox(height: 2),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 5,
                    vertical: 1,
                  ),
                  decoration: BoxDecoration(
                    color: (isCheaper ? colors.negative : colors.positive)
                        .withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(MarkoRadius.xs),
                  ),
                  child: Text(
                    isCheaper
                        ? '-${formatPriceNumber(diff)} ${formatCurrency(currency)}'
                        : '+${formatPriceNumber(diff)} ${formatCurrency(currency)}',
                    style: TextStyle(
                      color: isCheaper ? colors.negative : colors.positive,
                      fontSize: 10.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Відкрити пропозицію',
            onPressed: offer.url.isEmpty
                ? null
                : () => launchUrl(
                    Uri.parse(offer.url),
                    mode: LaunchMode.externalApplication,
                  ),
            icon: const HeroIcon(HeroIcons.arrowTopRightOnSquare, size: 19),
          ),
        ],
      ),
    );
  }
}

/// Що робити з ціною в кожному власному магазині: заказчик тримає той самий
/// товар у чотирьох магазинах за різними цінами, і рекомендація рахується
/// від найдешевшого. Решті потрібна своя, конкретна цифра.
class _OwnStoresGuidance extends ConsumerWidget {
  const _OwnStoresGuidance({
    required this.productId,
    required this.recommended,
    required this.currency,
  });

  final String productId;
  final double recommended;
  final String currency;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final siblings = ref.watch(_siblingsProvider(productId));

    return Padding(
      padding: const EdgeInsets.only(top: MarkoSpace.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Ваші магазини',
            style: Theme.of(
              context,
            ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: MarkoSpace.sm),
          siblings.when(
            loading: () => const _OwnStoresLoadingCard(),
            error: (_, _) => const MarkoInlineMessage(
              message: 'Не вдалося завантажити ціни ваших магазинів.',
              tone: MarkoMessageTone.error,
            ),
            data: (items) {
              if (items.length < 2) return const SizedBox.shrink();
              return Column(
                children: [
                  for (var index = 0; index < items.length; index++) ...[
                    _OwnStoreOfferCard(
                      sibling: items[index],
                      recommended: recommended,
                      currency: currency,
                    ),
                    if (index != items.length - 1)
                      const SizedBox(height: MarkoSpace.sm),
                  ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _OwnStoresLoadingCard extends StatelessWidget {
  const _OwnStoresLoadingCard();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return _OfferCardSurface(
      child: Row(
        children: [
          const MarkoLoader(size: 16, strokeWidth: 2),
          const SizedBox(width: MarkoSpace.sm),
          Text(
            'Завантажуємо ціни магазинів',
            style: MarkoType.caption.copyWith(color: colors.faint),
          ),
        ],
      ),
    );
  }
}

class _OwnStoreOfferCard extends StatelessWidget {
  const _OwnStoreOfferCard({
    required this.sibling,
    required this.recommended,
    required this.currency,
  });

  final SiblingListing sibling;
  final double recommended;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final price = sibling.price;
    final target =
        '${formatPriceNumber(recommended)} ${formatCurrency(currency)}';
    final matchesRecommendation =
        price != null && (price - recommended).abs() <= recommended * 0.01;
    final advice = switch ((price, matchesRecommendation)) {
      (null, _) => 'Вкажіть ціну',
      (_, true) => 'Відповідає рекомендації',
      (final value?, false) when value > recommended => 'Знизити до $target',
      _ => 'Підняти до $target',
    };
    final adviceColor = switch ((price, matchesRecommendation)) {
      (null, _) => colors.faint,
      (_, true) => colors.positive,
      (final value?, false) when value > recommended => colors.negative,
      _ => colors.brand,
    };

    return _OfferCardSurface(
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  sibling.storeName,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    HeroIcon(
                      HeroIcons.buildingStorefront,
                      size: 12,
                      color: colors.faint,
                    ),
                    const SizedBox(width: 3),
                    Text(
                      'Ваш магазин',
                      style: MarkoType.caption.copyWith(
                        color: colors.faint,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                price == null
                    ? 'Ціна не вказана'
                    : '${formatPriceNumber(price)} ${formatCurrency(currency)}',
                style: MarkoType.price.copyWith(
                  color: price == null ? colors.faint : colors.ink,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 2),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(
                  color: adviceColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(MarkoRadius.xs),
                ),
                child: Text(
                  advice,
                  style: TextStyle(
                    color: adviceColor,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Відкрити товар у магазині',
            onPressed: sibling.url.isEmpty
                ? null
                : () => launchUrl(
                    Uri.parse(sibling.url),
                    mode: LaunchMode.externalApplication,
                  ),
            icon: const HeroIcon(HeroIcons.arrowTopRightOnSquare, size: 19),
          ),
        ],
      ),
    );
  }
}
