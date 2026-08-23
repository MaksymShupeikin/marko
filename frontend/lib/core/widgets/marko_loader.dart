import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app_theme.dart';

/// The only spinner in the app: a brand-tinted arc sweeping over a faint
/// track. Same shape at 14px in a button and at 32px on an empty page.
class MarkoLoader extends StatefulWidget {
  const MarkoLoader({
    this.size = 20,
    this.strokeWidth = 2,
    this.color,
    super.key,
  });

  final double size;
  final double strokeWidth;

  /// Defaults to the brand ink; solid buttons pass their own label colour.
  final Color? color;

  @override
  State<MarkoLoader> createState() => _MarkoLoaderState();
}

class _MarkoLoaderState extends State<MarkoLoader>
    with SingleTickerProviderStateMixin {
  late final AnimationController _spin = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat();

  @override
  void dispose() {
    _spin.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.color ?? MarkoTheme.of(context).brand;
    return SizedBox.square(
      dimension: widget.size,
      child: AnimatedBuilder(
        animation: _spin,
        builder: (context, _) => CustomPaint(
          painter: _MarkoLoaderPainter(
            t: _spin.value,
            color: color,
            strokeWidth: widget.strokeWidth,
          ),
        ),
      ),
    );
  }
}

class _MarkoLoaderPainter extends CustomPainter {
  const _MarkoLoaderPainter({
    required this.t,
    required this.color,
    required this.strokeWidth,
  });

  final double t;
  final Color color;
  final double strokeWidth;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(strokeWidth / 2);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth;

    canvas.drawArc(
      rect,
      0,
      2 * math.pi,
      false,
      base..color = color.withValues(alpha: 0.16),
    );

    // The arc grows and shrinks while it spins, so the motion still reads at
    // 14px where a constant quarter-circle just looks like a wobbling dash.
    final turn = t * 2 * math.pi;
    final sweep = (0.10 + 0.62 * (0.5 - 0.5 * math.cos(turn))) * 2 * math.pi;
    canvas.drawArc(
      rect,
      turn * 2 - math.pi / 2,
      sweep,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round
        ..color = color,
    );
  }

  @override
  bool shouldRepaint(_MarkoLoaderPainter old) =>
      old.t != t || old.color != color || old.strokeWidth != strokeWidth;
}
