import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/widgets/marko_button.dart';
import '../products_controller.dart';
import '../products_models.dart';
import 'product_card.dart' show formatPriceNumber;

/// A floating capsule reporting the running import: it hovers over the catalog
/// in the Stack, counts products as they land, and animates a glowing border beam.
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
              key: ValueKey(sync.syncRunId),
              job: import!.activeJob,
              status: sync.status,
              onDismiss: () => _dismiss(context, ref),
            ),
    );
  }

  /// Готовий чи впалий імпорт просто ховаємо; живий — зупиняємо після підтвердження.
  Future<void> _dismiss(BuildContext context, WidgetRef ref) async {
    final notifier = ref.read(catalogImportProvider.notifier);
    final job = ref.read(catalogImportProvider).value?.activeJob;
    if (job?.isFinished ?? false) {
      notifier.dismissSync();
      return;
    }
    if (await _confirmCancel(context)) await notifier.cancelSync();
  }

  Future<bool> _confirmCancel(BuildContext context) async {
    final colors = MarkoTheme.of(context);
    return await showDialog<bool>(
          context: context,
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
              child: const HeroIcon(
                HeroIcons.stopCircle,
                color: Colors.redAccent,
                size: 22,
              ),
            ),
            title: Text(
              'Зупинити синхронізацію?',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontSize: 18,
                  ),
            ),
            content: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 380),
              child: Text(
                'Завантаження каталогу зупиниться. '
                'Уже синхронізовані товари залишаться в каталозі.',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: MarkoTheme.of(context).muted),
              ),
            ),
            actionsPadding: const EdgeInsets.fromLTRB(
              MarkoSpace.lg,
              0,
              MarkoSpace.lg,
              MarkoSpace.lg,
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: const Text('Продовжити'),
              ),
              MarkoButton.danger(
                label: 'Зупинити',
                icon: HeroIcons.stopCircle,
                onPressed: () => Navigator.of(context).pop(true),
              ),
            ],
          ),
        ) ??
        false;
  }
}

class _Capsule extends StatefulWidget {
  const _Capsule({
    super.key,
    required this.job,
    required this.status,
    required this.onDismiss,
  });

  final SyncRun? job;
  final String status;
  final VoidCallback onDismiss;

  @override
  State<_Capsule> createState() => _CapsuleState();
}

