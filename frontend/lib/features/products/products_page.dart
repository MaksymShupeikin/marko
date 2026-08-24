import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_loader.dart';
import '../../core/widgets/marko_toast.dart';
import 'products_controller.dart';
import 'products_models.dart';
import 'widgets/dynamic_sync_island.dart';
import 'widgets/product_card.dart';
import 'widgets/product_details_panel.dart';
import 'widgets/product_management_dialogs.dart';
import 'widgets/source_panel.dart';

/// Нижня панель дашборда (імпорт каталогу / ціни конкурентів) на мобілці.
const _bottomBarHeight = 76.0;

/// Висота плашки дій — потрібна, щоб розсунути те, що плаває над нею.
const _selectionBarHeight = 56.0;

/// The catalog toolbar's field controllers, kept outside the widget so the
/// filters survive rebuilds.
final catalogSearchFieldProvider = Provider<TextEditingController>((ref) {
  final controller = TextEditingController();
  ref.onDispose(controller.dispose);
  return controller;
});

final catalogPriceMinFieldProvider = Provider<TextEditingController>((ref) {
  final controller = TextEditingController();
  ref.onDispose(controller.dispose);
  return controller;
});

final catalogPriceMaxFieldProvider = Provider<TextEditingController>((ref) {
  final controller = TextEditingController();
  ref.onDispose(controller.dispose);
  return controller;
});

/// Clears the search box, price inputs, and resets all catalog filters to defaults.
void resetCatalogFilters(WidgetRef ref) {
  ref.read(catalogSearchFieldProvider).clear();
  ref.read(catalogPriceMinFieldProvider).clear();
  ref.read(catalogPriceMaxFieldProvider).clear();
  ref.read(productsControllerProvider.notifier).resetFilters();
}

/// The catalog search input.
class CatalogSearchField extends ConsumerWidget {
  const CatalogSearchField({
    this.labelText = 'Назва, артикул, бренд',
    this.hintText = 'Volkswagen T4 бампер',
    super.key,
  });

  final String? labelText;
  final String? hintText;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.watch(catalogSearchFieldProvider);
    final search = ref.read(productsControllerProvider.notifier).search;
    return ValueListenableBuilder(
      valueListenable: controller,
      builder: (context, value, _) => MarkoTextField(
        controller: controller,
        onChanged: search,
        textInputAction: TextInputAction.search,
        labelText: labelText,
        hintText: hintText,
        prefixIcon: HeroIcons.magnifyingGlass,
        suffixIcon: value.text.isEmpty
            ? null
            : IconButton(
                tooltip: 'Очистити',
                icon: const HeroIcon(HeroIcons.xMark, size: 17),
                onPressed: () {
                  controller.clear();
                  search('');
                },
              ),
      ),
    );
  }
}

class ProductsPage extends ConsumerStatefulWidget {
  const ProductsPage({super.key});

  @override
  ConsumerState<ProductsPage> createState() => _ProductsPageState();
}

