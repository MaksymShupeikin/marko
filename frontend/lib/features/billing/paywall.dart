import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../core/api_client.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import '../../core/widgets/marko_button.dart';

/// Set to true to always show the Paywall UI by default for local testing / preview.
const bool showPaywallDemo = false;

/// Whether this error is the backend's 402 paywall response.
bool isPaywallError(Object error) =>
    showPaywallDemo || (error is ApiException && error.statusCode == 402);

/// Shown in place of price-check results once the free limit is spent: what
/// the full version gives and a "contact us" request that unlocks it manually.
class PaywallCard extends ConsumerStatefulWidget {
  const PaywallCard({super.key});

  @override
  ConsumerState<PaywallCard> createState() => _PaywallCardState();
}

class _PaywallCardState extends ConsumerState<PaywallCard> {
  bool _busy = false;
  bool _requested = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  Future<void> _loadStatus() async {
    try {
      final payload = await ref
          .read(apiClientProvider)
          .getJson('/api/v1/billing/access-request');
      final requested = (payload as Map<String, dynamic>)['requested'] == true;
      if (mounted && requested) setState(() => _requested = true);
    } catch (_) {} // Не змогли дізнатися — просто покажемо кнопку.
  }

  Future<void> _requestAccess() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .postJson('/api/v1/billing/access-request');
      if (mounted) setState(() => _requested = true);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'Не вдалося надіслати запит. Спробуйте ще раз.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    const benefits = [
      'Необмежені перевірки цін конкурентів',
      'Усі джерела: Prom.ua, Avto.pro та Google',
      'Актуальні ціни для всього каталогу',
    ];

    return MarkoPanel(
      padding: EdgeInsets.zero,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 440),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _BlueprintHero(),
            Padding(
              padding: const EdgeInsets.all(MarkoSpace.xxl),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Безкоштовні перевірки закінчилися',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: MarkoSpace.xs),
                  Text(
                    'Ви використали безкоштовний ліміт. Щоб відкрити повний '
                    'доступ, надішліть запит — ми звʼяжемося з вами.',
                    style: Theme.of(
                      context,
                    ).textTheme.bodySmall?.copyWith(color: colors.muted),
                  ),
                  const SizedBox(height: MarkoSpace.lg),
                  for (final benefit in benefits) ...[
                    Row(
                      children: [
                        HeroIcon(
                          HeroIcons.checkCircle,
                          size: 16,
                          color: colors.positive,
                        ),
                        const SizedBox(width: MarkoSpace.sm),
                        Expanded(
                          child: Text(
                            benefit,
                            style: Theme.of(context).textTheme.bodyMedium,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: MarkoSpace.sm),
                  ],
                  const SizedBox(height: MarkoSpace.sm),
                  if (_requested)
                    const MarkoInlineMessage(
                      message:
                          'Запит надіслано. Ми звʼяжемося з вами '
                          'найближчим часом.',
                      tone: MarkoMessageTone.success,
                    )
                  else
                    MarkoButton(
                      label: 'Звʼязатися з нами',
                      icon: HeroIcons.envelope,
                      loading: _busy,
                      expand: true,
                      onPressed: _busy ? null : _requestAccess,
                    ),
                  if (_error != null) ...[
                    const SizedBox(height: MarkoSpace.md),
                    MarkoInlineMessage(
                      message: _error!,
                      tone: MarkoMessageTone.error,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Blueprint hero: yellow graph paper (the login-page texture recipe) with a
/// minimal price-search motif — a magnifying glass over a price, currency
/// glyphs floating on the grid.
class _BlueprintHero extends StatelessWidget {
  const _BlueprintHero();

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return ClipRRect(
      borderRadius: BorderRadius.vertical(
        top: Radius.circular(colors.panelRadius),
      ),
      child: Container(
        height: 140,
        decoration: BoxDecoration(
          color: colors.warningSoft,
          border: Border(bottom: BorderSide(color: colors.border)),
        ),
        child: CustomPaint(
          size: Size.infinite,
          painter: _BlueprintHeroPainter(
            ink: colors.ink,
            yellow: colors.warning,
          ),
        ),
      ),
    );
  }
}

class _BlueprintHeroPainter extends CustomPainter {
  const _BlueprintHeroPainter({required this.ink, required this.yellow});

  final Color ink;
  final Color yellow;

  void _glyph(
    Canvas canvas,
    String text,
    Offset center, {
    required Color color,
    required double fontSize,
    FontWeight weight = FontWeight.w600,
  }) {
    final painter = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(color: color, fontSize: fontSize, fontWeight: weight),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    painter.paint(
      canvas,
      center - Offset(painter.width / 2, painter.height / 2),
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    Paint pen(Color color, double alpha, double width) => Paint()
      ..color = color.withValues(alpha: alpha)
      ..strokeWidth = width
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    // Yellow graph paper, same recipe as the login background: fine cells,
    // every 5th line heavier.
    final fine = pen(yellow, 0.14, 1.0);
    final coarse = pen(yellow, 0.28, 1.0);
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

    // Drawing-sheet dressing over the grid: frame, title block in the
    // bottom-right corner, a dimension line with arrows — so it reads as an
    // actual blueprint, not just graph paper.
    final draft = pen(yellow, 0.45, 1.1);
    const m = 12.0;
    final sheet = Rect.fromLTRB(m, m, size.width - m, size.height - m);
    canvas.drawRect(sheet, draft);
    final block = Rect.fromLTRB(
      sheet.right - 96,
      sheet.bottom - 28,
      sheet.right,
      sheet.bottom,
    );
    canvas.drawRect(block, draft);
    canvas.drawLine(
      Offset(block.left, block.top + 14),
      Offset(block.right, block.top + 14),
      draft,
    );
    canvas.drawLine(
      Offset(block.left + 58, block.top + 14),
      Offset(block.left + 58, block.bottom),
      draft,
    );

    void arrow(Offset tip, double dx) {
      canvas.drawLine(tip, tip.translate(dx, -3.5), draft);
      canvas.drawLine(tip, tip.translate(dx, 3.5), draft);
    }

    final dimY = size.height * 0.17;
    final dimFrom = Offset(size.width * 0.36, dimY);
    final dimTo = Offset(size.width * 0.52, dimY);
    canvas.drawLine(dimFrom, dimTo, draft);
    canvas.drawLine(dimFrom.translate(0, -6), dimFrom.translate(0, 8), draft);
    canvas.drawLine(dimTo.translate(0, -6), dimTo.translate(0, 8), draft);
    arrow(dimFrom, 8);
    arrow(dimTo, -8);

    final lens = pen(yellow, 1.0, 2.4);

    // Magnifying glass, off-centre to the right, with the price in the lens.
    final c = Offset(size.width * 0.64, size.height * 0.44);
    final r = size.height * 0.28;
    canvas.drawCircle(c, r, lens);
    // Handle at 45° down-right.
    const dir = 0.7071; // cos/sin 45°
    canvas.drawLine(
      c + const Offset(dir, dir) * (r + 2),
      c + const Offset(dir, dir) * (r + size.height * 0.16),
      pen(yellow, 1.0, 4.0),
    );
    _glyph(
      canvas,
      '₴',
      c,
      color: ink.withValues(alpha: 0.75),
      fontSize: r * 1.1,
      weight: FontWeight.w700,
    );

    // Auto parts: a gear on the left, a hex nut top-right.
    final part = pen(yellow, 0.9, 1.8);
    final gearC = Offset(size.width * 0.16, size.height * 0.58);
    final gearR = size.height * 0.16;
    canvas.drawCircle(gearC, gearR, part);
    canvas.drawCircle(gearC, gearR * 0.4, part);
    for (var i = 0; i < 8; i++) {
      final ang = i * math.pi / 4;
      final d = Offset(math.cos(ang), math.sin(ang));
      canvas.drawLine(
        gearC + d * gearR,
        gearC + d * (gearR + 5),
        pen(yellow, 0.9, 2.6),
      );
    }

    final nutC = Offset(size.width * 0.87, size.height * 0.26);
    const nutR = 11.0;
    final hex = Path();
    for (var i = 0; i < 6; i++) {
      final ang = math.pi / 6 + i * math.pi / 3;
      final p = nutC + Offset(math.cos(ang), math.sin(ang)) * nutR;
      i == 0 ? hex.moveTo(p.dx, p.dy) : hex.lineTo(p.dx, p.dy);
    }
    hex.close();
    canvas.drawPath(hex, part);
    canvas.drawCircle(nutC, nutR * 0.5, part);

    // Currency glyphs floating on the grid, faint.
    final floating = yellow.withValues(alpha: 0.55);
    _glyph(
      canvas,
      '\$',
      Offset(size.width * 0.29, size.height * 0.24),
      color: floating,
      fontSize: 16,
    );
    _glyph(
      canvas,
      '€',
      Offset(size.width * 0.40, size.height * 0.78),
      color: floating,
      fontSize: 13,
    );
    _glyph(
      canvas,
      '\$',
      Offset(size.width * 0.90, size.height * 0.68),
      color: floating,
      fontSize: 12,
    );
  }

  @override
  bool shouldRepaint(covariant _BlueprintHeroPainter oldDelegate) =>
      oldDelegate.ink != ink || oldDelegate.yellow != yellow;
}
