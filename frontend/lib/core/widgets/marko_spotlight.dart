import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';

import '../app_theme.dart';
import '../marko_motion.dart';

/// Aceternity spotlight: a soft brand wash that follows the pointer.
class MarkoSpotlight extends StatefulWidget {
  const MarkoSpotlight({
    required this.child,
    this.borderRadius,
    this.enabled = true,
    super.key,
  });

  final Widget child;
  final BorderRadius? borderRadius;
  final bool enabled;

  @override
  State<MarkoSpotlight> createState() => _MarkoSpotlightState();
}

class _MarkoSpotlightState extends State<MarkoSpotlight> {
  Offset? _local;

  @override
  Widget build(BuildContext context) {
    final radius = widget.borderRadius ?? BorderRadius.zero;
    final colors = MarkoTheme.of(context);
    return MouseRegion(
      onHover: widget.enabled
          ? (event) => setState(() => _local = event.localPosition)
          : null,
      onExit: widget.enabled ? (_) => setState(() => _local = null) : null,
      child: ClipRRect(
        borderRadius: radius,
        child: Stack(
          children: [
            widget.child,
            if (_local != null)
              Positioned.fill(
                child: IgnorePointer(
                  child: CustomPaint(
                    painter: _SpotlightPainter(
                      center: _local!,
                      color: colors.brand.withValues(alpha: 0.14),
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

class _SpotlightPainter extends CustomPainter {
  const _SpotlightPainter({required this.center, required this.color});

  final Offset center;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final radius = size.shortestSide * 0.72;
    final paint = Paint()
      ..shader = RadialGradient(
        colors: [color, color.withValues(alpha: 0)],
      ).createShader(Rect.fromCircle(center: center, radius: radius));
    canvas.drawRect(Offset.zero & size, paint);
  }

  @override
  bool shouldRepaint(covariant _SpotlightPainter oldDelegate) {
    return oldDelegate.center != center || oldDelegate.color != color;
  }
}

/// Travelling gradient segment around a rounded rect. Static in tests.
class MarkoMovingBorder extends StatefulWidget {
  const MarkoMovingBorder({
    required this.child,
    this.radius = 12,
    this.strokeWidth = 1.4,
    super.key,
  });

  final Widget child;
  final double radius;
  final double strokeWidth;

  @override
  State<MarkoMovingBorder> createState() => _MarkoMovingBorderState();
}

class _MarkoMovingBorderState extends State<MarkoMovingBorder>
    with SingleTickerProviderStateMixin {
  AnimationController? _controller;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!markoLoopingMotionEnabled(context)) {
      _controller?.stop();
      return;
    }
    _controller ??= AnimationController(
      vsync: this,
      duration: const Duration(seconds: 6),
    )..repeat();
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final controller = _controller;
    final content = widget.child;
    if (controller == null) return content;
    return AnimatedBuilder(
      animation: controller,
      builder: (context, child) {
        return CustomPaint(
          foregroundPainter: _MovingBorderPainter(
            progress: controller.value,
            radius: widget.radius,
            strokeWidth: widget.strokeWidth,
            color: colors.brand,
            soft: colors.brandSoft,
          ),
          child: child,
        );
      },
      child: content,
    );
  }
}

class _MovingBorderPainter extends CustomPainter {
  const _MovingBorderPainter({
    required this.progress,
    required this.radius,
    required this.strokeWidth,
    required this.color,
    required this.soft,
  });

  final double progress;
  final double radius;
  final double strokeWidth;
  final Color color;
  final Color soft;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final rrect = RRect.fromRectAndRadius(
      rect.deflate(strokeWidth / 2),
      Radius.circular(radius),
    );
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..shader = SweepGradient(
        startAngle: 0,
        endAngle: math.pi * 2,
        transform: GradientRotation(progress * math.pi * 2),
        colors: [
          color.withValues(alpha: 0),
          color,
          soft,
          color.withValues(alpha: 0),
        ],
        stops: const [0.0, 0.18, 0.32, 0.48],
      ).createShader(rect);
    canvas.drawRRect(rrect, paint);
  }

  @override
  bool shouldRepaint(covariant _MovingBorderPainter oldDelegate) {
    return oldDelegate.progress != progress ||
        oldDelegate.radius != radius ||
        oldDelegate.strokeWidth != strokeWidth ||
        oldDelegate.color != color ||
        oldDelegate.soft != soft;
  }
}

/// Soft frosted wash used on the auth story badge.
class MarkoGlass extends StatelessWidget {
  const MarkoGlass({
    required this.child,
    this.padding = const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    this.radius = 8,
    super.key,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(radius),
            border: Border.all(color: Colors.white.withValues(alpha: 0.14)),
          ),
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}