class _ProductsPageState extends ConsumerState<ProductsPage> {
  final _scrollController = ScrollController();
  bool _showScrollTop = false;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController
      ..removeListener(_onScroll)
      ..dispose();
    super.dispose();
  }

  void _onScroll() {
    final position = _scrollController.position;
    if (position.pixels >= position.maxScrollExtent - 600) {
      ref.read(productsControllerProvider.notifier).loadMore();
    }
    final showScrollTop = position.pixels > 400;
    if (showScrollTop != _showScrollTop) {
      setState(() => _showScrollTop = showScrollTop);
    }
  }

  void _scrollToTop() => _scrollController.animateTo(
    0,
    duration: const Duration(milliseconds: 320),
    curve: Curves.easeOutCubic,
  );

  void _openDetails(StoreProduct product) {
    ref.read(productsControllerProvider.notifier).select(product);
    showProductDetails(
      context,
      product: product,
      onDismissed: () {
        if (mounted) {
          ref.read(productsControllerProvider.notifier).select(null);
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final catalog = ref.watch(productsControllerProvider);
    final controller = ref.read(productsControllerProvider.notifier);
    final state = catalog.value;
    // Поки триває імпорт, каталог уже показуємо: товари прибувають у сітку.
    final syncing = ref.watch(
      catalogImportProvider.select((s) => s.value?.hasActiveJob ?? false),
    );
    // Той самий поріг, що й у нижньої панелі дашборда.
    final compact = MediaQuery.sizeOf(context).width < 840;
    final showSelection =
        state != null && (state.hasSelection || state.bulkJob != null);
    final onboarding = state != null && state.isPristineEmpty && !syncing;
    // Нижня панель дашборда плюс жест-бар пристрою.
    final bottomBar = _bottomBarHeight + MediaQuery.paddingOf(context).bottom;

    return Material(
      color: Colors.transparent,
      child: Stack(
        children: [
          GestureDetector(
            onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
            child: CustomScrollView(
              controller: _scrollController,
              slivers: [
                SliverToBoxAdapter(
                  child: MarkoContentFrame(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const SizedBox(height: MarkoSpace.xxl),
                        const SourcePanel(),
                        const SizedBox(height: MarkoSpace.md),
                        if (onboarding)
                          const CatalogOnboarding()
                        else
                          _CatalogToolbar(
                            total: state?.page.total,
                            busy: state?.isRefreshing ?? false,
                          ),
                        if (state?.error != null) ...[
                          const SizedBox(height: MarkoSpace.md),
                          MarkoInlineMessage(
                            message: state!.error!,
                            tone: MarkoMessageTone.error,
                            action: TextButton(
                              onPressed: controller.dismissError,
                              child: const Text('Закрити'),
                            ),
                          ),
                        ],
                        const SizedBox(height: MarkoSpace.lg),
                      ],
                    ),
                  ),
                ),
                ...switch (catalog) {
                  AsyncLoading() => [const _GridSkeletonSliver()],
                  AsyncError(:final error) => [
                    SliverToBoxAdapter(
                      child: MarkoContentFrame(
                        child: _RetryView(
                          message: error.toString(),
                          onRetry: controller.refresh,
                        ),
                      ),
                    ),
                  ],
                  _ => _catalogSlivers(state!, syncing),
                },
                // Каталог доїжджає до самого низу екрана: місце лишаємо під плаваючими панелями.
                SliverToBoxAdapter(
                  child: SizedBox(
                    height: showSelection
                        ? (compact
                              ? bottomBar + _selectionBarHeight
                              : _selectionBarHeight + MarkoSpace.xl * 2)
                        : (compact ? bottomBar : 0),
                  ),
                ),
              ],
            ),
          ),
          // Live import status; floats over the catalog without moving it.
          const Positioned(
            top: MarkoSpace.md,
            left: 0,
            right: 0,
            child: Center(child: DynamicSyncIsland()),
          ),
          // Дії над вибраним: плашка внизу екрана в Stack для мобілки й десктопу.
          if (showSelection)
            Positioned(
              left: 0,
              right: 0,
              bottom: compact ? bottomBar + MarkoSpace.sm : MarkoSpace.xl,
              // Той самий жолоб, що й у каталогу: плашка стає в один край з картками.
              child: MarkoContentFrame(
                child: _SelectionBar(
                  count: state.actionCount,
                  total: state.page.total,
                  allMatching: state.allMatchingSelected,
                  job: state.bulkJob,
                ),
              ),
            ),
          // Centered floating capsule pill above the bottom edge / compact bar.
          AnimatedPositioned(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            left: 0,
            right: 0,
            bottom: compact
                ? bottomBar +
                      (showSelection ? _selectionBarHeight + MarkoSpace.md : 0)
                : (showSelection
                      ? _selectionBarHeight + MarkoSpace.xxl
                      : MarkoSpace.xl),
            child: Center(
              child: _ScrollTopButton(
                // На порожньому каталозі гортати нічого — кнопка зайва.
                visible: _showScrollTop && !onboarding,
                onPressed: _scrollToTop,
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _catalogSlivers(CatalogState state, bool syncing) {
    // Onboarding already fills the screen and says the same thing.
    if (state.isPristineEmpty && !syncing) return const [];

    // При пошуку, фільтрації або початковому імпорті показуємо шимер карток
    if (state.isRefreshing || (syncing && state.page.items.isEmpty)) {
      return const [_GridSkeletonSliver()];
    }

    if (state.page.items.isEmpty) {
      return [
        SliverFillRemaining(
          hasScrollBody: false,
          child: Padding(
            padding: const EdgeInsets.only(bottom: 72),
            child: MarkoContentFrame(
              child: Center(
                child: _EmptyCatalog(
                  query: state.query,
                  hasActiveFilters: state.hasActiveFilters,
                ),
              ),
            ),
          ),
        ),
      ];
    }
    return [
      SliverToBoxAdapter(
        child: MarkoContentFrame(
          child: _ProductGrid(
            products: state.page.items,
            selectedId: state.selected?.id,
            // "Вибрано все" позначає й видимі картки, хоч selectedIds порожній.
            checkedIds: state.allMatchingSelected
                ? {for (final item in state.page.items) item.id}
                : state.selectedIds,
            // Ще не приїхали, але вже в дорозі.
            ghostCount: syncing ? 4 : 0,
            onOpen: _openDetails,
            onCheck: ref
                .read(productsControllerProvider.notifier)
                .toggleSelection,
          ),
        ),
      ),
      if (state.isLoadingMore)
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Center(child: MarkoLoader(size: 26)),
          ),
        ),
    ];
  }
}

/// Back to the top of the catalog; centered floating pill that appears on scroll.
class _ScrollTopButton extends StatefulWidget {
  const _ScrollTopButton({required this.visible, required this.onPressed});

  final bool visible;
  final VoidCallback onPressed;

  @override
  State<_ScrollTopButton> createState() => _ScrollTopButtonState();
}

class _ScrollTopButtonState extends State<_ScrollTopButton> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final height = MarkoLayout.fieldHeightOf(context);
    const duration = Duration(milliseconds: 220);

    return IgnorePointer(
      ignoring: !widget.visible,
      child: AnimatedSlide(
        offset: widget.visible ? Offset.zero : const Offset(0, 0.6),
        duration: duration,
        curve: Curves.easeOutCubic,
        child: AnimatedOpacity(
          opacity: widget.visible ? 1 : 0,
          duration: duration,
          child: AnimatedScale(
            scale: widget.visible ? 1.0 : 0.85,
            duration: duration,
            curve: Curves.easeOutCubic,
            child: Tooltip(
              message: 'Вгору',
              child: MouseRegion(
                cursor: SystemMouseCursors.click,
                onEnter: (_) => setState(() => _hovered = true),
                onExit: (_) => setState(() => _hovered = false),
                child: GestureDetector(
                  onTap: widget.onPressed,
                  child: Center(
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 160),
                      curve: Curves.easeOutCubic,
                      height: height,
                      transform: Matrix4.translationValues(
                        0,
                        _hovered ? -2.0 : 0,
                        0,
                      ),
                      padding: const EdgeInsets.symmetric(
                        horizontal: MarkoSpace.lg,
                      ),
                      decoration: BoxDecoration(
                        color: colors.surface.withValues(alpha: 0.94),
                        borderRadius: BorderRadius.circular(MarkoRadius.md),
                        border: Border.all(
                          color: _hovered
                              ? colors.brand.withValues(alpha: 0.8)
                              : colors.borderStrong,
                          width: _hovered ? 1.2 : 1.0,
                        ),
                        boxShadow: [
                          if (_hovered)
                            BoxShadow(
                              color: colors.brand.withValues(alpha: 0.2),
                              blurRadius: 20,
                              offset: const Offset(0, 6),
                            ),
                          ...MarkoShadow.overlay,
                        ],
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          AnimatedContainer(
                            duration: const Duration(milliseconds: 160),
                            width: 24,
                            height: 24,
                            decoration: BoxDecoration(
                              color: _hovered
                                  ? colors.brandSoft
                                  : colors.surfaceMuted,
                              borderRadius: BorderRadius.circular(
                                MarkoRadius.sm,
                              ),
                            ),
                            alignment: Alignment.center,
                            child: HeroIcon(
                              HeroIcons.arrowUp,
                              size: 14,
                              color: _hovered ? colors.brand : colors.ink,
                            ),
                          ),
                          const SizedBox(width: MarkoSpace.sm),
                          Text(
                            'Вгору',
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: _hovered ? colors.brand : colors.ink,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CatalogToolbar extends StatelessWidget {
  const _CatalogToolbar({required this.total, required this.busy});

  final int? total;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text('Каталог', style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(width: MarkoSpace.sm),
            MarkoOemChip(total?.toString() ?? '—'),
            if (busy) ...[
              const SizedBox(width: MarkoSpace.md),
              const MarkoLoader(size: 14),
            ],
          ],
        ),
        const SizedBox(height: MarkoSpace.md),
        const CatalogFilterBar(),
      ],
    );
  }
}

/// Actions applied to every ticked card at once; shown only while something
/// is ticked, so the catalog looks unchanged the rest of the time.
class _SelectionBar extends ConsumerStatefulWidget {
  const _SelectionBar({
    required this.count,
    required this.total,
    required this.allMatching,
    required this.job,
  });

  final int count;

  /// Everything the current filter matches, loaded or not.
  final int total;

  /// The selection is the whole filtered catalog, not the ticked cards.
  final bool allMatching;

  /// A running catalog-wide refresh, if any.
  final SyncRun? job;

  @override
  ConsumerState<_SelectionBar> createState() => _SelectionBarState();
}

class _SelectionBarState extends ConsumerState<_SelectionBar> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    // На вузькому екрані підписи кнопок не влазять у рядок — лишаються іконки.
    final compact = MediaQuery.sizeOf(context).width < 840;
    final actions = [
      if (!widget.allMatching && widget.count < widget.total)
        _action(
          compact: compact,
          icon: HeroIcons.checkCircle,
          label: 'Усі ${widget.total} у каталозі',
          onPressed: _busy
              ? null
              : ref.read(productsControllerProvider.notifier).selectAllMatching,
        ),
      _action(
        compact: compact,
        icon: HeroIcons.arrowPath,
        label: 'Оновити за посиланням',
        onPressed: _busy ? null : _refresh,
        iconOverride: _busy ? const MarkoLoader(size: 15) : null,
      ),
      _action(
        compact: compact,
        icon: HeroIcons.trash,
        label: 'Видалити',
        color: colors.negative,
        onPressed: _busy ? null : _delete,
      ),
      _action(
        compact: compact,
        icon: HeroIcons.xMark,
        label: 'Скасувати',
        onPressed: _busy
            ? null
            : ref.read(productsControllerProvider.notifier).clearSelection,
      ),
    ];
    final box = DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
        boxShadow: MarkoShadow.overlay,
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: MarkoSpace.lg,
          vertical: MarkoSpace.sm,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Flexible(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    widget.allMatching
                        ? 'Вибрано всі ${widget.total}'
                        : 'Вибрано ${widget.count}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                      color: colors.ink,
                    ),
                  ),
                  if (widget.job != null)
                    Text(
                      'Оновлення ${widget.job!.statusLabel}: '
                      '${widget.job!.progressCurrent}'
                      '${widget.job!.progressTotal == null ? '' : ' з ${widget.job!.progressTotal}'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: MarkoType.caption.copyWith(color: colors.faint),
                    ),
                ],
              ),
            ),
            const SizedBox(width: MarkoSpace.md),
            // Один рядок: кнопки дій не переносяться.
            Row(
              mainAxisSize: MainAxisSize.min,
              spacing: compact ? MarkoSpace.xs : MarkoSpace.sm,
              children: actions,
            ),
          ],
        ),
      ),
    );

    return box;
  }

  /// Кнопка дії: з підписом на широкому екрані, сама іконка на вузькому.
  Widget _action({
    required bool compact,
    required HeroIcons icon,
    required String label,
    required VoidCallback? onPressed,
    Color? color,
    Widget? iconOverride,
  }) {
    final colors = MarkoTheme.of(context);
    return compact
        ? IconButton(
            tooltip: label,
            onPressed: onPressed,
            style: IconButton.styleFrom(
              foregroundColor: color ?? colors.ink,
              backgroundColor: colors.surfaceMuted,
              highlightColor: (color ?? colors.brand).withValues(alpha: 0.16),
            ),
            icon: iconOverride ?? HeroIcon(icon, size: 19),
          )
        : TextButton.icon(
            onPressed: onPressed,
            style: color == null
                ? null
                : TextButton.styleFrom(foregroundColor: color),
            icon: iconOverride ?? HeroIcon(icon, size: 17),
            label: Text(label),
          );
  }

  Future<void> _refresh() async {
    final total = widget.count;
    final controller = ref.read(productsControllerProvider.notifier);
    setState(() => _busy = true);
    try {
      // Весь каталог — це тисячі сторінок: працює фонове завдання, а плашка
      // показує його поступ. Кілька позначених оновлюємо тут і зараз.
      if (widget.allMatching) {
        showMarkoToast(
          context,
          message: 'Оновлюємо $total товарів у фоні…',
          tone: MarkoMessageTone.info,
        );
        await controller.refreshAllMatching();
        return;
      }
      final failed = await controller.refreshSelected();
      if (!mounted) return;
      showMarkoToast(
        context,
        message: failed == 0
            ? 'Оновлено товарів: ${total - failed}'
            : 'Оновлено ${total - failed} з $total, не вдалося: $failed',
        tone: failed == 0 ? MarkoMessageTone.success : MarkoMessageTone.warning,
      );
    } catch (error) {
      if (mounted) {
        showMarkoToast(
          context,
          title: 'Не вдалося оновити',
          message: '$error',
          tone: MarkoMessageTone.error,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final total = widget.count;
    if (!await confirmBulkProductDeletion(context, count: total)) return;
    final controller = ref.read(productsControllerProvider.notifier);
    setState(() => _busy = true);
    try {
      if (widget.allMatching) {
        final deleted = await controller.deleteAllMatching();
        if (!mounted) return;
        showMarkoToast(context, message: 'Видалено товарів: $deleted');
        return;
      }
      final failed = await controller.deleteSelected();
      if (!mounted) return;
      showMarkoToast(
        context,
        message: failed == 0
            ? 'Видалено товарів: $total'
            : 'Видалено ${total - failed} з $total, не вдалося: $failed',
        tone: failed == 0 ? MarkoMessageTone.success : MarkoMessageTone.warning,
      );
    } catch (error) {
      if (mounted) {
        showMarkoToast(
          context,
          title: 'Не вдалося видалити',
          message: '$error',
          tone: MarkoMessageTone.error,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

/// The search, price range, and sort controls used in both the catalog toolbar
/// and the sticky header when scrolled.
class CatalogFilterBar extends ConsumerWidget {
  const CatalogFilterBar({this.showSearch = true, super.key});

  final bool showSearch;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(productsControllerProvider).value;
    final controller = ref.read(productsControllerProvider.notifier);
    final sort = state?.sort ?? ProductSort.name;

    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 740;

        if (compact) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (showSearch) ...[
                const CatalogSearchField(),
                const SizedBox(height: MarkoSpace.sm),
              ],
              CatalogSourceToggle(
                source: state?.source ?? ProductSource.all,
                onChanged: controller.filterBySource,
                fullWidth: true,
              ),
              const SizedBox(height: MarkoSpace.sm),
              CatalogPriceRange(
                onChanged: controller.filterByPrice,
                fullWidth: true,
              ),
              const SizedBox(height: MarkoSpace.sm),
              CatalogSortMenu(
                sort: sort,
                onChanged: controller.sortBy,
                fullWidth: true,
              ),
            ],
          );
        }

        final filters = Wrap(
          spacing: MarkoSpace.sm,
          runSpacing: MarkoSpace.sm,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            CatalogSourceToggle(
              source: state?.source ?? ProductSource.all,
              onChanged: controller.filterBySource,
            ),
            CatalogPriceRange(onChanged: controller.filterByPrice),
            CatalogSortMenu(sort: sort, onChanged: controller.sortBy),
          ],
        );

        if (!showSearch) {
          return filters;
        }

        return Row(
          children: [
            const Expanded(child: CatalogSearchField()),
            const SizedBox(width: MarkoSpace.md),
            filters,
          ],
        );
      },
    );
  }
}

/// Price bounds, in the catalog's currency. Empty means no bound.
class CatalogPriceRange extends ConsumerWidget {
  const CatalogPriceRange({
    required this.onChanged,
    this.fullWidth = false,
    super.key,
  });

  final void Function(double? min, double? max) onChanged;
  final bool fullWidth;

  static double? _parse(String value) =>
      double.tryParse(value.trim().replaceAll(' ', '').replaceAll(',', '.'));

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final min = ref.watch(catalogPriceMinFieldProvider);
    final max = ref.watch(catalogPriceMaxFieldProvider);

    void emit() => onChanged(_parse(min.text), _parse(max.text));

    if (fullWidth) {
      return Row(
        children: [
          Expanded(
            child: _PriceField(
              width: double.infinity,
              controller: min,
              hint: 'Ціна від',
              onChanged: emit,
            ),
          ),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: _PriceField(
              width: double.infinity,
              controller: max,
              hint: 'Ціна до',
              onChanged: emit,
            ),
          ),
        ],
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final hasTightWidth =
            constraints.maxWidth.isFinite && constraints.maxWidth < 320;
        final fieldWidth = hasTightWidth
            ? (constraints.maxWidth - MarkoSpace.sm) / 2
            : 140.0;

        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _PriceField(
              width: fieldWidth > 60 ? fieldWidth : 140.0,
              controller: min,
              hint: 'Ціна від',
              onChanged: emit,
            ),
            const SizedBox(width: MarkoSpace.sm),
            _PriceField(
              width: fieldWidth > 60 ? fieldWidth : 140.0,
              controller: max,
              hint: 'Ціна до',
              onChanged: emit,
            ),
          ],
        );
      },
    );
  }
}

