import 'package:flutter/material.dart';
import 'package:heroicons/heroicons.dart';

import '../app_theme.dart';
import 'marko_loader.dart';

enum MarkoButtonVariant { primary, secondary, ghost, danger }

class MarkoButton extends StatefulWidget {
  const MarkoButton({
    required this.label,
    required this.onPressed,
    this.icon,
    this.leading,
    this.variant = MarkoButtonVariant.primary,
    this.loading = false,
    this.expand = false,
    this.autofocus = false,
    super.key,
  });

  const MarkoButton.secondary({
    required this.label,
    required this.onPressed,
    this.icon,
    this.leading,
    this.loading = false,
    this.expand = false,
    this.autofocus = false,
    super.key,
  }) : variant = MarkoButtonVariant.secondary;

  const MarkoButton.ghost({
    required this.label,
    required this.onPressed,
    this.icon,
    this.leading,
    this.loading = false,
    this.expand = false,
    this.autofocus = false,
    super.key,
  }) : variant = MarkoButtonVariant.ghost;

  const MarkoButton.danger({
    required this.label,
    required this.onPressed,
    this.icon,
    this.leading,
    this.loading = false,
    this.expand = false,
    this.autofocus = false,
    super.key,
  }) : variant = MarkoButtonVariant.danger;

  final String label;
  final VoidCallback? onPressed;
  final HeroIcons? icon;
  final Widget? leading;
  final MarkoButtonVariant variant;
  final bool loading;
  final bool expand;
  final bool autofocus;

  @override
  State<MarkoButton> createState() => _MarkoButtonState();
}

class _MarkoButtonState extends State<MarkoButton> {
  bool _hovered = false;
  bool _focused = false;
  bool _pressed = false;

  bool get _enabled => widget.onPressed != null && !widget.loading;

  @override
  void didUpdateWidget(covariant MarkoButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_enabled && _pressed) _pressed = false;
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final height = MarkoLayout.fieldHeightOf(context);
    final isPrimary = widget.variant == MarkoButtonVariant.primary;
    final isSecondary = widget.variant == MarkoButtonVariant.secondary;
    final isGhost = widget.variant == MarkoButtonVariant.ghost;
    final isDanger = widget.variant == MarkoButtonVariant.danger;
    final isSolid = isPrimary || isDanger;

    // Solid (Primary / Danger) colors
    final solidColor = isDanger ? colors.negative : colors.brand;
    final solidRing = Color.lerp(solidColor, Colors.black, 0.16)!;
    final solidHighlight = Color.lerp(
      solidColor,
      Colors.white,
      _hovered ? 0.45 : 0.35,
    )!;
    final solidStart = Color.lerp(
      solidColor,
      Colors.white,
      _hovered ? 0.14 : 0.06,
    )!;
    final solidEnd = Color.lerp(
      solidColor,
      Colors.black,
      _pressed ? 0.14 : (_hovered ? 0.02 : 0.07),
    )!;

    // Secondary / Ghost colors
    final secondaryBg = _pressed
        ? colors.surfaceMuted
        : _hovered
        ? colors.surfaceMuted.withValues(alpha: 0.8)
        : colors.surface;
    final ghostBg = _pressed
        ? colors.surfaceMuted
        : _hovered
        ? colors.surfaceMuted
        : Colors.transparent;

    final borderColor = isSolid
        ? (_focused ? solidRing : solidRing.withValues(alpha: 0.9))
        : isSecondary
        ? (_hovered ? colors.borderStrong : colors.border)
        : Colors.transparent;

    final textColor = isSolid
        ? Colors.white
        : isGhost
        ? (_hovered ? colors.ink : colors.muted)
        : colors.ink;

    final opacity = widget.onPressed == null && !widget.loading ? 0.5 : 1.0;

