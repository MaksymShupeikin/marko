import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../products_models.dart';
import 'product_card.dart';

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

/// Cell sizing shared by the real grid and its loading skeleton.
SliverGridDelegate _gridDelegateFor(double maxWidth) {
  final columns = _columnsFor(maxWidth);
  final horizontal = columns == 1;
  return SliverGridDelegateWithFixedCrossAxisCount(
    crossAxisCount: columns,
    mainAxisSpacing: horizontal ? MarkoSpace.sm : _gridSpacing,
    crossAxisSpacing: _gridSpacing,
    // Square image plus a fixed text block: an aspect ratio would
    // squeeze the text and overflow at some column counts.
    mainAxisExtent: horizontal
        ? productRowHeight
        : _tileWidth(maxWidth, columns) + _cardTextHeight,
  );
}

class ProductGrid extends StatelessWidget {
  const ProductGrid({
    required this.products,
    required this.selectedId,
    required this.checkedIds,
    required this.onOpen,
    required this.onCheck,
    this.ghostCount = 0,
    super.key,
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
          gridDelegate: _gridDelegateFor(constraints.maxWidth),
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

class GridSkeletonSliver extends StatelessWidget {
  const GridSkeletonSliver({super.key});

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
              gridDelegate: _gridDelegateFor(constraints.maxWidth),
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
