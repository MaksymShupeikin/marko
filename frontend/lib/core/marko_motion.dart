import 'dart:async';

import 'package:flutter/material.dart';

import 'app_theme.dart';

/// Flutter ports of Motion enter/hover and Aceternity atmosphere.
/// The npm packages themselves cannot run in this Dart client.
const bool kFlutterTest = bool.fromEnvironment('FLUTTER_TEST');

/// `bool.fromEnvironment('FLUTTER_TEST')` is only true when the runner
/// forwards it as a dart-define. `flutter test` always uses a test binding.
bool get markoWidgetTestBinding {
  return WidgetsBinding.instance.runtimeType.toString().contains(
    'TestWidgetsFlutterBinding',
  );
}

bool markoLoopingMotionEnabled(BuildContext context) {
  if (kFlutterTest || markoWidgetTestBinding) return false;
  if (MediaQuery.disableAnimationsOf(context)) return false;
  if (!TickerMode.valuesOf(context).enabled) return false;
  return true;
}

bool markoEnterMotionEnabled(BuildContext context) {
  if (kFlutterTest || markoWidgetTestBinding) return false;
  if (MediaQuery.disableAnimationsOf(context)) return false;
  return true;
}

abstract final class MarkoMotion {
  static const Duration enter = Duration(milliseconds: 520);
  static const Duration hover = Duration(milliseconds: 220);
  static const Duration pulse = Duration(milliseconds: 1800);
  static const Duration atmosphere = Duration(seconds: 16);
  static const Curve enterCurve = Curves.easeOutCubic;
  static const Curve hoverCurve = Curves.easeOutCubic;
  static const double hoverScale = 1.012;
  static const double enterOffset = 16;
}

/// Motion-style fade + rise. Plays once, then stays put.
class MarkoFadeUp extends StatefulWidget {
  const MarkoFadeUp({
    required this.child,
    this.delay = Duration.zero,
    this.duration = MarkoMotion.enter,
    this.offset = MarkoMotion.enterOffset,
    super.key,
  });

  final Widget child;
  final Duration delay;
  final Duration duration;
  final double offset;

  @override
  State<MarkoFadeUp> createState() => _MarkoFadeUpState();
}

class _MarkoFadeUpState extends State<MarkoFadeUp>
    with SingleTickerProviderStateMixin {
  AnimationController? _controller;
  Animation<double>? _opacity;
  Animation<Offset>? _slide;
  Timer? _delay;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!markoEnterMotionEnabled(context) || _controller != null) return;
    final controller = AnimationController(
      vsync: this,
      duration: widget.duration,
    );
    _controller = controller;
    _opacity = CurvedAnimation(
      parent: controller,
      curve: MarkoMotion.enterCurve,
    );
    _slide = Tween<Offset>(begin: Offset(0, widget.offset), end: Offset.zero)
        .animate(
          CurvedAnimation(parent: controller, curve: MarkoMotion.enterCurve),
        );
    final delay = widget.delay;
    if (delay == Duration.zero) {
      controller.forward();
    } else {
      _delay = Timer(delay, () {
        if (mounted) controller.forward();
      });
    }
  }

  @override
  void dispose() {
    _delay?.cancel();
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    final opacity = _opacity;
    final slide = _slide;
    if (controller == null || opacity == null || slide == null) {
      return widget.child;
    }
    return AnimatedBuilder(
      animation: controller,
      builder: (context, child) {
        return Opacity(
          opacity: opacity.value,
          child: Transform.translate(offset: slide.value, child: child),
        );
      },
      child: widget.child,
    );
  }
}

class MarkoStagger extends StatelessWidget {
  const MarkoStagger({
    required this.children,
    this.step = const Duration(milliseconds: 55),
    this.offset = MarkoMotion.enterOffset,
    super.key,
  });

  final List<Widget> children;
  final Duration step;
  final double offset;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var index = 0; index < children.length; index++)
          MarkoFadeUp(
            delay: step * index,
            offset: offset,
            child: children[index],
          ),
      ],
    );
  }
}

