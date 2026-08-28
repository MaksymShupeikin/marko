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

/// Черга імпортів над каталогом: перший магазин рахує товари під анімованим
/// променем, решта чекає компактними рядками під ним. Коли черга довша за
/// два рядки, хвіст згортається — щоб не затуляти каталог.
class DynamicSyncIsland extends ConsumerStatefulWidget {
  const DynamicSyncIsland({super.key});

  @override
  ConsumerState<DynamicSyncIsland> createState() => _DynamicSyncIslandState();
}

class _DynamicSyncIslandState extends ConsumerState<DynamicSyncIsland> {
  /// Скільки рядків видно згорнутою: активний плюс один наступний.
  static const _collapsedRows = 2;
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final import = ref.watch(catalogImportProvider).value;
    final runs = import?.visibleRuns ?? const <ActiveSyncRun>[];
    final hidden = runs.length - _collapsedRows;
    final collapsed = !_expanded && hidden > 0;
    final shown = collapsed ? runs.take(_collapsedRows).toList() : runs;

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
      child: runs.isEmpty
          ? const SizedBox.shrink()
          : AnimatedSize(
              key: ValueKey(runs.first.syncRunId),
              duration: const Duration(milliseconds: 180),
              curve: Curves.easeOutCubic,
              alignment: Alignment.topCenter,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final (index, run) in shown.indexed)
                    Padding(
                      padding: EdgeInsets.only(top: index == 0 ? 0 : MarkoSpace.xs),
                      child: index == 0
                          ? _Capsule(
                              key: ValueKey(run.syncRunId),
                              job: run.run,
                              status: run.run.status,
                              storeName: run.storeName,
                              storeLogoUrl: run.storeLogoUrl,
                              onDismiss: () => _dismiss(context, run),
                            )
                          : _QueuedRow(
                              key: ValueKey(run.syncRunId),
                              run: run,
                              // Хвіст згорнутої черги тьмяніє й тоншає:
                              // видно, що там ще щось є, але воно не заважає.
                              depth: collapsed ? index : 0,
                              onCancel: () => _dismiss(context, run),
                            ),
                    ),
                  if (hidden > 0)
                    Padding(
                      padding: const EdgeInsets.only(top: MarkoSpace.xs),
                      child: _QueueToggle(
                        hidden: hidden,
                        expanded: _expanded,
                        onPressed: () => setState(() => _expanded = !_expanded),
                      ),
                    ),
                ],
              ),
            ),
    );
  }

  /// Готовий чи впалий імпорт просто ховаємо; живий — зупиняємо після підтвердження.
  Future<void> _dismiss(BuildContext context, ActiveSyncRun run) async {
    final notifier = ref.read(catalogImportProvider.notifier);
    if (run.run.isFinished) {
      notifier.dismissSync();
      return;
    }
    if (await _confirmCancel(context)) await notifier.cancelSync(run.syncRunId);
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
    this.storeName,
    this.storeLogoUrl,
  });

  final SyncRun? job;
  final String status;
  final VoidCallback onDismiss;
  final String? storeName;
  final String? storeLogoUrl;

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
                        logoUrl: widget.storeLogoUrl,
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
                                      : widget.storeName?.trim().isNotEmpty ==
                                              true
                                          ? widget.storeName!.trim()
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
    this.logoUrl,
    this.size = 28,
  });

  final Color accent;
  final HeroIcons? icon;

  /// Логотип магазину: у черзі кількох імпортів саме він відрізняє рядки.
  final String? logoUrl;
  final double size;

  @override
  Widget build(BuildContext context) {
    if (icon != null) {
      return Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: accent.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(MarkoRadius.sm),
          border: Border.all(color: accent.withValues(alpha: 0.28)),
        ),
        alignment: Alignment.center,
        child: HeroIcon(icon!, size: size * 0.57, color: accent),
      );
    }

    final logo = logoUrl;
    if (logo != null && logo.isNotEmpty) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(MarkoRadius.sm),
        child: Image.network(
          logo,
          width: size,
          height: size,
          fit: BoxFit.contain,
          filterQuality: FilterQuality.high,
          // Логотип не завантажився — лишається загальний знак майданчика.
          errorBuilder: (_, _, _) => _promLogo(size),
        ),
      );
    }
    return _promLogo(size);
  }

  static Widget _promLogo(double size) => Image.asset(
        'assets/logos/prom.webp',
        width: size,
        height: size,
        fit: BoxFit.contain,
        filterQuality: FilterQuality.high,
      );
}

/// Магазин, що чекає своєї черги: рядок вужчий і спокійніший за активну капсулу.
class _QueuedRow extends StatelessWidget {
  const _QueuedRow({
    super.key,
    required this.run,
    required this.depth,
    required this.onCancel,
  });

  final ActiveSyncRun run;

  /// Глибина в згорнутому хвості: 0 — повний рядок, далі тьмяніше й дрібніше.
  final int depth;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final sunken = depth > 0;

    return AnimatedOpacity(
      duration: const Duration(milliseconds: 180),
      opacity: sunken ? 0.45 : 1,
      child: Container(
        constraints: BoxConstraints(maxWidth: sunken ? 440 : 480),
        margin: const EdgeInsets.symmetric(horizontal: MarkoSpace.lg),
        padding: const EdgeInsets.fromLTRB(8, 5, MarkoSpace.xs, 5),
        decoration: BoxDecoration(
          color: colors.surface.withValues(alpha: 0.9),
          borderRadius: BorderRadius.circular(MarkoRadius.md),
          border: Border.all(color: colors.border),
          boxShadow: sunken ? null : MarkoShadow.overlay,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _SyncBadge(
              accent: colors.muted,
              icon: null,
              logoUrl: run.storeLogoUrl,
              size: 22,
            ),
            const SizedBox(width: MarkoSpace.sm),
            Flexible(
              child: Text(
                run.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: colors.muted,
                  letterSpacing: -0.2,
                ),
              ),
            ),
            const SizedBox(width: MarkoSpace.sm),
            Text(
              run.run.statusLabel,
              style: MarkoType.caption.copyWith(color: colors.faint, fontSize: 11),
            ),
            const SizedBox(width: MarkoSpace.xs),
            _DismissButton(onPressed: onCancel),
          ],
        ),
      ),
    );
  }
}

/// «Ще N в черзі» — хвіст ховається, щоб черга не закривала каталог.
class _QueueToggle extends StatelessWidget {
  const _QueueToggle({
    required this.hidden,
    required this.expanded,
    required this.onPressed,
  });

  final int hidden;
  final bool expanded;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return TextButton.icon(
      onPressed: onPressed,
      icon: HeroIcon(
        expanded ? HeroIcons.chevronUp : HeroIcons.chevronDown,
        size: 14,
        color: colors.muted,
      ),
      label: Text(
        expanded ? 'Згорнути чергу' : 'Ще $hidden ${_plural(hidden)} в черзі',
        style: MarkoType.caption.copyWith(color: colors.muted, fontSize: 11.5),
      ),
      style: TextButton.styleFrom(
        padding: const EdgeInsets.symmetric(
          horizontal: MarkoSpace.sm,
          vertical: MarkoSpace.xxs,
        ),
        backgroundColor: colors.surface.withValues(alpha: 0.9),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(MarkoRadius.sm),
          side: BorderSide(color: colors.border),
        ),
      ),
    );
  }

  static String _plural(int count) {
    if (count % 10 == 1 && count % 100 != 11) return 'магазин';
    if ([2, 3, 4].contains(count % 10) && !(count % 100 >= 12 && count % 100 <= 14)) {
      return 'магазини';
    }
    return 'магазинів';
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
