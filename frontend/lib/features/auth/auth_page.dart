import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/app_theme.dart';
import '../../core/environment.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';
import '../products/products_models.dart';
import '../products/widgets/product_details_panel.dart';
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
  bool _rememberMe = true;

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
            // RTL child order paints the form side first and the story last,
            // so the app-window preview overhanging the panel edge draws on
            // top of the form column's background pattern instead of under it.
            return Row(
              textDirection: TextDirection.rtl,
              children: [
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
                const Expanded(flex: 9, child: _AuthStory()),
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
                  ? 'Створіть обліковий запис для моніторингу цін'
                  : 'Увійдіть для моніторингу цін конкурентів',
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
            const MarkoLabelledDivider(label: 'або через пошту'),
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
            if (!_register) ...[
              const SizedBox(height: MarkoSpace.xs),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Flexible(
                    child: InkWell(
                      borderRadius: BorderRadius.circular(MarkoRadius.xs),
                      onTap: busy
                          ? null
                          : () => setState(() => _rememberMe = !_rememberMe),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            SizedBox(
                              width: 18,
                              height: 18,
                              child: Checkbox(
                                value: _rememberMe,
                                onChanged: busy
                                    ? null
                                    : (v) => setState(
                                        () => _rememberMe = v ?? false,
                                      ),
                                materialTapTargetSize:
                                    MaterialTapTargetSize.shrinkWrap,
                                visualDensity: VisualDensity.compact,
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(4),
                                ),
                              ),
                            ),
                            const SizedBox(width: 6),
                            Flexible(
                              child: Text(
                                "Запам'ятати мене",
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(
                                      color: colors.muted,
                                      fontWeight: FontWeight.w500,
                                    ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: MarkoSpace.xs),
                  TextButton(
                    onPressed: busy
                        ? null
                        : () => ref
                              .read(authControllerProvider.notifier)
                              .resetPassword(_emailController.text),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 4,
                        vertical: 4,
                      ),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      visualDensity: VisualDensity.compact,
                    ),
                    child: const Text('Забули пароль?'),
                  ),
                ],
              ),
            ],
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
      // No clip: the app-window preview deliberately sticks out of the panel
      // towards the auth card. The painter clips itself to the rounded rect.
      child: Stack(
        children: [
          Positioned.fill(
            child: IgnorePointer(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(MarkoRadius.xl),
                child: CustomPaint(
                  painter: _MonochromeGeometryPainter(
                    lineColor: Colors.white.withValues(alpha: 0.035),
                  ),
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
                    SizedBox(height: compact ? MarkoSpace.lg : MarkoSpace.xxl),
                    Text(
                      'Ціни під контролем',
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
                      'рішення на основі актуальних даних',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Colors.white.withValues(alpha: 0.72),
                      ),
                    ),
                    SizedBox(height: compact ? MarkoSpace.md : MarkoSpace.lg),
                    // Overhangs the panel edge to the right, towards the
                    // auth card.
                    Expanded(
                      child: Align(
                        alignment: Alignment.bottomRight,
                        child: Transform.translate(
                          offset: const Offset(60, 0),
                          child: const _AuthProductPreview(),
                        ),
                      ),
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
    with TickerProviderStateMixin {
  late final AnimationController _animController;
  late final AnimationController _autoScroll;
  final _scroll = ScrollController();
  Timer? _resumeTimer;
  Timer? _stageTimer;
  Offset _hoverOffset = Offset.zero;
  bool _isHovered = false;
  String? _searchStage;

  static const _searchQuery = 'markoprice.com';

  /// The real backend stages, canned: the demo loops the exact captions the
  /// live search emits, then shows the report and re-runs every 10 seconds.
  static const _searchStages = [
    ('Готуємо пошукові запити', Duration(milliseconds: 1400)),
    ('Збираємо пропозиції: Avto.pro', Duration(milliseconds: 2400)),
    ('Avto.pro: знайдено 28', Duration(milliseconds: 1100)),
    ('Звіряємо 34 варіанти з нашою деталлю', Duration(milliseconds: 2400)),
    ('Відсіяли 6 чужих позицій', Duration(milliseconds: 900)),
  ];

  void _runDemoSearch([int step = 0]) {
    if (!mounted) return;
    if (step >= _searchStages.length) {
      setState(() => _searchStage = null);
      _stageTimer = Timer(const Duration(seconds: 10), _runDemoSearch);
      return;
    }
    final (caption, duration) = _searchStages[step];
    setState(() => _searchStage = caption);
    _stageTimer = Timer(duration, () => _runDemoSearch(step + 1));
  }

  /// Canned catalog product + market report: the preview renders the exact
  /// product details sheet the app shows, scrollable, with results in place.
  /// Photo: Wikimedia Commons "Bosch Oil Filter.JPG", CC BY-SA 4.0.
  static const _demoProduct = StoreProduct(
    id: 'demo',
    name: 'Фільтр масляний Bosch P 2023 для VW Golf IV / Skoda Octavia Tour 1.6-1.8T (оригінал)',
    url: '',
    sku: '0986452023',
    brand: 'BOSCH',
    price: 265,
    currency: 'UAH',
    isAvailable: true,
    imageUrl: 'assets/demo/oil_filter.webp',
    storeName: 'Мій магазин на Prom',
    oemNumbers: ['P 2023', '06A 115 561 B', 'W 719/30'],
  );

  static const _demoReport = CompetitorPriceReport(
    cached: true,
    observedAt: null,
    stats: CompetitorPriceStats(
      offersTotal: 28,
      sourcesTotal: 1,
      minPrice: 210,
      medianPrice: 285,
      maxPrice: 390,
    ),
    sources: [
      SourcePriceResult(
        source: 'avtopro',
        label: 'Avto.pro',
        status: 'completed',
        offersTotal: 28,
        minPrice: 210,
        medianPrice: 285,
        maxPrice: 390,
        offers: [
          MarketPriceOffer(
            source: 'avtopro',
            title: 'Фільтр масляний VAG 06A 115 561 B',
            price: 210,
            currency: 'UAH',
            url: '',
            seller: 'AvtoParts',
            city: 'Київ',
            condition: 'new',
          ),
          MarketPriceOffer(
            source: 'avtopro',
            title: 'Фільтр оливний 06A115561B для Golf IV',
            price: 235,
            currency: 'UAH',
            url: '',
            seller: 'VAG Detali',
            city: 'Одеса',
            condition: 'new',
          ),
          MarketPriceOffer(
            source: 'avtopro',
            title: 'MANN-FILTER W 719/30 фільтр оливний',
            price: 265,
            currency: 'UAH',
            url: '',
            seller: 'FilterMaster',
            city: 'Львів',
            isAnalog: true,
          ),
          MarketPriceOffer(
            source: 'avtopro',
            title: 'Фільтр масляний 06A115561B VAG (оригінал)',
            price: 285,
            currency: 'UAH',
            url: '',
            seller: 'InterTrade',
            city: 'Дніпро',
            condition: 'new',
          ),
          MarketPriceOffer(
            source: 'avtopro',
            title: 'KNECHT OC 264 масляний фільтр',
            price: 340,
            currency: 'UAH',
            url: '',
            seller: 'AutoLider',
            city: 'Харків',
            isAnalog: true,
          ),
          MarketPriceOffer(
            source: 'avtopro',
            title: 'Оригінальний фільтр VAG 06A 115 561 B',
            price: 390,
            currency: 'UAH',
            url: '',
            seller: 'PremiumParts',
            city: 'Київ',
            condition: 'new',
          ),
        ],
      ),
    ],
  );

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    )..repeat();
    // Slow ping-pong through the sheet; pauses while the user scrolls.
    _autoScroll = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 22),
    )..addListener(_tickAutoScroll);
    _autoScroll.repeat(reverse: true);
    _stageTimer = Timer(const Duration(seconds: 10), _runDemoSearch);
  }

  @override
  void dispose() {
    _resumeTimer?.cancel();
    _stageTimer?.cancel();
    _animController.dispose();
    _autoScroll.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _tickAutoScroll() {
    if (!_scroll.hasClients) return;
    final max = _scroll.position.maxScrollExtent;
    if (max <= 0) return;
    _scroll.jumpTo(max * _autoScroll.value);
  }

  /// Any pointer activity hands the scroll to the user; the auto-scroll
  /// resumes from wherever they left it after a short idle pause.
  void _pauseAutoScroll() {
    _autoScroll.stop();
    _resumeTimer?.cancel();
    _resumeTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      if (_scroll.hasClients && _scroll.position.maxScrollExtent > 0) {
        _autoScroll.value = (_scroll.offset / _scroll.position.maxScrollExtent)
            .clamp(0.0, 1.0);
      }
      _autoScroll.repeat(reverse: true);
    });
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
            final charCount = ((t / 0.35) * _searchQuery.length).floor().clamp(
              0,
              _searchQuery.length,
            );
            displayedText = _searchQuery.substring(0, charCount);
          } else if (t < 0.85) {
            displayedText = _searchQuery;
          } else {
            final charCount = (((1.0 - t) / 0.15) * _searchQuery.length)
                .floor()
                .clamp(0, _searchQuery.length);
            displayedText = _searchQuery.substring(0, charCount);
          }

          final showCursor = (t * 16).floor() % 2 == 0;

          // 2. 3D tilt only follows the mouse; at rest the window sits flat.
          final targetRotX = -(_hoverOffset.dy * 0.04);
          final targetRotY = _hoverOffset.dx * 0.05;

          return Transform(
            transform: Matrix4.identity()
              ..setEntry(3, 2, 0.0006)
              ..rotateX(targetRotX)
              ..rotateY(targetRotY),
            alignment: Alignment.center,
            child: ConstrainedBox(
              // The real app's details sheet is 480 wide — same proportions
              // here keep the demo honest and the composition balanced.
              constraints: const BoxConstraints(maxWidth: 500, maxHeight: 660),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: isDark
                      ? const Color(0xFF191A22)
                      : const Color(0xFF111319),
                  borderRadius: BorderRadius.circular(MarkoRadius.xl),
                  border: Border.all(color: border, width: 1.2),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(
                        alpha: _isHovered ? 0.75 : 0.60,
                      ),
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
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(MarkoRadius.xl),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // macOS-style App Window Header
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 6,
                        ),
                        decoration: const BoxDecoration(
                          border: Border(
                            bottom: BorderSide(color: Color(0x1AFFFFFF)),
                          ),
                        ),
                        child: Row(
                          children: [
                            const _WindowDot(color: Color(0x55FF5F56)),
                            const SizedBox(width: 6),
                            const _WindowDot(color: Color(0x55FFBD2E)),
                            const SizedBox(width: 6),
                            const _WindowDot(color: Color(0x5527C93F)),
                            const SizedBox(width: 12),
                            // Simulated Search Bar in header
                            Expanded(
                              child: Container(
                                height: 22,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.black.withValues(alpha: 0.40),
                                  borderRadius: BorderRadius.circular(
                                    MarkoRadius.sm,
                                  ),
                                  border: Border.all(
                                    color: const Color(0x22FFFFFF),
                                  ),
                                ),
                                child: Row(
                                  children: [
                                    HeroIcon(
                                      HeroIcons.magnifyingGlass,
                                      size: 13,
                                      color: Colors.white.withValues(
                                        alpha: 0.5,
                                      ),
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

                      // The product UI itself: the exact details sheet the app
                      // renders for a catalog product, auto-scrolling until
                      // the user takes over, with results already in place.
                      Expanded(
                        child: Listener(
                          behavior: HitTestBehavior.translucent,
                          onPointerDown: (_) => _pauseAutoScroll(),
                          onPointerSignal: (event) {
                            if (event is PointerScrollEvent) _pauseAutoScroll();
                          },
                          child: Stack(
                            children: [
                              ProductDetailsPreview(
                                product: _demoProduct,
                                report: _demoReport,
                                controller: _scroll,
                                searchStage: _searchStage,
                              ),
                              // Scroll affordance: fades away once past the top.
                              Positioned(
                                left: 0,
                                right: 0,
                                bottom: 12,
                                child: Center(
                                  child: IgnorePointer(
                                    child: AnimatedBuilder(
                                      animation: _scroll,
                                      builder: (context, child) =>
                                          AnimatedOpacity(
                                            duration: const Duration(
                                              milliseconds: 250,
                                            ),
                                            opacity:
                                                !_scroll.hasClients ||
                                                    _scroll.offset < 60
                                                ? 1
                                                : 0,
                                            child: child,
                                          ),
                                      child: Container(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 10,
                                          vertical: 5,
                                        ),
                                        decoration: BoxDecoration(
                                          color: Colors.black.withValues(
                                            alpha: 0.65,
                                          ),
                                          borderRadius: BorderRadius.circular(
                                            999,
                                          ),
                                        ),
                                        child: Row(
                                          mainAxisSize: MainAxisSize.min,
                                          children: [
                                            const HeroIcon(
                                              HeroIcons.chevronDown,
                                              size: 13,
                                              color: Colors.white,
                                            ),
                                            const SizedBox(width: 5),
                                            Text(
                                              'Гортайте',
                                              style: MarkoType.caption.copyWith(
                                                color: Colors.white,
                                                fontWeight: FontWeight.w600,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                    ),
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
              ),
            ),
          );
        },
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
      width: 8,
      height: 8,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
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
