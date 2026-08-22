import 'dart:ui';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import 'products_controller.dart';
import 'products_models.dart';
import 'widgets/help_overlay.dart';
import 'widgets/product_card.dart';
import 'widgets/product_details_panel.dart';
import 'widgets/source_panel.dart';

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
                        if (state != null && state.isPristineEmpty)
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
                  _ => _catalogSlivers(state!),
                },
                const SliverToBoxAdapter(child: SizedBox(height: 72)),
              ],
            ),
          ),
          // Centered floating capsule pill above the bottom edge / compact bar.
          Positioned(
            left: 0,
            right: 0,
            bottom: MediaQuery.sizeOf(context).width < 840 ? 76 : MarkoSpace.xl,
            child: Center(
              child: _ScrollTopButton(
                visible: _showScrollTop,
                onPressed: _scrollToTop,
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _catalogSlivers(CatalogState state) {
    // Onboarding already fills the screen and says the same thing.
    if (state.isPristineEmpty) return const [];
    if (state.page.items.isEmpty) {
      return [
        SliverToBoxAdapter(
          child: MarkoContentFrame(child: _EmptyCatalog(query: state.query)),
        ),
      ];
    }
    return [
      SliverToBoxAdapter(
        child: MarkoContentFrame(
          child: _ProductGrid(
            products: state.page.items,
            selectedId: state.selected?.id,
            onOpen: _openDetails,
          ),
        ),
      ),
      if (state.isLoadingMore)
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Center(child: CircularProgressIndicator()),
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
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 160),
                    curve: Curves.easeOutCubic,
                    transform: Matrix4.translationValues(
                      0,
                      _hovered ? -2.0 : 0,
                      0,
                    ),
                    padding: const EdgeInsets.symmetric(
                      horizontal: MarkoSpace.lg,
                      vertical: 9.5,
                    ),
                    decoration: BoxDecoration(
                      color: colors.surface.withValues(alpha: 0.94),
                      borderRadius: BorderRadius.circular(999),
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
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(999),
                      child: BackdropFilter(
                        filter: ImageFilter.blur(sigmaX: 8, sigmaY: 8),
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
                                shape: BoxShape.circle,
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
                              'Повернутися вгору',
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
              const SizedBox.square(
                dimension: 14,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ],
          ],
        ),
        const SizedBox(height: MarkoSpace.md),
        const CatalogFilterBar(),
      ],
    );
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
        final filters = Wrap(
          spacing: MarkoSpace.sm,
          runSpacing: MarkoSpace.sm,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            CatalogPriceRange(onChanged: controller.filterByPrice),
            CatalogSortMenu(sort: sort, onChanged: controller.sortBy),
          ],
        );

        if (!showSearch) {
          return filters;
        }

        const searchField = CatalogSearchField();

        if (constraints.maxWidth < 740) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              searchField,
              const SizedBox(height: MarkoSpace.sm),
              filters,
            ],
          );
        }

        return Row(
          children: [
            const Expanded(child: searchField),
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
  const CatalogPriceRange({required this.onChanged, super.key});

  final void Function(double? min, double? max) onChanged;

  static double? _parse(String value) =>
      double.tryParse(value.trim().replaceAll(' ', '').replaceAll(',', '.'));

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final min = ref.watch(catalogPriceMinFieldProvider);
    final max = ref.watch(catalogPriceMaxFieldProvider);

    void emit() => onChanged(_parse(min.text), _parse(max.text));

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _PriceField(controller: min, hint: 'Ціна від', onChanged: emit),
        const SizedBox(width: MarkoSpace.sm),
        _PriceField(controller: max, hint: 'Ціна до', onChanged: emit),
      ],
    );
  }
}

class _PriceField extends StatelessWidget {
  const _PriceField({
    required this.controller,
    required this.hint,
    required this.onChanged,
  });

  final TextEditingController controller;
  final String hint;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 150,
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

class CatalogSortMenu extends StatefulWidget {
  const CatalogSortMenu({
    required this.sort,
    required this.onChanged,
    super.key,
  });

  final ProductSort sort;
  final ValueChanged<ProductSort> onChanged;