class _CapsuleState extends State<_Capsule>
    with SingleTickerProviderStateMixin {
  late final AnimationController _beamController;

  @override
  void initState() {
    super.initState();
    _beamController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2200),
    )..repeat();
  }

  @override
  void didUpdateWidget(covariant _Capsule oldWidget) {
    super.didUpdateWidget(oldWidget);
    final currentStatus = widget.job?.status ?? widget.status;
    final isFinished = currentStatus == 'completed' ||
        currentStatus == 'failed' ||
        currentStatus == 'cancelled';
    if (isFinished && _beamController.isAnimating) {
      _beamController.stop();
    } else if (!isFinished && !_beamController.isAnimating) {
      _beamController.repeat();
    }
  }

  @override
  void dispose() {
    _beamController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final currentJob = widget.job;
    final currentStatus = currentJob?.status ?? widget.status;
    final failed = currentStatus == 'failed' || currentStatus == 'cancelled';
    final done = currentStatus == 'completed';
    final inProgress = !done && !failed;

    final accent = failed
        ? colors.negative
        : done
            ? colors.positive
            : colors.promAccent;

    final count = currentJob?.progressCurrent ?? 0;
    final progress = currentJob?.progress;
    final borderRadius = MarkoRadius.md;

    return Container(
      constraints: const BoxConstraints(maxWidth: 520),
      margin: const EdgeInsets.symmetric(horizontal: MarkoSpace.lg),
      child: Stack(
        children: [
          // 1. Background surface with blur
          Container(
            decoration: BoxDecoration(
              color: colors.surface.withValues(alpha: 0.94),
              borderRadius: BorderRadius.circular(borderRadius),
              boxShadow: [
                BoxShadow(
                  color: accent.withValues(alpha: inProgress ? 0.18 : 0.12),
                  blurRadius: inProgress ? 24 : 16,
                  spreadRadius: -4,
                  offset: const Offset(0, 6),
                ),
                ...MarkoShadow.overlay,
              ],
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(borderRadius),
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(8, 7, MarkoSpace.sm, 7),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _SyncBadge(
                        accent: accent,
                        icon: failed
                            ? HeroIcons.exclamationTriangle
                            : done
                                ? HeroIcons.check
                                : null,
                      ),
                      const SizedBox(width: MarkoSpace.sm),
                      Flexible(
                        child: Text(
                          currentStatus == 'cancelled'
                              ? 'Синхронізацію зупинено'
                              : failed
                                  ? 'Помилка синхронізації'
                                  : done
                                      ? 'Каталог оновлено'
                                      : 'Синхронізація',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w600,
                            color: colors.ink,
                            letterSpacing: -0.2,
                          ),
                        ),
                      ),
                      if (!failed) ...[
                        const SizedBox(width: MarkoSpace.sm),
                        _CountChip(count: count, accent: accent, done: done),
                      ],
                      if (inProgress && progress != null) ...[
                        const SizedBox(width: MarkoSpace.xs),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 6,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: colors.surfaceMuted,
                            borderRadius:
                                BorderRadius.circular(MarkoRadius.xs),
                          ),
                          child: Text(
                            '${(progress * 100).round()}%',
                            style: MarkoType.caption.copyWith(
                              color: colors.muted,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                      const SizedBox(width: MarkoSpace.xs),
                      _DismissButton(onPressed: widget.onDismiss),
                    ],
                  ),
                ),
              ),
            ),
          ),

          // 2. Animated border beam (spinning around container perimeter while in progress)
          Positioned.fill(
            child: IgnorePointer(
              child: AnimatedBuilder(
                animation: _beamController,
                builder: (context, _) {
                  return CustomPaint(
                    painter: _AnimatedBorderBeamPainter(
                      progress: _beamController.value,
                      accentColor: accent,
                      radius: borderRadius,
                      borderWidth: inProgress ? 1.8 : 1.0,
                      inProgress: inProgress,
                    ),
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Custom painter that creates a neon traveling beam running along the rounded border.
class _AnimatedBorderBeamPainter extends CustomPainter {
  _AnimatedBorderBeamPainter({
    required this.progress,
    required this.accentColor,
    required this.radius,
    required this.borderWidth,
    required this.inProgress,
  });

  final double progress;
  final Color accentColor;
  final double radius;
  final double borderWidth;
  final bool inProgress;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;

    final rect = Offset.zero & size;
    final rrect = RRect.fromRectAndRadius(
      rect.deflate(borderWidth / 2),
      Radius.circular(radius),
    );

    if (!inProgress) {
      // Solid settled border when finished/failed
      final solidPaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = borderWidth
        ..color = accentColor.withValues(alpha: 0.45);
      canvas.drawRRect(rrect, solidPaint);
      return;
    }

    // 1. Subtle background track border
    final basePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = borderWidth
      ..color = accentColor.withValues(alpha: 0.18);
    canvas.drawRRect(rrect, basePaint);

    // 2. Rotating beam sweep gradient around the border
    final startAngle = progress * 2 * math.pi;
    final sweepGradient = SweepGradient(
      center: Alignment.center,
      startAngle: 0.0,
      endAngle: math.pi * 2,
      transform: GradientRotation(startAngle),
      colors: [
        accentColor.withValues(alpha: 0.0),
        accentColor.withValues(alpha: 0.0),
        accentColor.withValues(alpha: 0.25),
        accentColor,
        accentColor.withValues(alpha: 0.0),
      ],
      stops: const [0.0, 0.52, 0.76, 0.96, 1.0],
    );

    final beamPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = borderWidth + 0.6
      ..shader = sweepGradient.createShader(rect);

    canvas.drawRRect(rrect, beamPaint);
  }

  @override
  bool shouldRepaint(covariant _AnimatedBorderBeamPainter oldDelegate) =>
      oldDelegate.progress != progress ||
      oldDelegate.accentColor != accentColor ||
      oldDelegate.inProgress != inProgress;
}

/// Dynamic sync badge: animated rotating icon while syncing, checkmark when done.
class _SyncBadge extends StatelessWidget {
  const _SyncBadge({
    required this.accent,
    required this.icon,
  });

  final Color accent;
  final HeroIcons? icon;

  @override
  Widget build(BuildContext context) {
    if (icon != null) {
      return Container(
        width: 28,
        height: 28,
        decoration: BoxDecoration(
          color: accent.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(MarkoRadius.sm),
          border: Border.all(color: accent.withValues(alpha: 0.28)),
        ),
        alignment: Alignment.center,
        child: HeroIcon(icon!, size: 16, color: accent),
      );
    }

    return Image.asset(
      'assets/logos/prom.webp',
      width: 28,
      height: 28,
      fit: BoxFit.contain,
      filterQuality: FilterQuality.high,
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
