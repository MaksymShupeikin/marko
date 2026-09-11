import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../../core/widgets/marko_loader.dart';
import '../../core/widgets/marko_toast.dart';
import 'file_download_stub.dart'
    if (dart.library.js_interop) 'file_download_web.dart';
import 'repricing_api.dart';
import 'repricing_controller.dart';
import 'repricing_models.dart';
import 'widgets/reprice_card.dart';

/// The repricing window: plan a run, watch it, read what it found.
///
/// Окремий маршрут, а не діалог: усередині історія прогонів, сотні карток
/// і вивантаження — у модальне вікно це не поміщається.
class RepricingPage extends ConsumerWidget {
  const RepricingPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final async = ref.watch(repricingControllerProvider);
    return Scaffold(
      backgroundColor: colors.canvas,
      appBar: AppBar(
        toolbarHeight: MarkoLayout.appBarHeight,
        leading: IconButton(
          icon: HeroIcon(HeroIcons.arrowLeft, size: 18, color: colors.ink),
          onPressed: () => context.go('/'),
        ),
        title: const Text('Переоцінка'),
        actions: [
          if (async.hasValue)
            TextButton.icon(
              onPressed: () => ref
                  .read(repricingControllerProvider.notifier)
                  .toggleHistory(),
              icon: HeroIcon(HeroIcons.clock, size: 15, color: colors.brand),
              label: Text(
                async.value!.showHistory ? 'Новий прогін' : 'Історія',
                style: TextStyle(color: colors.brand),
              ),
            ),
          const SizedBox(width: MarkoSpace.md),
        ],
      ),
      body: async.when(
        loading: () => const Center(child: MarkoLoader()),
        error: (error, _) => Center(
          child: MarkoInlineMessage(
            message: '$error',
            tone: MarkoMessageTone.error,
          ),
        ),
        data: (state) => _Body(state: state),
      ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(vertical: MarkoSpace.xxl),
      child: MarkoContentFrame(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (state.error != null) ...[
              MarkoInlineMessage(
                message: state.error!,
                tone: MarkoMessageTone.error,
              ),
              const SizedBox(height: MarkoSpace.lg),
            ],
            if (state.showHistory)
              _History(state: state)
            else ...[
              _StartPanel(state: state),
              const SizedBox(height: MarkoSpace.xxl),
              _Results(state: state),
            ],
          ],
        ),
      ),
    );
  }
}

class _StartPanel extends ConsumerWidget {
  const _StartPanel({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final controller = ref.read(repricingControllerProvider.notifier);
    final run = state.run;
    return MarkoPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const MarkoSectionLabel('Новий прогін'),
          const SizedBox(height: MarkoSpace.lg),
          if (state.preview?.signatureChanged ?? false) ...[
            const MarkoInlineMessage(
              message:
                  'Склад каталогу змінився з часу останнього прогону. '
                  'Пораховані раніше товари, яких уже немає, у покриття '
                  'не рахуються.',
              tone: MarkoMessageTone.warning,
            ),
            const SizedBox(height: MarkoSpace.lg),
          ],
          _ScopeChoice(state: state),
          const SizedBox(height: MarkoSpace.lg),
          _ModeChoice(state: state),
          if (state.scope == RepriceScope.partial) ...[
            const SizedBox(height: MarkoSpace.lg),
            _CountSlider(state: state),
          ],
          const SizedBox(height: MarkoSpace.lg),
          _PolicyChoice(state: state),
          const SizedBox(height: MarkoSpace.lg),
          _Estimate(state: state),
          const SizedBox(height: MarkoSpace.lg),
          if (run != null && run.isRunning)
            _Progress(run: run)
          else
            Align(
              alignment: Alignment.centerRight,
              child: MarkoButton(
                label: 'Запустити',
                icon: HeroIcons.play,
                loading: state.busy,
                onPressed: state.canStart && !state.exceedsChecks
                    ? controller.start
                    : null,
              ),
            ),
          if (state.exceedsChecks) ...[
            const SizedBox(height: MarkoSpace.md),
            Text(
              'Ліміту перевірок не вистачить на ${state.plannedCount} товарів. '
              'Зменште кількість або відкрийте повний доступ.',
              style: MarkoType.caption.copyWith(color: colors.negative),
            ),
          ],
        ],
      ),
    );
  }
}

