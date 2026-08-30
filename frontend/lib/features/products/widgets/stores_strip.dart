import 'dart:ui' show PointerDeviceKind;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
import '../../../core/widgets/marko_confirmation_dialog.dart';
import '../../../core/widgets/marko_toast.dart';
import '../products_api.dart';
import '../products_controller.dart';
import '../products_models.dart';

/// Підключені магазини воркспейсу; оновлюється після кожного імпорту.
final storesProvider = FutureProvider.autoDispose<List<StoreInfo>>(
  (ref) => ref.watch(productsApiProvider).listStores(),
);

/// Cards of the stores the catalog was imported from, above the catalog.
/// Tapping a card filters the catalog by that store; several can be on at once.
/// Above them — one card per uploaded XLSX file (they are recognised by the
/// seller-subdomain links their rows carry). Both kinds grow a trash icon on
/// hover: a store deletes with its catalog, a file stops being a search
/// reference — its rows leave the catalog and the competitor lookups.
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

    final fileStores = stores
        .where((store) => store.fileProductCount > 0)
        .toList(growable: false);

    final selectedIds =
        ref.watch(
          productsControllerProvider.select((s) => s.value?.storeIds),
        ) ??
        const <String>{};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (fileStores.isNotEmpty) ...[
          MarkoContentFrame(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Text(
                  'Файли',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(width: MarkoSpace.sm),
                MarkoOemChip('${fileStores.length}'),
              ],
            ),
          ),
          const SizedBox(height: MarkoSpace.md),
          _CardsRow(
            itemCount: fileStores.length,
            itemBuilder: (_, index) {
              final store = fileStores[index];
              return _StripCard(
                title: store.name,
                caption: '${store.fileProductCount} товарів з файлу',
                icon: HeroIcons.documentText,
                selected: false,
                deleteTooltip: 'Прибрати товари з файлу',
                onDelete: () => _deleteFile(context, ref, store),
              );
            },
          ),
          const SizedBox(height: MarkoSpace.xl),
        ],
        MarkoContentFrame(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text(
                'Магазини',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
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
        _CardsRow(
          itemCount: stores.length,
          itemBuilder: (_, index) {
            final store = stores[index];
            return _StripCard(
              title: store.name,
              caption: store.productCountLabel,
              logoUrl: store.logoUrl,
              selected: selectedIds.contains(store.id),
              deleteTooltip: 'Видалити магазин',
              onTap: () => ref
                  .read(productsControllerProvider.notifier)
                  .toggleStoreFilter(store.id),
              onDelete: () => _deleteStore(context, ref, store),
            );
          },
        ),
        const SizedBox(height: MarkoSpace.xl),
      ],
    );
  }

  Future<void> _deleteStore(
    BuildContext context,
    WidgetRef ref,
    StoreInfo store,
  ) async {
    final confirmed = await confirmMarkoAction(
      context,
      title: 'Видалити магазин?',
      subject: store.name,
      subjectDetails: store.productCountLabel,
      description:
          'Каталог магазину буде видалено. Магазин назавжди лишиться виключеним із цін конкурентів.',
      confirmLabel: 'Видалити',
      subjectIcon: HeroIcons.buildingStorefront,
    );
    if (!confirmed || !context.mounted) return;
    try {
      await ref.read(productsApiProvider).deleteStore(store.id);
    } catch (error) {
      if (context.mounted) {
        showMarkoToast(
          context,
          message: 'Не вдалося видалити магазин: $error',
          tone: MarkoMessageTone.error,
        );
      }
      return;
    }
    if (context.mounted) {
      showMarkoToast(context, message: 'Магазин «${store.name}» видалено');
    }
    ref.read(productsControllerProvider.notifier).clearStoreFilter();
    ref.invalidate(storesProvider);
    await ref.read(productsControllerProvider.notifier).refresh();
  }

  Future<void> _deleteFile(
    BuildContext context,
    WidgetRef ref,
    StoreInfo store,
  ) async {
    final confirmed = await confirmMarkoAction(
      context,
      title: 'Прибрати товари з файлу?',
      subject: store.name,
      subjectDetails: '${store.fileProductCount} товарів з файлу',
      description:
          'Товари з файлу буде прибрано з каталогу й пошуку конкурентів. '
          'Файл перестане бути референсом. '
          'Товари, імпортовані з Prom, лишаться.',
      confirmLabel: 'Прибрати',
      subjectIcon: HeroIcons.documentText,
    );
    if (!confirmed || !context.mounted) return;
    try {
      await ref.read(productsApiProvider).deleteStoreFileProducts(store.id);
    } catch (error) {
      if (context.mounted) {
        showMarkoToast(
          context,
          message: 'Не вдалося прибрати файл: $error',
          tone: MarkoMessageTone.error,
        );
      }
      return;
    }
    if (context.mounted) {
      showMarkoToast(
        context,
        message: 'Товари з файлу «${store.name}» прибрано',
      );
    }
    ref.invalidate(storesProvider);
    await ref.read(productsControllerProvider.notifier).refresh();
  }
}