/// Subtle scale + shadow on hover. Resting layout matches [child].
class MarkoHoverLift extends StatefulWidget {
  const MarkoHoverLift({
    required this.child,
    this.borderRadius,
    this.enabled = true,
    super.key,
  });

  final Widget child;
  final BorderRadius? borderRadius;
  final bool enabled;

  @override
  State<MarkoHoverLift> createState() => _MarkoHoverLiftState();
}

class _MarkoHoverLiftState extends State<MarkoHoverLift> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final lift = widget.enabled && _hovered;
    return MouseRegion(
      onEnter: widget.enabled ? (_) => setState(() => _hovered = true) : null,
      onExit: widget.enabled ? (_) => setState(() => _hovered = false) : null,
      child: AnimatedScale(
        scale: lift ? MarkoMotion.hoverScale : 1,
        duration: MarkoMotion.hover,
        curve: MarkoMotion.hoverCurve,
        child: AnimatedContainer(
          duration: MarkoMotion.hover,
          curve: MarkoMotion.hoverCurve,
          decoration: BoxDecoration(
            borderRadius: widget.borderRadius,
            boxShadow: [
              if (lift)
                BoxShadow(
                  color: colors.ink.withValues(alpha: 0.10),
                  blurRadius: 22,
                  offset: const Offset(0, 10),
                ),
            ],
          ),
          child: widget.child,
        ),
      ),
    );
  }
}

/// Expanding ring around a status dot. Idle when looping motion is off.
class MarkoStatusPulse extends StatefulWidget {
  const MarkoStatusPulse({required this.color, this.size = 6, super.key});

  final Color color;
  final double size;

  @override
  State<MarkoStatusPulse> createState() => _MarkoStatusPulseState();
}

class _MarkoStatusPulseState extends State<MarkoStatusPulse>
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
      duration: MarkoMotion.pulse,
    )..repeat();
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dot = Container(
      width: widget.size,
      height: widget.size,
      decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle),
    );
    final controller = _controller;
    if (controller == null || !markoLoopingMotionEnabled(context)) return dot;
    return SizedBox.square(
      dimension: widget.size * 2.6,
      child: AnimatedBuilder(
        animation: controller,
        builder: (context, child) {
          final t = Curves.easeOut.transform(controller.value);
          return Stack(
            alignment: Alignment.center,
            children: [
              Opacity(
                opacity: (1 - t) * 0.45,
                child: Transform.scale(
                  scale: 1 + t * 1.6,
                  child: Container(
                    width: widget.size,
                    height: widget.size,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: widget.color, width: 1.2),
                    ),
                  ),
                ),
              ),
              child!,
            ],
          );
        },
        child: dot,
      ),
    );
  }
}

/// Aceternity-style gradient headline. Static when motion is off.
class MarkoGradientText extends StatelessWidget {
  const MarkoGradientText(
    this.text, {
    this.style,
    this.animate = true,
    super.key,
  });

  final String text;
  final TextStyle? style;
  final bool animate;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final resolved = (style ?? Theme.of(context).textTheme.displaySmall)
        ?.copyWith(color: Colors.white);
    if (!animate || !markoLoopingMotionEnabled(context)) {
      return Text(text, style: resolved);
    }
    return _ShimmerText(
      text: text,
      style: resolved,
      colors: [
        Colors.white,
        Color.lerp(Colors.white, colors.brand, 0.25)!,
        Colors.white,
      ],
    );
  }
}

class _ShimmerText extends StatefulWidget {
  const _ShimmerText({
    required this.text,
    required this.style,
    required this.colors,
  });

  final String text;
  final TextStyle? style;
  final List<Color> colors;

  @override
  State<_ShimmerText> createState() => _ShimmerTextState();
}

class _ShimmerTextState extends State<_ShimmerText>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 5),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return ShaderMask(
          blendMode: BlendMode.srcIn,
          shaderCallback: (bounds) {
            return LinearGradient(
              begin: Alignment(-1.4 + _controller.value * 2.8, 0),
              end: Alignment(1.4 + _controller.value * 2.8, 0),
              colors: widget.colors,
            ).createShader(bounds);
          },
          child: child,
        );
      },
      child: Text(widget.text, style: widget.style),
    );
  }
}