class _ScopeChoice extends ConsumerWidget {
  const _ScopeChoice({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(repricingControllerProvider.notifier);
    return _Segmented<RepriceScope>(
      label: 'Що переоцінюємо',
      values: RepriceScope.values,
      selected: state.scope,
      labelOf: (scope) => scope.label,
      onChanged: controller.chooseScope,
    );
  }
}

class _ModeChoice extends ConsumerWidget {
  const _ModeChoice({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final controller = ref.read(repricingControllerProvider.notifier);
    final remaining = state.preview?.remaining ?? 0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Segmented<RepriceMode>(
          label: 'З чого починаємо',
          values: RepriceMode.values,
          selected: state.mode,
          labelOf: (mode) => mode.label,
          onChanged: (mode) => controller.chooseMode(mode),
        ),
        if (state.mode == RepriceMode.resume) ...[
          const SizedBox(height: MarkoSpace.sm),
          Text(
            'Ще не перевірено: $remaining',
            style: MarkoType.caption.copyWith(color: colors.muted),
          ),
        ],
      ],
    );
  }
}

class _CountSlider extends ConsumerWidget {
  const _CountSlider({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final controller = ref.read(repricingControllerProvider.notifier);
    final maxCount = state.maxCount;
    final value = state.count.clamp(1, maxCount).toDouble();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Скільки товарів',
                style: Theme.of(context).textTheme.labelLarge,
              ),
            ),
            Text(
              '${value.round()} з $maxCount',
              style: MarkoType.price.copyWith(color: colors.ink),
            ),
          ],
        ),
        Slider(
          value: value,
          min: 1,
          max: maxCount.toDouble(),
          // Понад тисячу поділок повзунок не відрізнить — і не треба.
          divisions: maxCount > 1
              ? (maxCount > 1000 ? 1000 : maxCount - 1)
              : null,
          label: '${value.round()}',
          onChanged: maxCount > 1
              ? (next) => controller.chooseCount(next.round())
              : null,
        ),
      ],
    );
  }
}

class _PolicyChoice extends ConsumerWidget {
  const _PolicyChoice({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final controller = ref.read(repricingControllerProvider.notifier);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Segmented<RepricePolicy>(
          label: 'Політика ціни',
          values: RepricePolicy.values,
          selected: state.policy,
          labelOf: (policy) => policy.label,
          onChanged: controller.choosePolicy,
        ),
        const SizedBox(height: MarkoSpace.sm),
        Text(
          state.policy.hint,
          style: MarkoType.caption.copyWith(color: colors.muted),
        ),
      ],
    );
  }
}

class _Estimate extends StatelessWidget {
  const _Estimate({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final left = state.preview?.checksLeft;
    final limit = left == null ? 'ліміту немає' : 'лишилось $left';
    return Container(
      padding: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(MarkoRadius.md),
      ),
      child: Row(
        children: [
          HeroIcon(HeroIcons.calculator, size: 16, color: colors.muted),
          const SizedBox(width: MarkoSpace.sm),
          Expanded(
            child: Text(
              // Свідомо найгірший випадок: товари зі свіжим звітом у кеші
              // безкоштовні, але дізнатись про це до запуску неможливо,
              // а обіцяти дешевше, ніж вийде, — гірше, ніж навпаки.
              'До ${state.plannedCount} перевірок ціни — $limit. '
              'Товари зі свіжим звітом у кеші не витрачають ліміт.',
              style: MarkoType.caption.copyWith(color: colors.muted),
            ),
          ),
        ],
      ),
    );
  }
}

