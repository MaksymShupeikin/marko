import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/environment.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import 'auth_controller.dart';
import 'auth_models.dart';

class AuthPage extends ConsumerStatefulWidget {
  const AuthPage({super.key});

  @override
  ConsumerState<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends ConsumerState<AuthPage> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _register = false;
  bool _obscurePassword = true;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final asyncAuth = ref.watch(authControllerProvider);
    final auth = asyncAuth.value;
    final busy = asyncAuth.isLoading || auth?.busy == true;

    return Scaffold(
      body: GestureDetector(
        onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 960;
            if (!wide) {
              return _MobileAuthLayout(form: _buildForm(context, auth, busy));
            }
            return Row(
              children: [
                const Expanded(flex: 9, child: _AuthStory()),
                Expanded(
                  flex: 11,
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: IgnorePointer(
                          child: CustomPaint(
                            painter: _MonochromeGeometryPainter(
                              lineColor: colors.ink.withValues(alpha: 0.04),
                              crosshairColor: colors.ink.withValues(
                                alpha: 0.08,
                              ),
                              dotGrid: true,
                            ),
                          ),
                        ),
                      ),
                      Center(
                        child: SingleChildScrollView(
                          padding: const EdgeInsets.all(MarkoSpace.huge),
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 430),
                            child: _buildForm(context, auth, busy),
                          ),
                        ),
                      ),
                      const Positioned(
                        top: MarkoSpace.lg,
                        right: MarkoSpace.lg,
                        child: MarkoThemeToggle(),
                      ),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildForm(BuildContext context, MarkoAuthState? auth, bool busy) {
    final colors = MarkoTheme.of(context);
    final showGoogle = Environment.supportsGoogleSignIn;
    return MarkoPanel(
      padding: const EdgeInsets.all(MarkoSpace.xxl),
      child: AutofillGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              _register ? 'Створіть акаунт' : 'З поверненням',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: MarkoSpace.sm),
            Text(
              _register
                  ? 'Підключіть магазини, щоб додати товари для відстеження цін.'
                  : 'Увійдіть, щоб додати товари для відстеження цін.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: colors.muted),
            ),
            const SizedBox(height: MarkoSpace.xxl),
            if (showGoogle)
              MarkoButton.secondary(
                label: 'Продовжити з Google',
                leading: const _GoogleLogo(size: 18),
                onPressed: busy
                    ? null
                    : () => ref
                          .read(authControllerProvider.notifier)
                          .loginWithGoogle(),
                expand: true,
              ),
            if (!showGoogle)
              const MarkoInlineMessage(
                message:
                    'Google-вхід недоступний у нативній Windows-версії. '
                    'Використовуйте web/PWA або увійдіть поштою.',
                tone: MarkoMessageTone.warning,
              ),
            const SizedBox(height: MarkoSpace.xl),
            Row(
              children: [
                const Expanded(child: Divider()),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: MarkoSpace.md,
                  ),
                  child: Text(
                    'або через пошту',
                    style: MarkoType.caption.copyWith(color: colors.faint),
                  ),
                ),
                const Expanded(child: Divider()),
              ],
            ),
            const SizedBox(height: MarkoSpace.xl),
            MarkoTextField(
              controller: _emailController,
              enabled: !busy,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              labelText: 'Пошта',
              hintText: 'name@company.com',
              prefixIcon: HeroIcons.atSymbol,
            ),
            const SizedBox(height: MarkoSpace.md),
            MarkoTextField(
              controller: _passwordController,
              enabled: !busy,
              obscureText: _obscurePassword,
              autofillHints: _register
                  ? const [AutofillHints.newPassword]
                  : const [AutofillHints.password],
              onSubmitted: (_) => busy ? null : _submit(),
              labelText: 'Пароль',
              prefixIcon: HeroIcons.lockClosed,
              suffixIcon: IconButton(
                tooltip: _obscurePassword
                    ? 'Показати пароль'
                    : 'Сховати пароль',
                onPressed: () =>
                    setState(() => _obscurePassword = !_obscurePassword),
                icon: HeroIcon(
                  _obscurePassword ? HeroIcons.eye : HeroIcons.eyeSlash,
                  size: 18,
                ),
              ),
            ),
            if (auth?.error != null) ...[
              const SizedBox(height: MarkoSpace.md),
              MarkoInlineMessage(
                message: auth!.error!,
                tone: MarkoMessageTone.error,
              ),
            ],
            if (auth?.notice != null) ...[
              const SizedBox(height: MarkoSpace.md),
              MarkoInlineMessage(
                message: auth!.notice!,
                tone: MarkoMessageTone.success,
              ),
            ],
            const SizedBox(height: MarkoSpace.lg),
            MarkoButton(
              label: _register ? 'Створити акаунт' : 'Увійти',
              onPressed: busy ? null : _submit,
              loading: busy,
              expand: true,
            ),
            const SizedBox(height: MarkoSpace.sm),
            TextButton(
              onPressed: busy
                  ? null
                  : () => setState(() => _register = !_register),
              child: Text(
                _register
                    ? 'Вже є акаунт? Увійти'
                    : 'Немає акаунта? Зареєструватися',
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _submit() {
    FocusManager.instance.primaryFocus?.unfocus();
    final controller = ref.read(authControllerProvider.notifier);
    if (_register) {
      controller.register(_emailController.text, _passwordController.text);
    } else {
      controller.login(_emailController.text, _passwordController.text);
    }
  }
}

class _MobileAuthLayout extends StatelessWidget {
  const _MobileAuthLayout({required this.form});

  final Widget form;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Stack(
      children: [
        Positioned.fill(
          child: IgnorePointer(
            child: CustomPaint(
              painter: _MonochromeGeometryPainter(
                lineColor: colors.ink.withValues(alpha: 0.035),
                crosshairColor: colors.ink.withValues(alpha: 0.07),
                dotGrid: true,
              ),
            ),
          ),
        ),
        Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [MarkoWordmark(), Spacer(), MarkoThemeToggle()],
                  ),
                  const SizedBox(height: MarkoSpace.xxl),
                  form,
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _StoryPill extends StatelessWidget {
  const _StoryPill({required this.icon, required this.label});

  final HeroIcons icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.md,
        vertical: MarkoSpace.sm,
      ),
      decoration: BoxDecoration(
        color: colors.onInverse.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: colors.onInverse.withValues(alpha: 0.12)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          HeroIcon(
            icon,
            size: 15,
            color: colors.onInverse.withValues(alpha: 0.8),
          ),
          const SizedBox(width: MarkoSpace.sm),
          Text(
            label,
            style: MarkoType.caption.copyWith(
              color: colors.onInverse.withValues(alpha: 0.8),
            ),
          ),
        ],
      ),
    );
  }
}

class _AuthStory extends StatelessWidget {
  const _AuthStory();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Container(
      margin: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: const Color(0xFF090D14),
        borderRadius: BorderRadius.circular(MarkoRadius.xl),
        border: Border.all(color: colors.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0x4D000000),
            blurRadius: 36,
            offset: Offset(0, 16),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          // Monochrome geometric background lines & rings
          Positioned.fill(
            child: IgnorePointer(
              child: CustomPaint(
                painter: _MonochromeGeometryPainter(
                  lineColor: colors.onInverse.withValues(alpha: 0.035),
                  crosshairColor: colors.onInverse.withValues(alpha: 0.07),
                  dotGrid: true,
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(MarkoSpace.xxl),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final compact = constraints.maxHeight < 720;
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const MarkoWordmark(inverse: true),
                    SizedBox(height: compact ? MarkoSpace.md : MarkoSpace.lg),
                    const Expanded(
                      child: Center(
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          child: _AuthProductPreview(),
                        ),
                      ),
                    ),
                    SizedBox(height: compact ? MarkoSpace.sm : MarkoSpace.md),
                    Text(
                      'Ціни під\nконтролем.',
                      style: Theme.of(context).textTheme.displaySmall?.copyWith(
                        color: colors.onInverse,
                        fontSize: compact ? 28 : 36,
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.5,
                        height: 1.1,
                      ),
                    ),
                    const SizedBox(height: MarkoSpace.xs),
                    Text(
                      'Стежте за конкурентами, знаходьте розбіжності та ухвалюйте '
                      'рішення на основі актуальних даних.',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: colors.onInverse.withValues(alpha: 0.72),
                      ),
                    ),
                    SizedBox(height: compact ? MarkoSpace.md : MarkoSpace.lg),
                    Wrap(
                      spacing: MarkoSpace.sm,
                      runSpacing: MarkoSpace.sm,
                      children: [
                        for (final line in const [
                          (
                            HeroIcons.buildingStorefront,
                            'Імпорт каталогу Prom.ua',
                          ),
                          (HeroIcons.bolt, 'Ціни конкурентів за OEM'),
                          (
                            HeroIcons.presentationChartLine,
                            'Спред ринку: мін · медіана · макс',
                          ),
                        ])
                          _StoryPill(icon: line.$1, label: line.$2),
                      ],
                    ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _AuthProductPreview extends StatelessWidget {
  const _AuthProductPreview();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final border = colors.onInverse.withValues(alpha: 0.16);

    return Transform(
      transform: Matrix4.identity()
        ..setEntry(3, 2, 0.0006)
        ..rotateX(0.038)
        ..rotateY(-0.055)
        ..rotateZ(-0.015),
      alignment: Alignment.center,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: const Color(0xFF131A29),
            borderRadius: BorderRadius.circular(MarkoRadius.xl),
            border: Border.all(color: border, width: 1.2),
            boxShadow: const [
              BoxShadow(
                color: Color(0x99000000),
                blurRadius: 44,
                spreadRadius: -4,
                offset: Offset(0, 26),
              ),
              BoxShadow(
                color: Color(0x33000000),
                blurRadius: 12,
                offset: Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // macOS-style App Window Header (Monochrome)
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: MarkoSpace.md,
                  vertical: MarkoSpace.sm,
                ),
                child: Row(
                  children: [
                    _WindowDot(color: colors.onInverse.withValues(alpha: 0.25)),
                    const SizedBox(width: 6),
                    _WindowDot(color: colors.onInverse.withValues(alpha: 0.25)),
                    const SizedBox(width: 6),
                    _WindowDot(color: colors.onInverse.withValues(alpha: 0.25)),
                    const SizedBox(width: MarkoSpace.md),
                    Expanded(
                      child: Container(
                        height: 24,
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.35),
                          borderRadius: BorderRadius.circular(MarkoRadius.xs),
                          border: Border.all(
                            color: colors.onInverse.withValues(alpha: 0.08),
                          ),
                        ),
                        alignment: Alignment.centerLeft,
                        child: Text(
                          'marko.app/dashboard',
                          overflow: TextOverflow.ellipsis,
                          style: MarkoType.caption.copyWith(
                            color: colors.onInverse.withValues(alpha: 0.5),
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              // Real Dashboard Screenshot
              ClipRRect(
                borderRadius: const BorderRadius.only(
                  bottomLeft: Radius.circular(MarkoRadius.xl),
                  bottomRight: Radius.circular(MarkoRadius.xl),
                ),
                child: AspectRatio(
                  aspectRatio: 3024 / 1722,
                  child: Image.asset(
                    'assets/images/dashboard_screenshot.png',
                    fit: BoxFit.cover,
                    alignment: Alignment.topCenter,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WindowDot extends StatelessWidget {
  const _WindowDot({required this.color});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 9,
      height: 9,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(color: color.withValues(alpha: 0.4), blurRadius: 4),
        ],
      ),
    );
  }
}

/// Subtle, high-end technical monochrome geometry background
class _MonochromeGeometryPainter extends CustomPainter {
  const _MonochromeGeometryPainter({
    required this.lineColor,
    required this.crosshairColor,
    this.dotGrid = false,
  });

  final Color lineColor;
  final Color crosshairColor;
  final bool dotGrid;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);

    final linePaint = Paint()
      ..color = lineColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    final crossPaint = Paint()
      ..color = crosshairColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;

    // Concentric guide rings
    for (final r in [180.0, 320.0, 480.0, 660.0]) {
      canvas.drawCircle(center, r, linePaint);
    }

    // Diagonal axis guides
    canvas.drawLine(
      Offset(center.dx - 220, center.dy - 220),
      Offset(center.dx + 220, center.dy + 220),
      linePaint,
    );
    canvas.drawLine(
      Offset(center.dx + 220, center.dy - 220),
      Offset(center.dx - 220, center.dy + 220),
      linePaint,
    );

    // Crosshair ticks
    void drawCrosshair(double x, double y) {
      const s = 6.0;
      canvas.drawLine(Offset(x - s, y), Offset(x + s, y), crossPaint);
      canvas.drawLine(Offset(x, y - s), Offset(x, y + s), crossPaint);
    }

    drawCrosshair(size.width * 0.12, size.height * 0.15);
    drawCrosshair(size.width * 0.88, size.height * 0.15);
    drawCrosshair(size.width * 0.12, size.height * 0.85);
    drawCrosshair(size.width * 0.88, size.height * 0.85);
    drawCrosshair(size.width * 0.50, size.height * 0.08);
    drawCrosshair(size.width * 0.50, size.height * 0.92);

    // Subtle dot grid
    if (dotGrid) {
      final dotPaint = Paint()..color = crosshairColor;
      const step = 48.0;
      for (double x = step; x < size.width; x += step) {
        for (double y = step; y < size.height; y += step) {
          canvas.drawCircle(Offset(x, y), 0.9, dotPaint);
        }
      }
    }
  }

  @override
  bool shouldRepaint(covariant _MonochromeGeometryPainter oldDelegate) =>
      oldDelegate.lineColor != lineColor ||
      oldDelegate.crosshairColor != crosshairColor ||
      oldDelegate.dotGrid != dotGrid;
}

/// Official Google "G" multi-color vector logo.
class _GoogleLogo extends StatelessWidget {
  const _GoogleLogo({this.size = 18.0});

  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        size: Size(size, size),
        painter: const _GoogleLogoPainter(),
      ),
    );
  }
}

class _GoogleLogoPainter extends CustomPainter {
  const _GoogleLogoPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.width / 24.0;
    canvas.save();
    canvas.scale(scale, scale);

    // Blue (#4285F4)
    final bluePaint = Paint()
      ..color = const Color(0xFF4285F4)
      ..style = PaintingStyle.fill;
    final bluePath = Path()
      ..moveTo(23.745, 12.27)
      ..cubicTo(23.745, 11.48, 23.675, 10.73, 23.55, 10.0)
      ..lineTo(12.0, 10.0)
      ..lineTo(12.0, 14.51)
      ..lineTo(18.59, 14.51)
      ..cubicTo(18.3, 16.03, 17.43, 17.32, 16.12, 18.19)
      ..lineTo(20.02, 21.24)
      ..cubicTo(22.3, 19.14, 23.745, 16.05, 23.745, 12.27)
      ..close();
    canvas.drawPath(bluePath, bluePaint);

    // Green (#34A853)
    final greenPaint = Paint()
      ..color = const Color(0xFF34A853)
      ..style = PaintingStyle.fill;
    final greenPath = Path()
      ..moveTo(12.0, 24.0)
      ..cubicTo(15.24, 24.0, 17.96, 22.92, 19.98, 21.05)
      ..lineTo(16.08, 18.0)
      ..cubicTo(15.0, 18.73, 13.62, 19.17, 12.0, 19.17)
      ..cubicTo(8.87, 19.17, 6.22, 17.06, 5.27, 14.21)
      ..lineTo(1.25, 17.32)
      ..cubicTo(3.28, 21.36, 7.42, 24.0, 12.0, 24.0)
      ..close();
    canvas.drawPath(greenPath, greenPaint);

    // Yellow (#FBBC05)
    final yellowPaint = Paint()
      ..color = const Color(0xFFFBBC05)
      ..style = PaintingStyle.fill;
    final yellowPath = Path()
      ..moveTo(5.27, 14.29)
      ..cubicTo(5.02, 13.57, 4.89, 12.8, 4.89, 12.0)
      ..cubicTo(4.89, 11.2, 5.03, 10.43, 5.27, 9.71)
      ..lineTo(1.25, 6.6)
      ..cubicTo(0.45, 8.24, 0.0, 10.07, 0.0, 12.0)
      ..cubicTo(0.0, 13.93, 0.45, 15.76, 1.25, 17.4)
      ..lineTo(5.27, 14.29)
      ..close();
    canvas.drawPath(yellowPath, yellowPaint);

    // Red (#EA4335)
    final redPaint = Paint()
      ..color = const Color(0xFFEA4335)
      ..style = PaintingStyle.fill;
    final redPath = Path()
      ..moveTo(12.0, 4.75)
      ..cubicTo(13.77, 4.75, 15.35, 5.36, 16.6, 6.55)
      ..lineTo(20.07, 3.08)
      ..cubicTo(17.95, 1.17, 15.23, 0.0, 12.0, 0.0)
      ..cubicTo(7.42, 0.0, 3.28, 2.64, 1.25, 6.68)
      ..lineTo(5.27, 9.79)
      ..cubicTo(6.22, 6.94, 8.87, 4.75, 12.0, 4.75)
      ..close();
    canvas.drawPath(redPath, redPaint);

    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