class _PriceField extends StatelessWidget {
  const _PriceField({
    required this.controller,
    required this.hint,
    required this.onChanged,
    this.width = 140.0,
  });

  final TextEditingController controller;
  final String hint;
  final VoidCallback onChanged;
  final double width;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: width,
      child: MarkoTextField(
        controller: controller,
        hintText: hint,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        inputFormatters: const [ThousandsPriceInputFormatter()],
        // Always-on ₴ marker; it also pins the field to the search field's
        // height via the shared prefix constraints.
        prefix: Text(
          '₴',
          style: TextStyle(color: MarkoTheme.of(context).faint, fontSize: 13.5),
        ),
        onChanged: (_) => onChanged(),
      ),
    );
  }
}

/// Where the products came from: everything, an uploaded XLSX, or a Prom sync.
/// A segmented switch rather than a menu — there are only three states and the
/// current one should be readable without opening anything.
class CatalogSourceToggle extends StatelessWidget {
  const CatalogSourceToggle({
    required this.source,
    required this.onChanged,
    this.fullWidth = false,
    super.key,
  });

  final ProductSource source;
  final ValueChanged<ProductSource> onChanged;
  final bool fullWidth;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final selectedIndex = ProductSource.values.indexOf(source);
    final count = ProductSource.values.length;
    final alignmentX = count > 1
        ? (2 * selectedIndex / (count - 1)) - 1.0
        : 0.0;