  @override
  State<CatalogSortMenu> createState() => _CatalogSortMenuState();
}

class _CatalogSortMenuState extends State<CatalogSortMenu> {
  final _menuController = MenuController();
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
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
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: option == widget.sort ? colors.brand : colors.ink,
                      fontWeight: option == widget.sort
                          ? FontWeight.w600
                          : FontWeight.w400,
                      fontSize: 13.5,
                    ),
                  ),
                ),
                const SizedBox(width: MarkoSpace.sm),
                if (option == widget.sort)
                  HeroIcon(HeroIcons.check, size: 16, color: colors.brand)
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
                mainAxisSize: MainAxisSize.min,
                children: [
                  HeroIcon(
                    HeroIcons.arrowsUpDown,
                    size: 15,
                    color: _hovered || isOpen ? colors.ink : colors.faint,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    widget.sort.label,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      fontWeight: FontWeight.w500,
                      fontSize: 13.5,
                    ),
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

class _ProductGrid extends StatelessWidget {
  const _ProductGrid({
    required this.products,
    required this.selectedId,
    required this.onOpen,
  });

  final List<StoreProduct> products;
  final String? selectedId;
  final ValueChanged<StoreProduct> onOpen;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = switch (constraints.maxWidth) {
          >= 1100 => 5,
          >= 880 => 4,
          >= 640 => 3,
          >= 420 => 2,
          _ => 1,
        };
        return GridView.builder(
          shrinkWrap: true,
          primary: false,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            mainAxisSpacing: _gridSpacing,
            crossAxisSpacing: _gridSpacing,
            // Square image plus a fixed text block: an aspect ratio would
            // squeeze the text and overflow at some column counts.
            mainAxisExtent:
                _tileWidth(constraints.maxWidth, columns) + _cardTextHeight,
          ),
          itemCount: products.length,
          itemBuilder: (context, index) {
            final product = products[index];
            return ProductCard(
              product: product,
              selected: product.id == selectedId,
              onTap: () => onOpen(product),
            );
          },
        );
      },
    );
  }
}

class _GridSkeletonSliver extends StatelessWidget {
  const _GridSkeletonSliver();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return SliverToBoxAdapter(
      child: MarkoContentFrame(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth >= 880 ? 4 : 2;
            return GridView.count(
              shrinkWrap: true,
              primary: false,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: columns,
              mainAxisSpacing: _gridSpacing,
              crossAxisSpacing: _gridSpacing,
              childAspectRatio:
                  _tileWidth(constraints.maxWidth, columns) /
                  (_tileWidth(constraints.maxWidth, columns) + _cardTextHeight),
              children: List.generate(
                columns * 2,
                (_) => DecoratedBox(
                  decoration: BoxDecoration(
                    color: colors.surfaceMuted,
                    borderRadius: BorderRadius.circular(MarkoRadius.xl),
                    border: Border.all(color: colors.border),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _EmptyCatalog extends StatelessWidget {
  const _EmptyCatalog({required this.query});

  final String query;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final searching = query.trim().isNotEmpty;
    return MarkoPanel(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.xxl,
        vertical: MarkoSpace.huge,
      ),
      child: Column(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(MarkoRadius.lg),
            ),
            alignment: Alignment.center,
            child: HeroIcon(
              searching
                  ? HeroIcons.magnifyingGlassCircle
                  : HeroIcons.archiveBox,
              color: colors.faint,
              size: 20,
            ),
          ),
          const SizedBox(height: MarkoSpace.md),
          Text(
            searching ? 'Нічого не знайдено' : 'Товарів поки немає',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: MarkoSpace.xs),
          Text(
            searching
                ? 'Спробуйте інший запит або скиньте фільтри.'
                : 'Додайте каталог із Prom або завантажте XLSX.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (!searching) ...[
            const SizedBox(height: MarkoSpace.lg),
            MarkoButton(
              label: 'Імпорт каталогу',
              icon: HeroIcons.arrowDownTray,
              onPressed: () => showCatalogImport(context),
            ),
          ],
        ],
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

/// Kept so the file picker lives next to the page that owns the catalog.
/// Returns whether products actually landed in the catalog.
Future<bool> pickAndImportCatalog(WidgetRef ref) async {
  final file = await FilePicker.pickFile(
    type: FileType.custom,
    allowedExtensions: const ['xlsx'],
  );
  if (file == null) return false;
  final bytes = await file.readAsBytes();
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
        if (constraints.maxWidth < 900) {
          return const Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Instructions(),
              SizedBox(height: MarkoSpace.xxl),
              cards,
            ],
          );
        }
        return const Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(flex: 6, child: _Instructions()),
            SizedBox(width: MarkoSpace.xxxl),
            Expanded(flex: 5, child: cards),
          ],
        );
      },
    );
  }
}

