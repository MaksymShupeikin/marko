import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../products_controller.dart';
import '../products_models.dart';
import 'product_card.dart' show formatPriceNumber;

/// A floating capsule reporting the running import: it hovers over the catalog
/// instead of pushing it down, counts products as they land, and dissolves a
/// few seconds after the job finishes.
class DynamicSyncIsland extends ConsumerWidget {
  const DynamicSyncIsland({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final import = ref.watch(catalogImportProvider).value;
    final sync = import?.activeSync;

    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 280),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      transitionBuilder: (child, animation) => FadeTransition(
        opacity: animation,
        child: SlideTransition(
          position: Tween(
            begin: const Offset(0, -0.55),
            end: Offset.zero,
          ).animate(animation),
          child: ScaleTransition(
            scale: Tween(begin: 0.92, end: 1.0).animate(animation),
            child: child,
          ),
        ),
      ),
      child: sync == null
          ? const SizedBox.shrink()
          : _Capsule(
              job: import!.activeJob,
              status: sync.status,
              onDismiss: ref.read(catalogImportProvider.notifier).dismissSync,
            ),
    );
  }
}

class _Capsule extends StatefulWidget {
  const _Capsule({
    required this.job,
    required this.status,
    required this.onDismiss,
  });

  final SyncRun? job;

  /// The status the sync was queued with, until the first poll answers.
  final String status;
  final VoidCallback onDismiss;

  @override
  State<_Capsule> createState() => _CapsuleState();
}

class _CapsuleState extends State<_Capsule> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat();

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final job = widget.job;
    final status = job?.status ?? widget.status;
    final failed = status == 'failed';
    final done = status == 'completed';
    final accent = failed
        ? colors.negative
        : done
        ? colors.positive
        : colors.promAccent;
    final count = job?.progressCurrent ?? 0;
    final progress = job?.progress;

    return Container(
      constraints: const BoxConstraints(maxWidth: 520),
      margin: const EdgeInsets.symmetric(horizontal: MarkoSpace.lg),
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: accent.withValues(alpha: 0.45)),
        boxShadow: [
          BoxShadow(
            color: accent.withValues(alpha: 0.18),
            blurRadius: 24,
            spreadRadius: -6,
            offset: const Offset(0, 8),
          ),
          ...MarkoShadow.overlay,
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(6, 6, MarkoSpace.sm, 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _PulseBadge(
                  pulse: _pulse,
                  accent: accent,
                  active: !done && !failed,
                  icon: failed
                      ? HeroIcons.exclamationTriangle
                      : done
                      ? HeroIcons.check
                      : null,
                ),
                const SizedBox(width: MarkoSpace.sm),
                Flexible(
                  child: Text(
                    failed
                        ? 'Імпорт не вдався'
                        : done
                        ? 'Каталог оновлено'
                        : 'Синхронізація Prom.ua',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: colors.ink,
                    ),
                  ),
                ),
                if (!failed) ...[
                  const SizedBox(width: MarkoSpace.sm),
                  _CountChip(count: count, accent: accent, done: done),
                ],
                if (!done && !failed) ...[
                  const SizedBox(width: MarkoSpace.sm),
                  _MiniProgress(value: progress, accent: accent),
                ],
                const SizedBox(width: MarkoSpace.xs),
                _DismissButton(onPressed: widget.onDismiss),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The source mark with a radar ring around it while the job runs.
class _PulseBadge extends StatelessWidget {
  const _PulseBadge({
    required this.pulse,
    required this.accent,
    required this.active,
    required this.icon,
  });

  final Animation<double> pulse;
  final Color accent;
  final bool active;

  /// Replaces the source logo once the job has an outcome.
  final HeroIcons? icon;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 30,
      height: 30,
      child: Stack(
        alignment: Alignment.center,
        children: [
          if (active)
            AnimatedBuilder(
              animation: pulse,
              builder: (context, _) => Transform.scale(
                scale: 1 + pulse.value * 0.55,
                child: Container(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: accent.withValues(alpha: 0.5 * (1 - pulse.value)),
                      width: 1.5,
                    ),
                  ),
                ),
              ),
            ),
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.14),
              shape: BoxShape.circle,
              border: Border.all(color: accent.withValues(alpha: 0.3)),
            ),
            alignment: Alignment.center,
            child: icon == null
                ? Image.asset(
                    'assets/logos/prom.png',
                    width: 14,
                    color: accent,
                    colorBlendMode: BlendMode.srcIn,
                  )
                : HeroIcon(icon!, size: 15, color: accent),
          ),
        ],
      ),
    );
  }
}

/// The live odometer: the number runs up to each new count instead of jumping.
class _CountChip extends StatelessWidget {
  const _CountChip({
    required this.count,
    required this.accent,
    required this.done,
  });

  final int count;
  final Color accent;
  final bool done;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: MarkoSpace.sm, vertical: 3),
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(MarkoRadius.sm),
        border: Border.all(color: accent.withValues(alpha: 0.24)),
      ),
      child: TweenAnimationBuilder<double>(
        tween: Tween(end: count.toDouble()),
        duration: const Duration(milliseconds: 650),
        curve: Curves.easeOutCubic,
        builder: (context, value, _) => Text(
          '${done ? '+' : ''}${formatPriceNumber(value.roundToDouble())} товарів',
          maxLines: 1,
          style: MarkoType.price.copyWith(
            fontSize: 12,
            color: colors.ink,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

/// A short bar plus a percentage; indeterminate while the total is unknown.
class _MiniProgress extends StatelessWidget {
  const _MiniProgress({required this.value, required this.accent});

  final double? value;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: SizedBox(
            width: 64,
            height: 4,
            child: TweenAnimationBuilder<double>(
              tween: Tween(end: value ?? 0),
              duration: const Duration(milliseconds: 650),
              curve: Curves.easeOutCubic,
              builder: (context, animated, _) => LinearProgressIndicator(
                value: value == null ? null : animated,
                color: accent,
                backgroundColor: colors.surfaceMuted,
              ),
            ),
          ),
        ),
        if (value != null) ...[
          const SizedBox(width: 6),
          Text(
            '${(value! * 100).round()}%',
            style: MarkoType.caption.copyWith(color: colors.muted, fontSize: 11),
          ),
        ],
      ],
    );
  }
}

class _DismissButton extends StatelessWidget {
  const _DismissButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return IconButton(
      tooltip: 'Сховати',
      onPressed: onPressed,
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints.tightFor(width: 26, height: 26),
      icon: HeroIcon(HeroIcons.xMark, size: 15, color: colors.faint),
    );
  }
}