    return Container(
      height: MarkoLayout.fieldHeightOf(context),
      width: fullWidth ? double.infinity : 228,
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
        boxShadow: MarkoShadow.card,
      ),
      child: Stack(
        children: [
          AnimatedAlign(
            alignment: Alignment(alignmentX, 0.0),
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            child: FractionallySizedBox(
              widthFactor: 1.0 / count,
              heightFactor: 1.0,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: colors.surfaceMuted,
                  borderRadius: BorderRadius.circular(MarkoRadius.sm),
                  border: Border.all(
                    color: colors.borderStrong.withValues(alpha: 0.5),
                  ),
                  boxShadow: MarkoShadow.segmentedItem,
                ),
              ),
            ),
          ),
          Row(
            children: [
              for (final option in ProductSource.values)
                Expanded(
                  child: _SourceSegment(
                    label: option.label,
                    selected: option == source,
                    onPressed: () => onChanged(option),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SourceSegment extends StatefulWidget {
  const _SourceSegment({
    required this.label,
    required this.selected,
    required this.onPressed,
  });

  final String label;
  final bool selected;
  final VoidCallback onPressed;

  @override
  State<_SourceSegment> createState() => _SourceSegmentState();
}

class _SourceSegmentState extends State<_SourceSegment> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isSelected = widget.selected;
    final baseStyle =
        Theme.of(context).textTheme.bodyMedium?.copyWith(
          fontSize: MarkoLayout.fieldFontSizeOf(context),
        ) ??
        const TextStyle(fontSize: 13.5);

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: widget.onPressed,
        child: Center(
          child: AnimatedDefaultTextStyle(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOut,
            style: baseStyle.copyWith(
              color: isSelected
                  ? colors.ink
                  : (_hovered ? colors.ink : colors.faint),
            ),
            child: Text(
              widget.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ),
      ),
    );
  }
}

class CatalogSortMenu extends StatefulWidget {
  const CatalogSortMenu({
    required this.sort,
    required this.onChanged,
    this.fullWidth = false,
    super.key,
  });

  final ProductSort sort;
  final ValueChanged<ProductSort> onChanged;
  final bool fullWidth;

  @override
  State<CatalogSortMenu> createState() => _CatalogSortMenuState();
}

class _CatalogSortMenuState extends State<CatalogSortMenu> {
  final _menuController = MenuController();
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final textStyle =
        Theme.of(context).textTheme.bodyMedium?.copyWith(
          fontSize: MarkoLayout.fieldFontSizeOf(context),
        ) ??
        const TextStyle(fontSize: 13.5);

    return MenuAnchor(
      controller: _menuController,
      alignmentOffset: const Offset(0, 4),
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(colors.surface),
        elevation: const WidgetStatePropertyAll(10),
        shadowColor: WidgetStatePropertyAll(
          Colors.black.withValues(alpha: 0.18),
        ),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(MarkoRadius.md),
            side: BorderSide(color: colors.border),
          ),
        ),
        padding: const WidgetStatePropertyAll(EdgeInsets.all(MarkoSpace.xxs)),
      ),
      menuChildren: [
        for (final option in ProductSort.values)
          MenuItemButton(
            onPressed: () => widget.onChanged(option),
            style: ButtonStyle(
              minimumSize: const WidgetStatePropertyAll(Size(190, 36)),
              padding: const WidgetStatePropertyAll(
                EdgeInsets.symmetric(
                  horizontal: MarkoSpace.md,
                  vertical: MarkoSpace.xs,
                ),
              ),
              shape: WidgetStatePropertyAll(
                RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(MarkoRadius.sm),
                ),
              ),
              overlayColor: WidgetStateProperty.resolveWith((states) {
                if (states.contains(WidgetState.hovered) ||
                    states.contains(WidgetState.focused)) {
                  return colors.surfaceMuted;
                }
                if (states.contains(WidgetState.pressed)) {
                  return colors.border;
                }
                return Colors.transparent;
              }),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.max,
              children: [
                Expanded(
                  child: Text(
                    option.label,
                    style: textStyle.copyWith(
                      color: option == widget.sort ? colors.ink : colors.muted,
                      fontWeight: option == widget.sort
                          ? FontWeight.w600
                          : FontWeight.w400,
                    ),
                  ),
                ),
                const SizedBox(width: MarkoSpace.sm),
                if (option == widget.sort)
                  HeroIcon(HeroIcons.check, size: 16, color: colors.ink)
                else
                  const SizedBox(width: 16),
              ],
            ),
          ),
      ],
      builder: (context, controller, child) {
        final isOpen = controller.isOpen;
        return MouseRegion(
          cursor: SystemMouseCursors.click,
          onEnter: (_) => setState(() => _hovered = true),
          onExit: (_) => setState(() => _hovered = false),
          child: GestureDetector(
            onTap: () {
              if (controller.isOpen) {
                controller.close();
              } else {
                controller.open();
              }
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              curve: Curves.easeInOut,
              height: MarkoLayout.fieldHeightOf(context),
              width: widget.fullWidth ? double.infinity : null,
              padding: const EdgeInsets.symmetric(horizontal: MarkoSpace.md),
              decoration: BoxDecoration(
                color: _hovered || isOpen
                    ? colors.surfaceMuted
                    : colors.surface,
                borderRadius: BorderRadius.circular(MarkoRadius.md),
                border: Border.all(
                  color: _hovered || isOpen
                      ? colors.borderStrong
                      : colors.border,
                ),
                boxShadow: _hovered || isOpen
                    ? MarkoShadow.hover
                    : MarkoShadow.card,
              ),
              child: Row(
                mainAxisSize:
                    widget.fullWidth ? MainAxisSize.max : MainAxisSize.min,
                mainAxisAlignment: widget.fullWidth
                    ? MainAxisAlignment.spaceBetween
                    : MainAxisAlignment.start,
                children: [
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      HeroIcon(
                        HeroIcons.arrowsUpDown,
                        size: 15,
                        color: _hovered || isOpen ? colors.ink : colors.faint,
                      ),
                      const SizedBox(width: 8),
                      Text(
                        widget.sort.label,
                        style: textStyle.copyWith(
                          color: colors.ink,
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(width: 6),
                  AnimatedRotation(
                    turns: isOpen ? 0.5 : 0,
                    duration: const Duration(milliseconds: 150),
                    child: HeroIcon(
                      HeroIcons.chevronDown,
                      size: 14,
                      color: _hovered || isOpen ? colors.ink : colors.faint,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

const _gridSpacing = 16.0;
const _cardTextHeight = 118.0;

double _tileWidth(double available, int columns) =>
    (available - _gridSpacing * (columns - 1)) / columns;

/// Один стовпчик означає горизонтальні картки — сітка з квадратних фото
/// починається тільки там, де їх поміщається щонайменше три.
int _columnsFor(double width) => switch (width) {
  >= 1100 => 5,
  >= 880 => 4,
  >= 640 => 3,
  _ => 1,
};

class _ProductGrid extends StatelessWidget {
  const _ProductGrid({
    required this.products,
    required this.selectedId,
    required this.checkedIds,
    required this.onOpen,
    required this.onCheck,
    this.ghostCount = 0,
  });

  final List<StoreProduct> products;
  final String? selectedId;
  final Set<String> checkedIds;
  final ValueChanged<StoreProduct> onOpen;
  final ValueChanged<String> onCheck;

  /// Shimmering placeholders tacked onto the end while an import is running.
  final int ghostCount;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = _columnsFor(constraints.maxWidth);
        // На вузькому екрані — один стовпчик компактних рядків: більше товарів
        // на екрані, ніж від картки з фото на всю ширину.
        final horizontal = columns == 1;
        final selecting = checkedIds.isNotEmpty;
        return GridView.builder(
          shrinkWrap: true,
          primary: false,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            mainAxisSpacing: horizontal ? MarkoSpace.sm : _gridSpacing,
            crossAxisSpacing: _gridSpacing,
            // Square image plus a fixed text block: an aspect ratio would
            // squeeze the text and overflow at some column counts.
            mainAxisExtent: horizontal
                ? productRowHeight
                : _tileWidth(constraints.maxWidth, columns) + _cardTextHeight,
          ),
          itemCount: products.length + ghostCount,
          itemBuilder: (context, index) {
            if (index >= products.length) {
              return ProductCardSkeleton(horizontal: horizontal);
            }
            final product = products[index];
            // Ключ за id: щойно спарсений товар — новий елемент, і тільки він
            // програє появу; решта карток лишаються на місці.
            // Чужі магазини не редагуються — нема сенсу їх позначати.
            final toggle = product.canManage
                ? () {
                    HapticFeedback.selectionClick();
                    onCheck(product.id);
                  }
                : null;
            return _Appear(
              key: ValueKey(product.id),
              child: ProductCard(
                product: product,
                horizontal: horizontal,
                selected: product.id == selectedId,
                checked: checkedIds.contains(product.id),
                // На дотику ховера нема: позначки видно, поки триває вибір.
                alwaysShowCheck: horizontal && selecting,
                onCheckChanged: product.canManage
                    ? () => onCheck(product.id)
                    : null,
                // Утримання починає вибір, далі тап позначає решту.
                onLongPress: horizontal ? toggle : null,
                onTap: horizontal && selecting && toggle != null
                    ? toggle
                    : () => onOpen(product),
              ),
            );
          },
        );
      },
    );
  }
}

/// Fades and lifts a card in once, when it first lands in the grid.
class _Appear extends StatelessWidget {
  const _Appear({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 340),
      curve: Curves.easeOutCubic,
      builder: (context, value, child) => Opacity(
        opacity: value,
        child: Transform.translate(
          offset: Offset(0, 12 * (1 - value)),
          child: child,
        ),
      ),
      child: child,
    );
  }
}

class _GridSkeletonSliver extends StatelessWidget {
  const _GridSkeletonSliver();

  @override
  Widget build(BuildContext context) {
    return SliverToBoxAdapter(
      child: MarkoContentFrame(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final columns = _columnsFor(constraints.maxWidth);
            final horizontal = columns == 1;
            return GridView.builder(
              shrinkWrap: true,
              primary: false,
              physics: const NeverScrollableScrollPhysics(),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: columns,
                mainAxisSpacing: horizontal ? MarkoSpace.sm : _gridSpacing,
                crossAxisSpacing: _gridSpacing,
                mainAxisExtent: horizontal
                    ? productRowHeight
                    : _tileWidth(constraints.maxWidth, columns) +
                          _cardTextHeight,
              ),
              itemCount: horizontal ? 6 : columns * 3,
              itemBuilder: (context, index) =>
                  ProductCardSkeleton(horizontal: horizontal),
            );
          },
        ),
      ),
    );
  }
}

class _EmptyCatalog extends ConsumerWidget {
  const _EmptyCatalog({required this.query, this.hasActiveFilters = false});

  final String query;
  final bool hasActiveFilters;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final searching = query.trim().isNotEmpty;
    final filtered = hasActiveFilters || searching;

    return MarkoEmptyState(
      icon: filtered ? HeroIcons.magnifyingGlass : HeroIcons.archiveBox,
      title: filtered ? 'Нічого не знайдено' : 'Товарів поки немає',
      description: filtered
          ? 'Спробуйте змінити пошуковий запит або скиньте активні фільтри.'
          : 'Додайте каталог із Prom або завантажте XLSX.',
      action: filtered
          ? MarkoButton(
              label: 'Скинути фільтри',
              icon: HeroIcons.arrowPath,
              variant: MarkoButtonVariant.secondary,
              onPressed: () => resetCatalogFilters(ref),
            )
          : MarkoButton(
              label: 'Імпорт каталогу',
              icon: HeroIcons.arrowDownTray,
              onPressed: () => showCatalogImport(context),
            ),
    );
  }
}

class _RetryView extends StatelessWidget {
  const _RetryView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        MarkoInlineMessage(message: message, tone: MarkoMessageTone.error),
        const SizedBox(height: MarkoSpace.md),
        MarkoButton(label: 'Повторити', onPressed: onRetry),
      ],
    );
  }
}