class _Progress extends StatelessWidget {
  const _Progress({required this.run});

  final RepriceRun run;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const MarkoLoader(size: 15),
            const SizedBox(width: MarkoSpace.sm),
            Expanded(
              child: Text(
                'Переоцінка ${run.statusLabel}: '
                '${run.progressCurrent} з ${run.progressTotal ?? 0}',
                style: MarkoType.caption.copyWith(color: colors.muted),
              ),
            ),
          ],
        ),
        const SizedBox(height: MarkoSpace.sm),
        ClipRRect(
          borderRadius: BorderRadius.circular(MarkoRadius.xs),
          child: LinearProgressIndicator(
            value: run.progress,
            minHeight: 4,
            backgroundColor: colors.border,
            valueColor: AlwaysStoppedAnimation(colors.brand),
          ),
        ),
      ],
    );
  }
}

class _Results extends ConsumerWidget {
  const _Results({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final run = state.run;
    if (run == null) {
      return const MarkoEmptyState(
        icon: HeroIcons.calculator,
        title: 'Прогонів ще не було',
        description:
            'Виберіть охоплення й запустіть переоцінку — результат з’явиться тут.',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Прогін ${run.createdAtLabel}',
                style: Theme.of(
                  context,
                ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
              ),
            ),
            _ExportButton(run: run),
          ],
        ),
        const SizedBox(height: MarkoSpace.xs),
        Text(
          '${run.scopeLabel} · ${run.modeLabel} · каталог '
          '${run.catalog.shortSignature} (${run.catalog.itemCount} товарів)'
          '${run.catalogIsCurrent ? '' : ' · каталог відтоді змінився'}',
          style: MarkoType.caption.copyWith(color: colors.muted),
        ),
        if (run.error != null) ...[
          const SizedBox(height: MarkoSpace.md),
          MarkoInlineMessage(
            message: run.error!,
            tone: MarkoMessageTone.warning,
          ),
        ],
        const SizedBox(height: MarkoSpace.lg),
        _OutcomeFilter(state: state),
        const SizedBox(height: MarkoSpace.lg),
        if (state.items.items.isEmpty)
          MarkoEmptyState(
            icon: HeroIcons.inbox,
            title: 'Порожньо',
            description: run.isRunning
                ? 'Прогін ще виконується — рядки з’являться, коли він завершиться.'
                : 'За цим фільтром рядків немає.',
          )
        else
          _Cards(state: state),
      ],
    );
  }
}

class _OutcomeFilter extends ConsumerWidget {
  const _OutcomeFilter({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(repricingControllerProvider.notifier);
    final run = state.run;
    final counts = <RepriceOutcome?, int>{
      null: run?.total ?? 0,
      RepriceOutcome.changed: run?.changedCount ?? 0,
      RepriceOutcome.unchanged: run?.unchangedCount ?? 0,
      RepriceOutcome.noRecommendation: run?.skippedCount ?? 0,
    };
    return Wrap(
      spacing: MarkoSpace.sm,
      runSpacing: MarkoSpace.sm,
      children: [
        for (final entry in counts.entries)
          ChoiceChip(
            selected: state.filter == entry.key,
            onSelected: (_) => controller.filterBy(entry.key),
            label: Text(
              '${entry.key?.label ?? 'Усі'} · ${entry.value}',
              style: const TextStyle(fontSize: 12.5),
            ),
          ),
      ],
    );
  }
}

class _Cards extends ConsumerWidget {
  const _Cards({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(repricingControllerProvider.notifier);
    return Column(
      children: [
        for (final item in state.items.items) ...[
          RepriceCard(
            item: item,
            onDismiss: () =>
                controller.dismiss(item.listingId, dismissed: !item.dismissed),
            onOpenInCatalog: () => context.go('/'),
          ),
          const SizedBox(height: MarkoSpace.md),
        ],
        if (state.items.total > state.items.items.length)
          Text(
            'Показано ${state.items.items.length} з ${state.items.total}',
            style: MarkoType.caption.copyWith(
              color: MarkoTheme.of(context).muted,
            ),
          ),
      ],
    );
  }
}

class _ExportButton extends ConsumerStatefulWidget {
  const _ExportButton({required this.run});

