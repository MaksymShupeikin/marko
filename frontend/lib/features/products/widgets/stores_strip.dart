import 'dart:ui' show PointerDeviceKind;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_cached_image.dart';
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
                Text('Файли', style: Theme.of(context).textTheme.headlineMedium),
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
    final confirmed = await _confirm(
      context,
      title: 'Видалити магазин «${store.name}»?',
      message:
          'Каталог магазину (${store.productCountLabel}) буде видалено. '
          'Сам магазин назавжди лишиться виключеним із цін конкурентів.',
      action: 'Видалити магазин',
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
    final confirmed = await _confirm(
      context,
      title: 'Прибрати файл магазину «${store.name}»?',
      message:
          'Товари з файлу (${store.fileProductCount}) буде прибрано з '
          'каталогу й пошуку конкурентів — файл перестане бути референсом. '
          'Товари, імпортовані з Prom, лишаться.',
      action: 'Прибрати файл',
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
      showMarkoToast(context, message: 'Товари з файлу «${store.name}» прибрано');
    }
    ref.invalidate(storesProvider);
    await ref.read(productsControllerProvider.notifier).refresh();
  }

  Future<bool> _confirm(
    BuildContext context, {
    required String title,
    required String message,
    required String action,
  }) async {
    final colors = MarkoTheme.of(context);
    return await showDialog<bool>(
          context: context,
          barrierDismissible: true,
          builder: (context) => AlertDialog(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(colors.panelRadius),
              side: BorderSide(color: colors.border),
            ),
            backgroundColor: colors.surface,
            surfaceTintColor: Colors.transparent,
            icon: Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: colors.negative.withValues(alpha: 0.10),
                shape: BoxShape.circle,
              ),
              alignment: Alignment.center,
              child: HeroIcon(
                HeroIcons.trash,
                color: colors.negative,
                size: 22,
              ),
            ),
            title: Text(
              title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w600,
                fontSize: 18,
              ),
            ),
            content: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 380),
              child: Text(
                message,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: colors.faint),
              ),
            ),
            actionsAlignment: MainAxisAlignment.center,
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: const Text('Скасувати'),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: colors.negative,
                  foregroundColor: Colors.white,
                ),
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(action),
              ),
            ],
          ),
        ) ??
        false;
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

/// One card of the strip: a store or an uploaded file. The trash icon lives
/// half-faded in the corner and lights up on hover — on touch screens, where
/// hover does not exist, the faded icon stays tappable as it is.
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

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final selected = widget.selected;

    return MouseRegion(
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
        onTap: widget.onTap,
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
            if (selected) ...[
              const SizedBox(width: MarkoSpace.sm),
              HeroIcon(HeroIcons.checkCircle, size: 18, color: colors.brand),
            ],
            const SizedBox(width: MarkoSpace.sm),
            AnimatedOpacity(
              // Без миші (телефон) ховера немає — лишаємо кнопку видимою.
              opacity: _hovered ? 1.0 : 0.35,
              duration: const Duration(milliseconds: 120),
              child: Tooltip(
                message: widget.deleteTooltip,
                child: InkWell(
                  customBorder: const CircleBorder(),
                  onTap: widget.onDelete,
                  child: Padding(
                    padding: const EdgeInsets.all(4),
                    child: HeroIcon(
                      HeroIcons.trash,
                      size: 16,
                      color: _hovered ? colors.negative : colors.faint,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
