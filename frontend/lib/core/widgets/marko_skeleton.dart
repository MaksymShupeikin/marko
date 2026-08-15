import 'package:flutter/material.dart';

import '../app_theme.dart';
import '../marko_motion.dart';

class MarkoSkeleton extends StatefulWidget {
  const MarkoSkeleton({
    this.width,
    this.height = 14,
    this.radius = 7,
    super.key,
  });

  final double? width;
  final double height;
  final double radius;

  @override
  State<MarkoSkeleton> createState() => _MarkoSkeletonState();
}

class _MarkoSkeletonState extends State<MarkoSkeleton>
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
      duration: const Duration(milliseconds: 1150),
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
    final highlight = Color.lerp(colors.surfaceMuted, colors.surface, 0.78)!;
    final box = DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surfaceMuted,
        borderRadius: BorderRadius.circular(widget.radius),
      ),
    );
    final controller = _controller;
    final child = controller == null
        ? box
        : AnimatedBuilder(
            animation: controller,
            builder: (context, child) {
              final position = -1.8 + (controller.value * 3.6);
              return ShaderMask(
                blendMode: BlendMode.srcATop,
                shaderCallback: (bounds) => LinearGradient(
                  begin: Alignment(position - 0.8, -0.3),
                  end: Alignment(position + 0.8, 0.3),
                  colors: [colors.surfaceMuted, highlight, colors.surfaceMuted],
                  stops: const [0.25, 0.5, 0.75],
                ).createShader(bounds),
                child: child,
              );
            },
            child: box,
          );
    return SizedBox(width: widget.width, height: widget.height, child: child);
  }
}

class MarkoQueueSkeleton extends StatelessWidget {
  const MarkoQueueSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpacing.lg,
        vertical: MarkoSpacing.lg + MarkoSpacing.xxs,
      ),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: MarkoBreakpoints.wide),
            child: const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                MarkoSkeleton(width: 240, height: 28, radius: 8),
                SizedBox(height: MarkoSpacing.xs),
                MarkoSkeleton(width: 420, height: 14),
                SizedBox(height: MarkoSpacing.lg),
                MarkoSkeleton(width: double.infinity, height: 88, radius: 12),
                SizedBox(height: MarkoSpacing.md),
                MarkoSkeleton(width: double.infinity, height: 88, radius: 12),
                SizedBox(height: MarkoSpacing.md),
                MarkoSkeleton(width: double.infinity, height: 88, radius: 12),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