/// The shared horizontal scroller for card rows.
class _CardsRow extends StatelessWidget {
  const _CardsRow({required this.itemCount, required this.itemBuilder});

  final int itemCount;
  final NullableIndexedWidgetBuilder itemBuilder;

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.sizeOf(context).width;
    final horizontalPadding = screenWidth > MarkoLayout.contentMaxWidth
        ? ((screenWidth - MarkoLayout.contentMaxWidth) / 2) + MarkoLayout.gutter
        : MarkoLayout.gutter;

    return ScrollConfiguration(
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
          itemCount: itemCount,
          separatorBuilder: (_, _) => const SizedBox(width: MarkoSpace.md),
          itemBuilder: itemBuilder,
        ),
      ),
    );
  }
}

/// One card of the strip: store actions appear on hover or keyboard focus.
/// On touch, selecting the card reveals the same actions without a custom icon.
class _StripCard extends StatefulWidget {
  const _StripCard({
    required this.title,
    required this.caption,
    required this.selected,
    required this.deleteTooltip,
    required this.onDelete,
    this.icon,
    this.logoUrl,
    this.onTap,
  });

  final String title;
  final String caption;
  final bool selected;
  final String deleteTooltip;
  final VoidCallback onDelete;
  final HeroIcons? icon;
  final String? logoUrl;
  final VoidCallback? onTap;

  @override
  State<_StripCard> createState() => _StripCardState();
}

class _StripCardState extends State<_StripCard> {
  bool _hovered = false;
  bool _focused = false;
  bool _revealed = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final selected = widget.selected;
    final showActions = _hovered || _focused || _revealed;

    return Focus(
      onFocusChange: (value) => setState(() => _focused = value),
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: MarkoPanel(
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
          onTap: () {
            if (widget.onTap != null) {
              widget.onTap!();
              // Touch screens have no hover. The selected card still reveals
              // its actions after a tap; desktop keeps them hover-only.
              if (!_hovered) setState(() => _revealed = true);
              return;
            }
            setState(() => _revealed = !_revealed);
          },
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
                child: widget.logoUrl == null
                    ? Center(
                        child: HeroIcon(
                          widget.icon ?? HeroIcons.buildingStorefront,
                          size: 18,
                          color: selected ? colors.brand : colors.faint,
                        ),
                      )
                    : MarkoCachedImage(
                        imageUrl: widget.logoUrl,
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
                      widget.title,
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
                    widget.caption,
                    style: MarkoType.caption.copyWith(
                      color: selected ? colors.brand : colors.faint,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
              ClipRect(
                child: AnimatedSize(
                  duration: const Duration(milliseconds: 180),
                  curve: Curves.easeOutCubic,
                  alignment: Alignment.centerLeft,
                  child: showActions
                      ? Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const SizedBox(width: MarkoSpace.sm),
                            if (widget.onTap != null) ...[
                              IconButton(
                                tooltip: selected
                                    ? 'Зняти вибір'
                                    : 'Обрати магазин',
                                icon: HeroIcon(
                                  selected
                                      ? HeroIcons.check
                                      : HeroIcons.checkCircle,
                                  size: 18,
                                  color: selected ? colors.brand : null,
                                ),
                                onPressed: widget.onTap,
                              ),
                              const SizedBox(width: MarkoSpace.xs),
                            ],
                            IconButton(
                              tooltip: widget.deleteTooltip,
                              icon: HeroIcon(
                                HeroIcons.trash,
                                size: 18,
                                color: colors.negative,
                              ),
                              onPressed: widget.onDelete,
                            ),
                          ],
                        )
                      : const SizedBox.shrink(),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
