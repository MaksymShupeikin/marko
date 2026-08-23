import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/environment.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import 'auth_controller.dart';
import 'auth_models.dart';
import 'widgets/google_auth_button.dart';

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
              GoogleAuthButton(
                busy: busy,
                fallback: MarkoButton.secondary(
                  label: 'Продовжити з Google',
                  leading: const _GoogleLogo(size: 18),
                  onPressed: busy
                      ? null
                      : () => ref
                            .read(authControllerProvider.notifier)
                            .loginWithGoogle(),
                  expand: true,
                ),
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
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MarkoSpace.md,
        vertical: MarkoSpace.sm,
      ),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(MarkoRadius.md),
        border: Border.all(color: Colors.white.withValues(alpha: 0.12)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          HeroIcon(
            icon,
            size: 15,
            color: Colors.white.withValues(alpha: 0.85),
          ),
          const SizedBox(width: MarkoSpace.sm),
          Text(
            label,
            style: MarkoType.caption.copyWith(
              color: Colors.white.withValues(alpha: 0.85),
              fontWeight: FontWeight.w500,
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
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      margin: const EdgeInsets.all(MarkoSpace.md),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF18181D) : const Color(0xFF0D0E12),
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
                  lineColor: Colors.white.withValues(alpha: 0.035),
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
                        color: Colors.white,
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
                        color: Colors.white.withValues(alpha: 0.72),
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

class _AuthProductPreview extends StatefulWidget {
  const _AuthProductPreview();

  @override
  State<_AuthProductPreview> createState() => _AuthProductPreviewState();
}

class _AuthProductPreviewState extends State<_AuthProductPreview>
    with SingleTickerProviderStateMixin {
  late final AnimationController _animController;
  Offset _hoverOffset = Offset.zero;
  bool _isHovered = false;

  static const _searchQuery = '06A 115 561 B';

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    )..repeat();
  }

  @override
  void dispose() {
    _animController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final colors = MarkoTheme.of(context);
    const border = Color(0x2EFFFFFF);

    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() {
        _isHovered = false;
        _hoverOffset = Offset.zero;
      }),
      onHover: (event) {
        final box = context.findRenderObject() as RenderBox?;
        if (box != null && box.hasSize) {
          final center = box.size.center(Offset.zero);
          final rel = (event.localPosition - center);
          setState(() {
            _hoverOffset = Offset(
              (rel.dx / (box.size.width / 2)).clamp(-1.0, 1.0),
              (rel.dy / (box.size.height / 2)).clamp(-1.0, 1.0),
            );
          });
        }
      },
      child: AnimatedBuilder(
        animation: _animController,
        builder: (context, child) {
          final t = _animController.value;

          // 1. Typing animation (0.0 .. 0.35 typing, 0.35 .. 0.85 visible, 0.85 .. 1.0 pause/reset)
          String displayedText;
          if (t < 0.35) {
            final charCount =
                ((t / 0.35) * _searchQuery.length).floor().clamp(0, _searchQuery.length);
            displayedText = _searchQuery.substring(0, charCount);
          } else if (t < 0.85) {
            displayedText = _searchQuery;
          } else {
            final charCount =
                (((1.0 - t) / 0.15) * _searchQuery.length).floor().clamp(0, _searchQuery.length);
            displayedText = _searchQuery.substring(0, charCount);
          }

          final showCursor = (t * 16).floor() % 2 == 0;

          // 2. Smooth oscillating user price pin (min 220, max 340)
          // Sine wave oscillation for smooth natural price exploration
          final double dynamicPriceFraction = (0.35 + 0.30 * (0.5 + 0.5 * math.sin(t * 2 * math.pi))).clamp(0.15, 0.85);
          final dynamicUserPrice = (210 + dynamicPriceFraction * (390 - 210)).round();
          final diffPct = (((dynamicUserPrice - 285) / 285) * 100).round();

          // 3. 3D Matrix tilt with smooth mouse hover tracking
          final targetRotX = 0.035 - (_hoverOffset.dy * 0.04);
          final targetRotY = -0.045 + (_hoverOffset.dx * 0.05);

          return Transform(
            transform: Matrix4.identity()
              ..setEntry(3, 2, 0.0006)
              ..rotateX(targetRotX)
              ..rotateY(targetRotY)
              ..rotateZ(-0.012),
            alignment: Alignment.center,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: isDark ? const Color(0xFF191A22) : const Color(0xFF111319),
                  borderRadius: BorderRadius.circular(MarkoRadius.xl),
                  border: Border.all(color: border, width: 1.2),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: _isHovered ? 0.75 : 0.60),
                      blurRadius: _isHovered ? 48 : 36,
                      spreadRadius: -4,
                      offset: const Offset(0, 20),
                    ),
                    BoxShadow(
                      color: colors.brand.withValues(alpha: 0.08),
                      blurRadius: 32,
                      offset: const Offset(0, 6),
                    ),
                  ],
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // macOS-style App Window Header
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      decoration: const BoxDecoration(
                        border: Border(bottom: BorderSide(color: Color(0x1AFFFFFF))),
                      ),
                      child: Row(
                        children: [
                          const _WindowDot(color: Color(0x55FF5F56)),
                          const SizedBox(width: 6),
                          const _WindowDot(color: Color(0x55FFBD2E)),
                          const SizedBox(width: 6),
                          const _WindowDot(color: Color(0x5527C93F)),
                          const SizedBox(width: 14),
                          // Simulated Search Bar in header
                          Expanded(
                            child: Container(
                              height: 26,
                              padding: const EdgeInsets.symmetric(horizontal: 10),
                              decoration: BoxDecoration(
                                color: Colors.black.withValues(alpha: 0.40),
                                borderRadius: BorderRadius.circular(MarkoRadius.sm),
                                border: Border.all(color: const Color(0x22FFFFFF)),
                              ),
                              child: Row(
                                children: [
                                  HeroIcon(
                                    HeroIcons.magnifyingGlass,
                                    size: 13,
                                    color: Colors.white.withValues(alpha: 0.5),
                                  ),
                                  const SizedBox(width: 6),
                                  Expanded(
                                    child: RichText(
                                      overflow: TextOverflow.ellipsis,
                                      text: TextSpan(
                                        text: displayedText,
                                        style: const TextStyle(
                                          color: Colors.white,
                                          fontSize: 11.5,
                                          fontWeight: FontWeight.w500,
                                          fontFamily: 'monospace',
                                        ),
                                        children: [
                                          if (showCursor)
                                            const TextSpan(
                                              text: '|',
                                              style: TextStyle(
                                                color: Color(0xFF60A5FA),
                                                fontWeight: FontWeight.w700,
                                              ),
                                            ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),

                    // Inner Live UI Demonstration
                    Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          // 1. Live Product Header
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.center,
                            children: [
                              Container(
                                width: 34,
                                height: 34,
                                decoration: BoxDecoration(
                                  color: Colors.white.withValues(alpha: 0.08),
                                  borderRadius: BorderRadius.circular(MarkoRadius.sm),
                                  border: Border.all(color: const Color(0x24FFFFFF)),
                                ),
                                alignment: Alignment.center,
                                child: const HeroIcon(
                                  HeroIcons.cube,
                                  size: 18,
                                  color: Colors.white,
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    const Text(
                                      'Фільтр масляний VAG',
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        color: Colors.white,
                                        fontSize: 13,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    const SizedBox(height: 2),
                                    Row(
                                      children: [
                                        Container(
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 5,
                                            vertical: 1,
                                          ),
                                          decoration: BoxDecoration(
                                            color: Colors.white.withValues(alpha: 0.1),
                                            borderRadius: BorderRadius.circular(3),
                                          ),
                                          child: const Text(
                                            '06A 115 561 B',
                                            style: TextStyle(
                                              color: Color(0xFF94A3B8),
                                              fontSize: 10,
                                              fontFamily: 'monospace',
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(width: 6),
                                        Text(
                                          '· 28 пропозицій на ринку',
                                          style: TextStyle(
                                            color: Colors.white.withValues(alpha: 0.5),
                                            fontSize: 11,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),

                          const SizedBox(height: 12),

                          // 2. Animated Spectrum Gauge Box
                          Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: Colors.black.withValues(alpha: 0.28),
                              borderRadius: BorderRadius.circular(MarkoRadius.md),
                              border: Border.all(color: const Color(0x1FFFFFFF)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                // Stats 3 cards
                                const Row(
                                  children: [
                                    Expanded(
                                      child: _DemoStat(
                                        label: 'Мінімум',
                                        value: '210 ₴',
                                        color: Color(0xFF34D399),
                                      ),
                                    ),
                                    SizedBox(width: 6),
                                    Expanded(
                                      child: _DemoStat(
                                        label: 'Медіана',
                                        value: '285 ₴',
                                        color: Colors.white,
                                      ),
                                    ),
                                    SizedBox(width: 6),
                                    Expanded(
                                      child: _DemoStat(
                                        label: 'Максимум',
                                        value: '390 ₴',
                                        color: Color(0xFFF87171),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 12),

                                // Animated Spectrum Track with floating user badge
                                LayoutBuilder(
                                  builder: (context, gaugeConstraints) {
                                    final gw = gaugeConstraints.maxWidth;
                                    final pinPos = (dynamicPriceFraction * (gw - 12))
                                        .clamp(0.0, gw - 12);
                                    final pillPos = (pinPos - 38).clamp(0.0, gw - 86);

                                    return Column(
                                      children: [
                                        SizedBox(
                                          height: 20,
                                          child: Stack(
                                            clipBehavior: Clip.none,
                                            children: [
                                              Positioned(
                                                left: pillPos,
                                                child: Container(
                                                  padding: const EdgeInsets.symmetric(
                                                    horizontal: 6,
                                                    vertical: 2,
                                                  ),
                                                  decoration: BoxDecoration(
                                                    color: const Color(0xFF60A5FA),
                                                    borderRadius: BorderRadius.circular(4),
                                                    boxShadow: [
                                                      BoxShadow(
                                                        color: const Color(0xFF60A5FA)
                                                            .withValues(alpha: 0.4),
                                                        blurRadius: 6,
                                                        offset: const Offset(0, 2),
                                                      ),
                                                    ],
                                                  ),
                                                  child: Row(
                                                    mainAxisSize: MainAxisSize.min,
                                                    children: [
                                                      Container(
                                                        width: 4,
                                                        height: 4,
                                                        decoration: const BoxDecoration(
                                                          color: Colors.white,
                                                          shape: BoxShape.circle,
                                                        ),
                                                      ),
                                                      const SizedBox(width: 4),
                                                      Text(
                                                        'Ви: $dynamicUserPrice ₴ (${diffPct >= 0 ? '+$diffPct' : diffPct}%)',
                                                        style: const TextStyle(
                                                          color: Colors.white,
                                                          fontSize: 10,
                                                          fontWeight: FontWeight.w700,
                                                        ),
                                                      ),
                                                    ],
                                                  ),
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                        const SizedBox(height: 3),
                                        SizedBox(
                                          height: 10,
                                          child: Stack(
                                            alignment: Alignment.centerLeft,
                                            children: [
                                              Container(
                                                height: 5,
                                                decoration: BoxDecoration(
                                                  borderRadius: BorderRadius.circular(999),
                                                  gradient: const LinearGradient(
                                                    colors: [
                                                      Color(0xFF34D399),
                                                      Color(0xFF60A5FA),
                                                      Color(0xFFFBBF24),
                                                      Color(0xFFF87171),
                                                    ],
                                                    stops: [0.0, 0.4, 0.75, 1.0],
                                                  ),
                                                ),
                                              ),
                                              // Median Line (0.42 fraction)
                                              Positioned(
                                                left: (gw - 2) * 0.42,
                                                child: Container(
                                                  width: 2,
                                                  height: 10,
                                                  decoration: BoxDecoration(
                                                    color: Colors.white,
                                                    borderRadius: BorderRadius.circular(1),
                                                  ),
                                                ),
                                              ),
                                              // Dynamic Pin Dot
                                              Positioned(
                                                left: pinPos,
                                                child: Container(
                                                  width: 12,
                                                  height: 12,
                                                  decoration: BoxDecoration(
                                                    shape: BoxShape.circle,
                                                    color: const Color(0xFF60A5FA),
                                                    border: Border.all(
                                                      color: Colors.white,
                                                      width: 2,
                                                    ),
                                                    boxShadow: const [
                                                      BoxShadow(
                                                        color: Color(0x66000000),
                                                        blurRadius: 4,
                                                        offset: Offset(0, 1),
                                                      ),
                                                    ],
                                                  ),
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                      ],
                                    );
                                  },
                                ),
                              ],
                            ),
                          ),

                          const SizedBox(height: 10),

                          // 3. Competitor Live Offers List
                          const _DemoOfferRow(
                            seller: 'AvtoParts Київ',
                            city: 'Київ (в наявності)',
                            price: '235 ₴',
                            tag: '-17% нижче',
                            isCheaper: true,
                          ),
                          const SizedBox(height: 4),
                          const _DemoOfferRow(
                            seller: 'InterTrade Дніпро',
                            city: 'Дніпро (1 день)',
                            price: '285 ₴',
                            tag: 'медіана',
                            isCheaper: null,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _DemoStat extends StatelessWidget {
  const _DemoStat({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.5),
              fontSize: 9.5,
            ),
          ),
          const SizedBox(height: 1),
          Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 11.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _DemoOfferRow extends StatelessWidget {
  const _DemoOfferRow({
    required this.seller,
    required this.city,
    required this.price,
    required this.tag,
    required this.isCheaper,
  });

  final String seller;
  final String city;
  final String price;
  final String tag;
  final bool? isCheaper;

  @override
  Widget build(BuildContext context) {
    final tagColor = isCheaper == true
        ? const Color(0xFF34D399)
        : isCheaper == false
        ? const Color(0xFFF87171)
        : const Color(0xFF94A3B8);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.03),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: const Color(0x14FFFFFF)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  seller,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 11,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                Text(
                  city,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.45),
                    fontSize: 9.5,
                  ),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
            decoration: BoxDecoration(
              color: tagColor.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(3),
              border: Border.all(color: tagColor.withValues(alpha: 0.28)),
            ),
            child: Text(
              tag,
              style: TextStyle(
                color: tagColor,
                fontSize: 9,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            price,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
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
      ),
    );
  }
}

/// Blueprint texture: graph paper, drawing frame, dimension lines, section hatch.
class _MonochromeGeometryPainter extends CustomPainter {
  const _MonochromeGeometryPainter({required this.lineColor});

  final Color lineColor;

  @override
  void paint(Canvas canvas, Size size) {
    final a = lineColor.a;
    Paint pen(double alphaScale, double width) => Paint()
      ..color = lineColor.withValues(alpha: (a * alphaScale).clamp(0.0, 1.0))
      ..strokeWidth = width
      ..style = PaintingStyle.stroke;

    final fine = pen(0.45, 1.0);
    final coarse = pen(0.9, 1.0);
    final frame = pen(1.6, 1.4);
    final dim = pen(1.3, 1.0);

    // Graph paper: fine cells, every 5th line heavier.
    const cell = 16.0;
    for (double x = 0, i = 0; x < size.width; x += cell, i++) {
      canvas.drawLine(
        Offset(x, 0),
        Offset(x, size.height),
        i % 5 == 0 ? coarse : fine,
      );
    }
    for (double y = 0, i = 0; y < size.height; y += cell, i++) {
      canvas.drawLine(
        Offset(0, y),
        Offset(size.width, y),
        i % 5 == 0 ? coarse : fine,
      );
    }

    // Drawing frame + title block in the bottom-right corner.
    const m = 24.0;
    final sheet = Rect.fromLTRB(m, m, size.width - m, size.height - m);
    canvas.drawRect(sheet, frame);
    final block = Rect.fromLTRB(
      sheet.right - 210,
      sheet.bottom - 64,
      sheet.right,
      sheet.bottom,
    );
    canvas.drawRect(block, frame);
    canvas.drawLine(
      Offset(block.left, block.top + 22),
      Offset(block.right, block.top + 22),
      frame,
    );
    canvas.drawLine(
      Offset(block.left + 130, block.top + 22),
      Offset(block.left + 130, block.bottom),
      frame,
    );

    // Dimension line with arrowheads and extension lines.
    void arrow(Offset tip, double dx) {
      canvas.drawLine(tip, tip.translate(dx, -4), dim);
      canvas.drawLine(tip, tip.translate(dx, 4), dim);
    }

    void dimension(Offset from, Offset to, double extend) {
      canvas.drawLine(from, to, dim);
      canvas.drawLine(from.translate(0, -extend), from.translate(0, 6), dim);
      canvas.drawLine(to.translate(0, -extend), to.translate(0, 6), dim);
      arrow(from, 9);
      arrow(to, -9);
    }

    dimension(
      Offset(sheet.left + 40, size.height * 0.22),
      Offset(sheet.left + 40 + size.width * 0.34, size.height * 0.22),
      34,
    );
    dimension(
      Offset(size.width * 0.46, size.height * 0.78),
      Offset(size.width * 0.46 + 150, size.height * 0.78),
      -28,
    );

    // Section hatch: 45° lines inside one small band, like a cut view.
    final band = Rect.fromLTWH(
      sheet.left + 40,
      size.height * 0.34,
      size.width * 0.22,
      70,
    );
    canvas.save();
    canvas.clipRect(band);
    for (double x = band.left - band.height; x < band.right; x += 9) {
      canvas.drawLine(
        Offset(x, band.top),
        Offset(x + band.height, band.bottom),
        dim,
      );
    }
    canvas.restore();
    canvas.drawRect(band, coarse);

    // Centre line: long-dash / short-dash through the band.
    final cy = band.center.dy;
    for (double x = band.left - 26; x < band.right + 26; x += 26) {
      canvas.drawLine(Offset(x, cy), Offset(x + 14, cy), dim);
      canvas.drawLine(Offset(x + 19, cy), Offset(x + 22, cy), dim);
    }
  }

  @override
  bool shouldRepaint(covariant _MonochromeGeometryPainter oldDelegate) =>
      oldDelegate.lineColor != lineColor;
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