    final button = SizedBox(
      height: height,
      width: widget.expand ? double.infinity : null,
      child: AnimatedScale(
        duration: const Duration(milliseconds: 90),
        scale: _pressed ? 0.985 : 1,
        child: AnimatedOpacity(
          duration: const Duration(milliseconds: 120),
          opacity: opacity,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            curve: Curves.easeOut,
            height: height,
            decoration: BoxDecoration(
              // The top highlight is the first 1px of the gradient, so it
              // follows the rounded corners instead of cutting across them.
              gradient: isSolid
                  ? LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [solidHighlight, solidStart, solidEnd],
                      stops: [0, 1 / height, 1],
                    )
                  : null,
              color: isSolid
                  ? null
                  : isSecondary
                  ? secondaryBg
                  : ghostBg,
              borderRadius: BorderRadius.circular(MarkoRadius.md),
              // Primary's ring sits outside the box, like Tailwind's `ring`:
              // a real border would paint over the 1px gradient highlight.
              border: isSolid
                  ? null
                  : Border.all(color: borderColor, width: _focused ? 1.5 : 1),
              boxShadow: [
                if (_focused)
                  BoxShadow(
                    color: (isSolid ? solidRing : colors.brand).withValues(
                      alpha: 0.35,
                    ),
                    blurRadius: 0,
                    spreadRadius: 2,
                  ),
                // 1. Soft Ambient Glow for optical depth and elevation
                if (isSolid && _enabled && !_pressed)
                  BoxShadow(
                    color: solidColor.withValues(alpha: _hovered ? 0.35 : 0.20),
                    blurRadius: _hovered ? 14 : 8,
                    spreadRadius: _hovered ? 0 : -2,
                    offset: Offset(0, _hovered ? 4 : 2),
                  ),
                // 2. Direct crisp tactile grounding shadow
                if (isSolid || (isSecondary && !_pressed))
                  BoxShadow(
                    color: colors.ink.withValues(
                      alpha: isSolid
                          ? (_pressed ? 0.10 : 0.18)
                          : (_pressed ? 0.02 : 0.04),
                    ),
                    blurRadius: _pressed ? 1 : 2.5,
                    offset: Offset(0, _pressed ? 0 : 1.5),
                  ),
                // 3. Crisp outer hairline border
                if (isSolid)
                  BoxShadow(
                    color: borderColor,
                    spreadRadius: _focused ? 1.5 : 1,
                    blurRadius: 0,
                  ),
              ],
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: Row(
                mainAxisSize: widget.expand
                    ? MainAxisSize.max
                    : MainAxisSize.min,
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  if (widget.loading)
                    MarkoLoader(size: 16, strokeWidth: 2, color: textColor)
                  else if (widget.leading != null)
                    widget.leading!
                  else if (widget.icon != null)
                    HeroIcon(widget.icon!, size: 17, color: textColor),
                  if (widget.loading ||
                      widget.leading != null ||
                      widget.icon != null)
                    const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      widget.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: textColor,
                        fontSize: MarkoLayout.fieldFontSizeOf(context),
                        height: 1.15,
                        fontWeight: FontWeight.w600,
                        shadows: isSolid
                            ? const [
                                Shadow(
                                  color: Color(0x38000000),
                                  offset: Offset(0, 1),
                                  blurRadius: 1.5,
                                ),
                              ]
                            : null,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );

    return Semantics(
      button: true,
      enabled: _enabled,
      label: widget.label,
      value: widget.loading ? 'Завантаження' : null,
      excludeSemantics: true,
      child: FocusableActionDetector(
        autofocus: widget.autofocus,
        enabled: _enabled,
        mouseCursor: _enabled
            ? SystemMouseCursors.click
            : SystemMouseCursors.basic,
        onShowHoverHighlight: (value) => setState(() => _hovered = value),
        onShowFocusHighlight: (value) => setState(() => _focused = value),
        actions: {
          ActivateIntent: CallbackAction<ActivateIntent>(
            onInvoke: (_) {
              _activate();
              return null;
            },
          ),
        },
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _enabled ? _activate : null,
          onTapDown: _enabled ? (_) => setState(() => _pressed = true) : null,
          onTapUp: _enabled ? (_) => setState(() => _pressed = false) : null,
          onTapCancel: _enabled ? () => setState(() => _pressed = false) : null,
          child: widget.expand
              ? SizedBox(width: double.infinity, child: button)
              : button,
        ),
      ),
    );
  }

  void _activate() {
    if (!_enabled) return;
    widget.onPressed?.call();
  }
}
