import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../products_controller.dart';
import '../products_models.dart';

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

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final min = ref.watch(catalogPriceMinFieldProvider);
    final max = ref.watch(catalogPriceMaxFieldProvider);

    void emit() => onChanged(parsePrice(min.text), parsePrice(max.text));

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
    final baseStyle = MarkoLayout.fieldTextStyleOf(context);

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
    final textStyle = MarkoLayout.fieldTextStyleOf(context);

    // Поверхня меню і ховер пунктів приходять із menuTheme/menuButtonTheme.
    return MenuAnchor(
      controller: _menuController,
      alignmentOffset: const Offset(0, 4),
      menuChildren: [
        for (final option in ProductSort.values)
          MenuItemButton(
            onPressed: () => widget.onChanged(option),
            style: const ButtonStyle(
              minimumSize: WidgetStatePropertyAll(Size(190, 36)),
              padding: WidgetStatePropertyAll(
                EdgeInsets.symmetric(
                  horizontal: MarkoSpace.md,
                  vertical: MarkoSpace.xs,
                ),
              ),
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