  final RepriceRun run;

  @override
  ConsumerState<_ExportButton> createState() => _ExportButtonState();
}

class _ExportButtonState extends ConsumerState<_ExportButton> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    return MarkoButton.secondary(
      label: 'Вивантажити в Excel',
      icon: HeroIcons.arrowDownTray,
      loading: _busy,
      onPressed: widget.run.isRunning || _busy ? null : _download,
    );
  }

  Future<void> _download() async {
    setState(() => _busy = true);
    try {
      final bytes = await ref
          .read(repricingControllerProvider.notifier)
          .exportBytes();
      final name =
          'marko-reprice-'
          '${widget.run.createdAt.toIso8601String().substring(0, 10)}.xlsx';
      final saved = saveBytes(bytes, name, xlsxMimeType);
      if (!mounted) return;
      if (!saved) {
        showMarkoToast(
          context,
          message: 'Вивантаження доступне у браузерній версії Marko.',
          tone: MarkoMessageTone.warning,
        );
      }
    } catch (error) {
      if (mounted) {
        showMarkoToast(
          context,
          message: '\$error',
          tone: MarkoMessageTone.error,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _History extends ConsumerWidget {
  const _History({required this.state});

  final RepricingState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = MarkoTheme.of(context);
    final controller = ref.read(repricingControllerProvider.notifier);
    if (state.history.isEmpty) {
      return const MarkoEmptyState(
        icon: HeroIcons.clock,
        title: 'Історія порожня',
        description: 'Тут з’являться минулі прогони — з датою і каталогом.',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const MarkoSectionLabel('Історія прогонів'),
        const SizedBox(height: MarkoSpace.lg),
        for (final run in state.history) ...[
          MarkoPanel(
            padding: const EdgeInsets.all(MarkoSpace.lg),
            onTap: () => controller.openRun(run.id),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        run.createdAtLabel,
                        style: MarkoType.price.copyWith(color: colors.ink),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${run.scopeLabel} · ${run.modeLabel} · '
                        'каталог ${run.catalog.shortSignature}'
                        '${run.catalogIsCurrent ? '' : ' (інший)'}',
                        style: MarkoType.caption.copyWith(color: colors.muted),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'змінено ${run.changedCount} · без змін '
                        '${run.unchangedCount} · не пораховано '
                        '${run.skippedCount}',
                        style: MarkoType.caption.copyWith(color: colors.muted),
                      ),
                    ],
                  ),
                ),
                MarkoStatusPill(
                  label: run.statusLabel,
                  tone: run.status == 'completed'
                      ? colors.positive
                      : colors.muted,
                ),
              ],
            ),
          ),
          const SizedBox(height: MarkoSpace.md),
        ],
      ],
    );
  }
}

class _Segmented<T> extends StatelessWidget {
  const _Segmented({
    required this.label,
    required this.values,
    required this.selected,
    required this.labelOf,
    required this.onChanged,
  });

  final String label;
  final List<T> values;
  final T selected;
  final String Function(T) labelOf;
  final void Function(T) onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: MarkoSpace.sm),
        Wrap(
          spacing: MarkoSpace.sm,
          runSpacing: MarkoSpace.sm,
          children: [
            for (final value in values)
              ChoiceChip(
                selected: value == selected,
                onSelected: (_) => onChanged(value),
                label: Text(
                  labelOf(value),
                  style: const TextStyle(fontSize: 12.5),
                ),
              ),
          ],
        ),
      ],
    );
  }
}