class _Step {
  const _Step({
    required this.title,
    required this.body,
    required this.tag,
    required this.icon,
  });

  final String title;
  final String body;
  final String tag;
  final HeroIcons icon;
}

const _steps = [
  _Step(
    title: 'Експортуйте файл XLSX або вкажіть магазин Prom',
    body:
        'Рекомендуємо XLSX експорт із кабінету Prom: він містить оригінальні номери OEM та артикули виробників для точної звірки.',
    tag: 'Prom.ua XLSX',
    icon: HeroIcons.arrowDownTray,
  ),
  _Step(
    title: 'Автоматичне завантаження каталогу',
    body:
        'Сервер Marko обробляє файл за 1–2 хвилини, формує зручну сітку товарів, фільтри цін та створює структуру пошуку.',
    tag: 'Швидка обробка',
    icon: HeroIcons.bolt,
  ),
  _Step(
    title: 'Миттєва аналітика цін на Avto.pro',
    body:
        'Клікайте на будь-яку картку товару або шукайте за OEM, щоб бачити мінімальні й медіанні ринкові ціни та пропозиції конкурентів.',
    tag: 'Avto.pro Live',
    icon: HeroIcons.presentationChartLine,
  ),
];

class _Instructions extends StatelessWidget {
  const _Instructions();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Почніть з імпорту каталогу',
          style: Theme.of(
            context,
          ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: MarkoSpace.sm),
        Text(
          'Товарів поки немає. Завантажте ваш асортимент один раз — і відкриється '
          'повноцінний каталог, швидкий пошук, фільтри за ₴ та аналітика цін конкурентів.',
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: colors.muted, height: 1.45),
        ),
        const SizedBox(height: MarkoSpace.xl),
        for (var i = 0; i < _steps.length; i++) ...[
          if (i > 0) const SizedBox(height: MarkoSpace.md),
          _StepRow(index: i + 1, step: _steps[i]),
        ],
        const SizedBox(height: MarkoSpace.xl),
        Container(
          padding: const EdgeInsets.all(MarkoSpace.md),
          decoration: BoxDecoration(
            color: colors.surfaceMuted,
            borderRadius: BorderRadius.circular(MarkoRadius.md),
            border: Border.all(color: colors.border),
          ),
          child: Row(
            children: [
              HeroIcon(HeroIcons.bookOpen, size: 18, color: colors.muted),
              const SizedBox(width: MarkoSpace.sm),
              Expanded(
                child: Text(
                  'Потрібна допомога? Перегляньте короткий довідник.',
                  style: TextStyle(fontSize: 12.5, color: colors.ink),
                ),
              ),
              const SizedBox(width: MarkoSpace.sm),
              TextButton.icon(
                onPressed: () => showHelpOverlay(context),
                icon: const HeroIcon(HeroIcons.bookOpen, size: 16),
                label: const Text('Інструкція'),
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                ),
              ),
            ],
          ),
        ),
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
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        step.title,
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: MarkoSpace.xs,
                        vertical: 1,
                      ),
                      decoration: BoxDecoration(
                        color: colors.surfaceMuted,
                        borderRadius: BorderRadius.circular(MarkoRadius.sm),
                        border: Border.all(color: colors.border),
                      ),
                      child: Text(
                        step.tag,
                        style: MarkoType.caption.copyWith(
                          fontSize: 10.5,
                          color: colors.faint,
                        ),
                      ),
                    ),
                  ],
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
