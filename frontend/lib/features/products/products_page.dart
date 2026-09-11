import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_loader.dart';
import 'products_controller.dart';
import 'products_models.dart';
import 'widgets/catalog_filters.dart';
import 'widgets/catalog_onboarding.dart';
import 'widgets/dynamic_sync_island.dart';
import 'widgets/product_details_panel.dart';
import 'widgets/product_grid.dart';
import 'widgets/selection_bar.dart';
import 'widgets/source_panel.dart';
import 'widgets/stores_strip.dart';

/// Нижня панель дашборда (імпорт каталогу / ціни конкурентів) на мобілці.
const _bottomBarHeight = 76.0;

/// Висота плашки дій — потрібна, щоб розсунути те, що плаває над нею.
const _selectionBarHeight = 56.0;

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
    final compact = MarkoLayout.compactOf(context);
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
                        if (onboarding) ...[
                          const SizedBox(height: MarkoSpace.md),
                          const CatalogOnboarding(),
                        ],
                      ],
                    ),
                  ),
                ),
                if (!onboarding) ...[
                  const SliverToBoxAdapter(child: StoresStrip()),
                  SliverToBoxAdapter(
                    child: MarkoContentFrame(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
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
                ],
                ...switch (catalog) {
                  AsyncLoading() => [const GridSkeletonSliver()],
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
                child: SelectionBar(
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
      return const [GridSkeletonSliver()];
    }

    if (state.page.items.isEmpty) {
      return [
        SliverFillRemaining(
          hasScrollBody: false,
          child: Padding(
            padding: const EdgeInsets.only(bottom: 72),
            child: MarkoContentFrame(
              child: Center(
                child: EmptyCatalog(
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
          child: ProductGrid(
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
            const Spacer(),
            // Переоцінка живе окремим вікном: усередині історія прогонів,
            // сотні карток і вивантаження — у тулбарі це не поміщається.
            // На телефоні підпис не влазить у рядок — лишається іконка.
            if (MarkoLayout.compactOf(context))
              IconButton(
                tooltip: 'Переоцінка',
                onPressed: () => context.go('/reprice'),
                icon: HeroIcon(
                  HeroIcons.calculator,
                  size: 18,
                  color: MarkoTheme.of(context).ink,
                ),
              )
            else
              MarkoButton.secondary(
                label: 'Переоцінка',
                icon: HeroIcons.calculator,
                onPressed: () => context.go('/reprice'),
              ),
          ],
        ),
        const SizedBox(height: MarkoSpace.md),
        const CatalogFilterBar(),
      ],
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
