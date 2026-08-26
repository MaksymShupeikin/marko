import 'dart:ui' show PointerDeviceKind;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../products_api.dart';
import '../products_controller.dart';
import '../products_models.dart';

/// Підключені магазини воркспейсу; оновлюється після кожного імпорту.
final storesProvider = FutureProvider.autoDispose<List<StoreInfo>>(
  (ref) => ref.watch(productsApiProvider).listStores(),
);

/// Cards of the stores the catalog was imported from, above the catalog.
/// Tapping a card filters the catalog by that store; several can be on at once.
/// Uses a full-bleed horizontal scroll on mobile so cards slide edge-to-edge across the screen.
class StoresStrip extends ConsumerWidget {
  const StoresStrip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Імпорт завершився або приїхав файл — список і лічильники вже інші.
    ref.listen(catalogImportProvider, (previous, next) {
      final wasBusy = previous?.value?.hasActiveJob ?? false;
      final isBusy = next.value?.hasActiveJob ?? false;
      final newImport = previous?.value?.lastImport != next.value?.lastImport;
      if ((wasBusy && !isBusy) || newImport) ref.invalidate(storesProvider);
    });

    // Порожній магазин (невдалий імпорт чи все приховано) — не картка.
    final stores = (ref.watch(storesProvider).value ?? const <StoreInfo>[])
        .where((store) => store.productCount > 0)
        .toList(growable: false);
    if (stores.isEmpty) return const SizedBox.shrink();

    final selectedIds =
        ref.watch(
          productsControllerProvider.select((s) => s.value?.storeIds),
        ) ??
        const <String>{};

    final screenWidth = MediaQuery.sizeOf(context).width;
    final horizontalPadding = screenWidth > MarkoLayout.contentMaxWidth
        ? ((screenWidth - MarkoLayout.contentMaxWidth) / 2) + MarkoLayout.gutter
        : MarkoLayout.gutter;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        MarkoContentFrame(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text('Магазини', style: Theme.of(context).textTheme.headlineMedium),
              const SizedBox(width: MarkoSpace.sm),
              MarkoOemChip('${stores.length}'),
              const Spacer(),
              if (selectedIds.isNotEmpty)
                TextButton(
                  style: TextButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                  onPressed: () => ref
                      .read(productsControllerProvider.notifier)
                      .clearStoreFilter(),
                  child: const Text('Скинути'),
                ),
            ],
          ),
        ),
        const SizedBox(height: MarkoSpace.md),
        ScrollConfiguration(
          behavior: ScrollConfiguration.of(context).copyWith(
            dragDevices: {
              PointerDeviceKind.touch,
              PointerDeviceKind.mouse,
              PointerDeviceKind.trackpad,
              PointerDeviceKind.stylus,
            },
          ),
          child: SizedBox(
            height: 72,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              clipBehavior: Clip.none,
              physics: const BouncingScrollPhysics(
                parent: AlwaysScrollableScrollPhysics(),
              ),
              padding: EdgeInsets.symmetric(horizontal: horizontalPadding),
              itemCount: stores.length,
              separatorBuilder: (_, _) => const SizedBox(width: MarkoSpace.md),
              itemBuilder: (_, index) {
                final store = stores[index];
                return _StoreCard(
                  store: store,
                  selected: selectedIds.contains(store.id),
                  onTap: () => ref
                      .read(productsControllerProvider.notifier)
                      .toggleStoreFilter(store.id),
                );
              },
            ),
          ),
        ),
        const SizedBox(height: MarkoSpace.xl),
      ],
    );
  }
}

class _StoreCard extends StatelessWidget {
  const _StoreCard({
    required this.store,
    required this.selected,
    required this.onTap,
  });

  final StoreInfo store;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return MarkoPanel(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.md,
        vertical: MarkoSpace.sm,
      ),
      color: selected
          ? (isDark
              ? colors.brand.withValues(alpha: 0.15)
              : colors.brandSoft)
          : null,
      borderColor: selected ? colors.brand : null,
      onTap: onTap,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 40,
            height: 40,
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: colors.surfaceMuted,
              borderRadius: BorderRadius.circular(MarkoRadius.sm),
              border: Border.all(
                color: selected
                    ? colors.brand.withValues(alpha: 0.35)
                    : colors.border,
              ),
            ),
            child: store.logoUrl == null
                ? Center(
                    child: HeroIcon(
                      HeroIcons.buildingStorefront,
                      size: 18,
                      color: selected ? colors.brand : colors.faint,
                    ),
                  )
                : MarkoCachedImage(
                    imageUrl: store.logoUrl,
                    fit: BoxFit.contain,
                  ),
          ),
          const SizedBox(width: MarkoSpace.md),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 160),
                child: Text(
                  store.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: selected ? colors.brand : null,
                  ),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                store.productCountLabel,
                style: MarkoType.caption.copyWith(
                  color: selected ? colors.brand : colors.faint,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          if (selected) ...[
            const SizedBox(width: MarkoSpace.sm),
            HeroIcon(HeroIcons.checkCircle, size: 18, color: colors.brand),
          ],
        ],
      ),
    );
  }
}
