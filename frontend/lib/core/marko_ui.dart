import 'package:flutter/material.dart';

import 'app_theme.dart';

class MarkoWordmark extends StatelessWidget {
  const MarkoWordmark({this.compact = false, this.inverse = false, super.key});

  final bool compact;
  final bool inverse;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: compact ? 30 : 34,
          height: compact ? 30 : 34,
          decoration: BoxDecoration(
            color: inverse ? Colors.white.withValues(alpha: 0.12) : colors.ink,
            borderRadius: BorderRadius.circular(9),
            border: inverse
                ? Border.all(color: Colors.white.withValues(alpha: 0.14))
                : null,
          ),
          alignment: Alignment.center,
          child: Icon(
            Icons.show_chart_rounded,
            size: compact ? 18 : 20,
            color: Colors.white,
          ),
        ),
        const SizedBox(width: 10),
        Text(
          'Marko',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            fontSize: compact ? 17 : 19,
            letterSpacing: -0.4,
            color: inverse ? Colors.white : colors.ink,
          ),
        ),
      ],
    );
  }
}

class MarkoPanel extends StatelessWidget {
  const MarkoPanel({
    required this.child,
    this.padding = const EdgeInsets.all(20),
    this.color,
    this.borderColor,
    this.onTap,
    super.key,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final Color? borderColor;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final radius = BorderRadius.circular(colors.panelRadius);
    final content = Padding(padding: padding, child: child);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color ?? colors.surface,
        borderRadius: radius,
        border: Border.all(color: borderColor ?? colors.border),
      ),
      child: onTap == null
          ? content
          : Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: radius,
                onTap: onTap,
                child: content,
              ),
            ),
    );
  }
}

enum MarkoMessageTone { info, success, warning, error }

class MarkoInlineMessage extends StatelessWidget {
  const MarkoInlineMessage({
    required this.message,
    this.tone = MarkoMessageTone.info,
    this.action,
    super.key,
  });

  final String message;
  final MarkoMessageTone tone;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final (foreground, background, icon) = switch (tone) {
      MarkoMessageTone.info => (
        colors.brand,
        colors.brandSoft,
        Icons.info_outline,
      ),
      MarkoMessageTone.success => (
        colors.positive,
        colors.positiveSoft,
        Icons.check_circle_outline,
      ),
      MarkoMessageTone.warning => (
        colors.warning,
        colors.warningSoft,
        Icons.warning_amber_rounded,
      ),
      MarkoMessageTone.error => (
        colors.negative,
        colors.negativeSoft,
        Icons.error_outline,
      ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(icon, size: 18, color: foreground),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: foreground,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          if (action != null) ...[const SizedBox(width: 8), action!],
        ],
      ),
    );
  }
}
