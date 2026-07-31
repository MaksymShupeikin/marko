import 'package:flutter/material.dart';

import '../app_theme.dart';

class MarkoButton extends StatefulWidget {
  const MarkoButton({
    required this.label,
    required this.onPressed,
    this.icon,
    this.loading = false,
    this.expand = false,
    this.autofocus = false,
    super.key,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
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
    final brand = colors.brand;
    final ring = Color.lerp(brand, Colors.black, 0.10)!;
    final highlight = Color.lerp(brand, Colors.white, 0.30)!;
    final gradientStart = Color.lerp(
      brand,
      Colors.white,
      _hovered ? 0.30 : 0.15,
    )!;
    final gradientEnd = Color.lerp(brand, Colors.black, _pressed ? 0.07 : 0)!;
    final opacity = widget.onPressed == null && !widget.loading ? 0.5 : 1.0;

    final button = AnimatedScale(
      duration: const Duration(milliseconds: 90),
      scale: _pressed ? 0.985 : 1,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 120),
        opacity: opacity,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          curve: Curves.easeOut,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(9),
            border: Border.all(
              color: _focused ? ring : ring.withValues(alpha: 0.9),
              width: _focused ? 2 : 1,
            ),
            boxShadow: [
              if (_focused)
                BoxShadow(
                  color: ring.withValues(alpha: 0.28),
                  blurRadius: 0,
                  spreadRadius: 2,
                ),
              BoxShadow(
                color: colors.ink.withValues(alpha: _pressed ? 0.08 : 0.13),
                blurRadius: _pressed ? 1 : 3,
                offset: Offset(0, _pressed ? 0 : 1),
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(_focused ? 7 : 8),
            child: Stack(
              alignment: Alignment.center,
              children: [
                Positioned.fill(
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 120),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [gradientStart, gradientEnd],
                      ),
                    ),
                  ),
                ),
                Positioned(
                  top: 0,
                  left: 1,
                  right: 1,
                  child: Container(
                    height: 1,
                    color: highlight.withValues(alpha: 0.9),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 13,
                    vertical: 9,
                  ),
                  child: Row(
                    mainAxisSize: widget.expand
                        ? MainAxisSize.max
                        : MainAxisSize.min,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (widget.loading)
                        const SizedBox.square(
                          dimension: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      else if (widget.icon != null)
                        Icon(widget.icon, size: 17, color: Colors.white),
                      if (widget.loading || widget.icon != null)
                        const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          widget.label,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.labelLarge
                              ?.copyWith(
                                color: Colors.white,
                                fontSize: 14,
                                height: 1.15,
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );

    return Semantics(
      button: true,
      enabled: _enabled,
      label: widget.label,
      value: widget.loading ? 'Загрузка' : null,
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
        child: ConstrainedBox(
          constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _enabled ? _activate : null,
            onTapDown: _enabled ? (_) => setState(() => _pressed = true) : null,
            onTapUp: _enabled ? (_) => setState(() => _pressed = false) : null,
            onTapCancel: _enabled
                ? () => setState(() => _pressed = false)
                : null,
            child: widget.expand
                ? SizedBox(width: double.infinity, child: button)
                : button,
          ),
        ),
      ),
    );
  }

  void _activate() {
    if (!_enabled) return;
    widget.onPressed?.call();
  }
}
