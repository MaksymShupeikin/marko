import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app_theme.dart';
import '../marko_motion.dart';

enum MarkoAtmosphereVariant { canvas, ink }

/// Aceternity-style aurora + beams + meteors, painted behind [child].
class MarkoAtmosphere extends StatefulWidget {
  const MarkoAtmosphere({
    required this.child,
    this.variant = MarkoAtmosphereVariant.canvas,
    this.beams = true,
    this.meteors = false,
    this.sparkles = false,
    super.key,
  });

  final Widget child;
  final MarkoAtmosphereVariant variant;
  final bool beams;
  final bool meteors;
  final bool sparkles;

  @override
  State<MarkoAtmosphere> createState() => _MarkoAtmosphereState();
}

class _MarkoAtmosphereState extends State<MarkoAtmosphere>
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
      duration: MarkoMotion.atmosphere,
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
    final ink = widget.variant == MarkoAtmosphereVariant.ink;
    final controller = _controller;
    final painter = _AtmospherePainter(
      progress: controller?.value ?? 0,
      ink: ink,
      beams: widget.beams,
      meteors: widget.meteors && ink,
      sparkles: widget.sparkles && ink,
      brand: colors.brand,
      canvas: ink ? colors.ink : colors.canvas,
    );
    final backdrop = controller == null
        ? CustomPaint(painter: painter, child: const SizedBox.expand())
        : AnimatedBuilder(
            animation: controller,
            builder: (context, _) {
              return CustomPaint(
                painter: _AtmospherePainter(
                  progress: controller.value,
                  ink: ink,
                  beams: widget.beams,
                  meteors: widget.meteors && ink,
                  sparkles: widget.sparkles && ink,
                  brand: colors.brand,
                  canvas: ink ? colors.ink : colors.canvas,
                ),
                child: const SizedBox.expand(),
              );
            },
          );
    return Stack(
      fit: StackFit.expand,
      children: [
        RepaintBoundary(child: backdrop),
        widget.child,
      ],
    );
  }
}

class _AtmospherePainter extends CustomPainter {
  const _AtmospherePainter({
    required this.progress,
    required this.ink,
    required this.beams,
    required this.meteors,
    required this.sparkles,
    required this.brand,
    required this.canvas,
  });

  final double progress;
  final bool ink;
  final bool beams;
  final bool meteors;
  final bool sparkles;
  final Color brand;
  final Color canvas;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = this.canvas);
    _paintAurora(canvas, size);
    if (beams) _paintBeams(canvas, size);
    if (meteors) _paintMeteors(canvas, size);
    if (sparkles) _paintSparkles(canvas, size);
  }

  void _paintAurora(Canvas canvas, Size size) {
    final t = progress * math.pi * 2;
    final blobs = <(Offset, double, Color)>[
      (
        Offset(
          size.width * (0.18 + 0.04 * math.sin(t)),
          size.height * (0.22 + 0.05 * math.cos(t * 0.8)),
        ),
        size.shortestSide * (ink ? 0.62 : 0.48),
        brand.withValues(alpha: ink ? 0.34 : 0.10),
      ),
      (
        Offset(
          size.width * (0.82 + 0.05 * math.cos(t * 0.9)),
          size.height * (0.28 + 0.04 * math.sin(t * 1.1)),
        ),
        size.shortestSide * (ink ? 0.55 : 0.40),
        Color.lerp(
          brand,
          Colors.white,
          ink ? 0.35 : 0.2,
        )!.withValues(alpha: ink ? 0.22 : 0.07),
      ),
      (
        Offset(
          size.width * (0.52 + 0.06 * math.sin(t * 0.7 + 1)),
          size.height * (0.78 + 0.03 * math.cos(t * 0.6)),
        ),
        size.shortestSide * (ink ? 0.70 : 0.52),
        (ink ? Colors.white : brand).withValues(alpha: ink ? 0.07 : 0.05),
      ),
    ];
    for (final blob in blobs) {
      final paint = Paint()
        ..shader = RadialGradient(
          colors: [blob.$3, blob.$3.withValues(alpha: 0)],
        ).createShader(Rect.fromCircle(center: blob.$1, radius: blob.$2));
      canvas.drawCircle(blob.$1, blob.$2, paint);
    }
  }

  void _paintBeams(Canvas canvas, Size size) {
    final count = ink ? 7 : 4;
    for (var i = 0; i < count; i++) {
      final phase = (progress + i / count) % 1;
      final x = size.width * (-0.2 + 1.4 * ((i / count + phase * 0.15) % 1));
      final paint = Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            Colors.transparent,
            (ink ? Colors.white : brand).withValues(alpha: ink ? 0.10 : 0.045),
            Colors.transparent,
          ],
        ).createShader(Offset.zero & size)
        ..strokeWidth = ink ? 1.2 : 1
        ..style = PaintingStyle.stroke;
      canvas.drawLine(
        Offset(x, -20),
        Offset(x + size.height * 0.28, size.height + 20),
        paint,
      );
    }
  }

  void _paintMeteors(Canvas canvas, Size size) {
    const seeds = [0.08, 0.23, 0.41, 0.57, 0.72, 0.88];
    for (var i = 0; i < seeds.length; i++) {
      final cycle = (progress * (0.7 + i * 0.08) + seeds[i]) % 1;
      final startX = size.width * (0.1 + seeds[i] * 0.85);
      final y = size.height * (-0.1 + cycle * 1.2);
      final x = startX + cycle * size.width * 0.18;
      final fade = cycle < 0.12
          ? cycle / 0.12
          : cycle > 0.82
          ? (1 - cycle) / 0.18
          : 1.0;
      final paint = Paint()
        ..shader = LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Colors.white.withValues(alpha: 0),
            Colors.white.withValues(alpha: 0.55 * fade),
          ],
        ).createShader(Rect.fromLTWH(x - 40, y - 6, 48, 12))
        ..strokeWidth = 1.3
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(Offset(x - 36, y - 14), Offset(x, y), paint);
    }
  }

  void _paintSparkles(Canvas canvas, Size size) {
    const points = [
      (0.18, 0.16),
      (0.72, 0.12),
      (0.88, 0.38),
      (0.12, 0.62),
      (0.41, 0.48),
      (0.63, 0.71),
      (0.91, 0.82),
    ];
    for (var i = 0; i < points.length; i++) {
      final twinkle =
          0.35 +
          0.65 *
              (0.5 +
                  0.5 *
                      math.sin(progress * math.pi * 2 * (1.2 + i * 0.17) + i));
      final center = Offset(
        size.width * points[i].$1,
        size.height * points[i].$2,
      );
      canvas.drawCircle(
        center,
        1.1 + twinkle,
        Paint()..color = Colors.white.withValues(alpha: 0.18 + 0.45 * twinkle),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _AtmospherePainter oldDelegate) {
    return oldDelegate.progress != progress ||
        oldDelegate.ink != ink ||
        oldDelegate.beams != beams ||
        oldDelegate.meteors != meteors ||
        oldDelegate.sparkles != sparkles ||
        oldDelegate.brand != brand ||
        oldDelegate.canvas != canvas;
  }
}