Future<bool> pickAndImportCatalog(WidgetRef ref) async {
  final file = await FilePicker.pickFile(
    type: FileType.custom,
    allowedExtensions: const ['xlsx'],
  );
  if (file == null) return false;
  final bytes = await file.readAsBytes();
  if (bytes.isEmpty) return false;
  final imported = await ref
      .read(catalogImportProvider.notifier)
      .importFile(file.name, bytes);
  if (imported) {
    await ref.read(productsControllerProvider.notifier).refresh();
  }
  return imported;
}

/// What a brand new account sees instead of the catalog: how the first import
/// works on the left, the same two source cards as the import modal on the
/// right. The toolbar, search and filters only appear once products exist.
class CatalogOnboarding extends StatelessWidget {
  const CatalogOnboarding({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        const cards = CatalogSourceCards();
        // На вузькому екрані спершу дають імпортувати, і лише тим, у кого не
        // вийшло, показують кроки — за роздільником, як «або через пошту».
        if (constraints.maxWidth < 900) {
          return const Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Instructions(steps: false),
              SizedBox(height: MarkoSpace.xl),
              cards,
              SizedBox(height: MarkoSpace.xxl),
              MarkoLabelledDivider(label: 'Інструкція, якщо щось не виходить'),
              SizedBox(height: MarkoSpace.xl),
              _Instructions(intro: false),
            ],
          );
        }
        return const Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Instructions(steps: false),
            SizedBox(height: MarkoSpace.xl),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 5, child: cards),
                SizedBox(width: MarkoSpace.xxxl),
                Expanded(flex: 6, child: _Instructions(intro: false)),
              ],
            ),
          ],
        );
      },
    );
  }
}

