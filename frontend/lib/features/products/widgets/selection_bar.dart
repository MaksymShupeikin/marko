import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_loader.dart';
import '../../../core/widgets/marko_toast.dart';
import '../products_controller.dart';
import '../products_models.dart';
import 'product_management_dialogs.dart';

/// Actions applied to every ticked card at once; shown only while something
/// is ticked, so the catalog looks unchanged the rest of the time.
class SelectionBar extends ConsumerStatefulWidget {
  const SelectionBar({
    required this.count,
    required this.total,
    required this.allMatching,
    required this.job,
    super.key,
  });

  final int count;

  /// Everything the current filter matches, loaded or not.
  final int total;

  /// The selection is the whole filtered catalog, not the ticked cards.
  final bool allMatching;

  /// A running catalog-wide refresh, if any.
  final SyncRun? job;

  @override
  ConsumerState<SelectionBar> createState() => _SelectionBarState();
}

class _SelectionBarState extends ConsumerState<SelectionBar> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    // На вузькому екрані підписи кнопок не влазять у рядок — лишаються іконки.
    final compact = MarkoLayout.compactOf(context);
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

  /// Блокує плашку на час дії та показує тост, якщо дія впала.
  Future<void> _run(String errorTitle, Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } catch (error) {
      if (mounted) {
        showMarkoToast(
          context,
          title: errorTitle,
          message: '$error',
          tone: MarkoMessageTone.error,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Скільки вдалося з того, що просили: успіх або попередження.
  void _reportOutcome(String verb, int total, int failed) {
    if (!mounted) return;
    showMarkoToast(
      context,
      message: failed == 0
          ? '$verb товарів: $total'
          : '$verb ${total - failed} з $total, не вдалося: $failed',
      tone: failed == 0 ? MarkoMessageTone.success : MarkoMessageTone.warning,
    );
  }

  Future<void> _refresh() {
    final total = widget.count;
    final controller = ref.read(productsControllerProvider.notifier);
    return _run('Не вдалося оновити', () async {
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
      _reportOutcome('Оновлено', total, await controller.refreshSelected());
    });
  }

  Future<void> _delete() async {
    final total = widget.count;
    if (!await confirmBulkProductDeletion(context, count: total)) return;
    final controller = ref.read(productsControllerProvider.notifier);
    await _run('Не вдалося видалити', () async {
      if (widget.allMatching) {
        final deleted = await controller.deleteAllMatching();
        if (!mounted) return;
        showMarkoToast(context, message: 'Видалено товарів: $deleted');
        return;
      }
      _reportOutcome('Видалено', total, await controller.deleteSelected());
    });
  }
}