class _Step {
  const _Step({required this.title, required this.body, required this.icon});

  final String title;
  final String body;
  final HeroIcons icon;
}

const _steps = [
  _Step(
    title: 'Експортуйте каталог із Prom.ua',
    body:
        'У кабінеті Prom.ua відкрийте «Товари та послуги», натисніть «Експорт» і виберіть формат XLSX.',
    icon: HeroIcons.arrowDownTray,
  ),
  _Step(
    title: 'Завантажте XLSX-файл у Marko',
    body:
        'Оберіть експортований XLSX-файл на пристрої. Marko імпортує назви, ціни, бренди, OEM-номери та артикули виробників.',
    icon: HeroIcons.bolt,
  ),
  _Step(
    title: 'Перевіряйте ціни конкурентів',
    body:
        'Відкрийте товар або знайдіть його за OEM, щоб побачити мінімальну й медіанну ціни та пропозиції на Avto.pro.',
    icon: HeroIcons.presentationChartLine,
  ),
];

class _Instructions extends StatelessWidget {
  const _Instructions({this.intro = true, this.steps = true});

  /// Заголовок із підзаголовком і самі кроки на мобілці роз'їжджаються
  /// в різні кінці екрана, тому кожну половину можна показати окремо.
  final bool intro;
  final bool steps;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (intro) ...[
          Text(
            'Додайте товари з XLSX-вивантаження',
            style: Theme.of(
              context,
            ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: MarkoSpace.sm),
          Text(
            'Експортуйте асортимент із кабінету Prom.ua та завантажте '
            'файл у Marko. Після обробки стануть доступні каталог, пошук, фільтри й аналітика цін конкурентів.',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: colors.muted, height: 1.45),
          ),
        ],
        if (intro && steps) const SizedBox(height: MarkoSpace.xl),
        if (steps)
          for (var i = 0; i < _steps.length; i++) ...[
            if (i > 0) const SizedBox(height: MarkoSpace.md),
            _StepRow(index: i + 1, step: _steps[i]),
          ],
      ],
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.index, required this.step});

  final int index;
  final _Step step;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: colors.brandSoft,
              borderRadius: BorderRadius.circular(MarkoRadius.md),
              border: Border.all(color: colors.brand.withValues(alpha: 0.2)),
            ),
            alignment: Alignment.center,
            child: Text(
              '0$index',
              style: MarkoType.price.copyWith(
                color: colors.brand,
                fontSize: 13,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: MarkoSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  step.title,
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  step.body,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.muted,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
