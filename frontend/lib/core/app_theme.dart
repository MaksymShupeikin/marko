import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Spacing scale from the Marko design system (4px rhythm).
abstract final class MarkoSpace {
  static const xxs = 2.0;
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 20.0;
  static const xxl = 24.0;
  static const xxxl = 32.0;
  static const huge = 48.0;
}

/// One content column: the app bar and the page share these so nothing sits
/// on a different vertical line.
abstract final class MarkoLayout {
  static const contentMaxWidth = 1240.0;
  static const gutter = MarkoSpace.xxl;
  static const appBarHeight = 60.0;

  /// Every text field and button in the app is exactly this tall.
  static const fieldHeight = 38.0;

  /// A finger is not a mouse pointer: touch layouts get the 48px minimum.
  static const touchFieldHeight = 48.0;

  /// Same phone breakpoint as [MarkoModal].
  static double fieldHeightOf(BuildContext context) =>
      MediaQuery.sizeOf(context).width < 700 ? touchFieldHeight : fieldHeight;

  /// Body/label text inside those controls, scaled with them.
  static double fieldFontSizeOf(BuildContext context) =>
      MediaQuery.sizeOf(context).width < 700 ? 15.0 : 13.5;
}

/// Corner radii. Nothing in the product invents its own value.
abstract final class MarkoRadius {
  static const xs = 4.0; // hotkeys, tiny tags
  static const sm = 6.0; // inputs, chips, segmented pills
  static const md = 8.0; // buttons, toolbars
  static const lg = 10.0; // feature cards, dropzone
  static const xl = 14.0; // main surfaces, modals
}

/// Stacked crisp offsets instead of Material blur clouds.
abstract final class MarkoShadow {
  static const card = [
    BoxShadow(color: Color(0x0A000000), blurRadius: 2, offset: Offset(0, 1)),
  ];
  static const hover = [
    BoxShadow(
      color: Color(0x14000000),
      blurRadius: 12,
      spreadRadius: -2,
      offset: Offset(0, 4),
    ),
  ];
  static const overlay = [
    BoxShadow(
      color: Color(0x1F000000),
      blurRadius: 24,
      spreadRadius: -4,
      offset: Offset(0, 8),
    ),
  ];
  static const segmentedItem = [
    BoxShadow(color: Color(0x0F000000), blurRadius: 2, offset: Offset(0, 1)),
  ];
}

/// Technical layer: OEM codes, prices and hotkeys are always monospaced.
abstract final class MarkoType {
  static const _mono = 'Geist Mono';
  static const _monoFallback = [
    'JetBrains Mono',
    'SF Mono',
    'Menlo',
    'Consolas',
    'monospace',
  ];

  static const oem = TextStyle(
    fontFamily: _mono,
    fontFamilyFallback: _monoFallback,
    fontSize: 13,
    height: 1.2,
    fontWeight: FontWeight.w600,
    letterSpacing: 0.2,
  );

  static const price = TextStyle(
    fontFamily: _mono,
    fontFamilyFallback: _monoFallback,
    fontSize: 15,
    height: 1.2,
    fontWeight: FontWeight.w600,
    fontFeatures: [FontFeature.tabularFigures()],
  );

  static const caption = TextStyle(
    fontFamily: _mono,
    fontFamilyFallback: _monoFallback,
    fontSize: 11.5,
    height: 1.3,
    fontWeight: FontWeight.w500,
    letterSpacing: 0.3,
  );

  static const hotkey = TextStyle(
    fontFamily: _mono,
    fontFamilyFallback: _monoFallback,
    fontSize: 11,
    height: 1.0,
    fontWeight: FontWeight.w500,
  );
}

@immutable
class MarkoTheme extends ThemeExtension<MarkoTheme> {
  const MarkoTheme({
    required this.canvas,
    required this.surface,
    required this.surfaceMuted,
    required this.ink,
    required this.muted,
    required this.faint,
    required this.border,
    required this.borderStrong,
    required this.brand,
    required this.brandSoft,
    required this.positive,
    required this.positiveSoft,
    required this.negative,
    required this.negativeSoft,
    required this.warning,
    required this.warningSoft,
    required this.inverseSurface,
    required this.onInverse,
    required this.excelAccent,
    required this.promAccent,
    required this.oemAccent,
    required this.panelRadius,
  });

  static const light = MarkoTheme(
    canvas: Color(0xFFF8FAFC),
    surface: Color(0xFFFFFFFF),
    surfaceMuted: Color(0xFFF1F5F9),
    ink: Color(0xFF0C0C0E),
    muted: Color(0xFF475569),
    faint: Color(0xFF94A3B8),
    border: Color(0xFFE2E8F0),
    borderStrong: Color(0xFFCBD5E1),
    brand: Color(0xFF0070F3),
    brandSoft: Color(0xFFEFF6FF),
    positive: Color(0xFF10B981),
    positiveSoft: Color(0xFFECFDF5),
    negative: Color(0xFFEF4444),
    negativeSoft: Color(0xFFFEF2F2),
    warning: Color(0xFFF59E0B),
    warningSoft: Color(0xFFFFFBEB),
    inverseSurface: Color(0xFF0C0C0E),
    onInverse: Color(0xFFFFFFFF),
    excelAccent: Color(0xFF21A366),
    promAccent: Color(0xFF7C3AED),
    oemAccent: Color(0xFF0070F3),
    panelRadius: MarkoRadius.xl,
  );

  /// Same semantics on a black canvas: hairlines become translucent white,
  /// the soft tints become low-alpha washes of their own hue.
  static const dark = MarkoTheme(
    canvas: Color(0xFF09090B),
    surface: Color(0xFF0F0F12),
    surfaceMuted: Color(0xFF18181B),
    ink: Color(0xFFF8FAFC),
    muted: Color(0xD9F8FAFC),
    faint: Color(0xFF94A3B8),
    border: Color(0x14FFFFFF),
    borderStrong: Color(0x29FFFFFF),
    brand: Color(0xFF3B93FF),
    brandSoft: Color(0x260070F3),
    positive: Color(0xFF10B981),
    positiveSoft: Color(0x2610B981),
    negative: Color(0xFFF87171),
    negativeSoft: Color(0x26EF4444),
    warning: Color(0xFFFBBF24),
    warningSoft: Color(0x26F59E0B),
    inverseSurface: Color(0xFF18181B),
    onInverse: Color(0xFFF8FAFC),
    excelAccent: Color(0xFF34D399),
    promAccent: Color(0xFFA855F7),
    oemAccent: Color(0xFF3B93FF),
    panelRadius: MarkoRadius.xl,
  );

  final Color canvas;
  final Color surface;
  final Color surfaceMuted;
  final Color ink;

  /// Secondary text.
  final Color muted;

  /// Captions, meta labels, inactive icons.
  final Color faint;
  final Color border;
  final Color borderStrong;
  final Color brand;
  final Color brandSoft;
  final Color positive;
  final Color positiveSoft;
  final Color negative;
  final Color negativeSoft;
  final Color warning;
  final Color warningSoft;

  /// Deliberately opposite surface: primary buttons, tooltips, hero panels.
  final Color inverseSurface;
  final Color onInverse;

  /// Integration accents: the neon wash and logo tint of each source tile.
  final Color excelAccent;
  final Color promAccent;
  final Color oemAccent;
  final double panelRadius;

  static MarkoTheme of(BuildContext context) {
    return Theme.of(context).extension<MarkoTheme>() ?? light;
  }

  @override
  MarkoTheme copyWith({
    Color? canvas,
    Color? surface,
    Color? surfaceMuted,
    Color? ink,
    Color? muted,
    Color? faint,
    Color? border,
    Color? borderStrong,
    Color? brand,
    Color? brandSoft,
    Color? positive,
    Color? positiveSoft,
    Color? negative,
    Color? negativeSoft,
    Color? warning,
    Color? warningSoft,
    Color? inverseSurface,
    Color? onInverse,
    Color? excelAccent,
    Color? promAccent,
    Color? oemAccent,
    double? panelRadius,
  }) {
    return MarkoTheme(
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceMuted: surfaceMuted ?? this.surfaceMuted,
      ink: ink ?? this.ink,
      muted: muted ?? this.muted,
      faint: faint ?? this.faint,
      border: border ?? this.border,
      borderStrong: borderStrong ?? this.borderStrong,
      brand: brand ?? this.brand,
      brandSoft: brandSoft ?? this.brandSoft,
      positive: positive ?? this.positive,
      positiveSoft: positiveSoft ?? this.positiveSoft,
      negative: negative ?? this.negative,
      negativeSoft: negativeSoft ?? this.negativeSoft,
      warning: warning ?? this.warning,
      warningSoft: warningSoft ?? this.warningSoft,
      inverseSurface: inverseSurface ?? this.inverseSurface,
      onInverse: onInverse ?? this.onInverse,
      excelAccent: excelAccent ?? this.excelAccent,
      promAccent: promAccent ?? this.promAccent,
      oemAccent: oemAccent ?? this.oemAccent,
      panelRadius: panelRadius ?? this.panelRadius,
    );
  }

  @override
  MarkoTheme lerp(covariant MarkoTheme? other, double t) {
    if (other == null) return this;
    return MarkoTheme(
      canvas: Color.lerp(canvas, other.canvas, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceMuted: Color.lerp(surfaceMuted, other.surfaceMuted, t)!,
      ink: Color.lerp(ink, other.ink, t)!,
      muted: Color.lerp(muted, other.muted, t)!,
      faint: Color.lerp(faint, other.faint, t)!,
      border: Color.lerp(border, other.border, t)!,
      borderStrong: Color.lerp(borderStrong, other.borderStrong, t)!,
      brand: Color.lerp(brand, other.brand, t)!,
      brandSoft: Color.lerp(brandSoft, other.brandSoft, t)!,
      positive: Color.lerp(positive, other.positive, t)!,
      positiveSoft: Color.lerp(positiveSoft, other.positiveSoft, t)!,
      negative: Color.lerp(negative, other.negative, t)!,
      negativeSoft: Color.lerp(negativeSoft, other.negativeSoft, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      warningSoft: Color.lerp(warningSoft, other.warningSoft, t)!,
      inverseSurface: Color.lerp(inverseSurface, other.inverseSurface, t)!,
      onInverse: Color.lerp(onInverse, other.onInverse, t)!,
      excelAccent: Color.lerp(excelAccent, other.excelAccent, t)!,
      promAccent: Color.lerp(promAccent, other.promAccent, t)!,
      oemAccent: Color.lerp(oemAccent, other.oemAccent, t)!,
      panelRadius: panelRadius + (other.panelRadius - panelRadius) * t,
    );
  }
}

abstract final class AppTheme {
  static ThemeData get light => _build(MarkoTheme.light, Brightness.light);

  static ThemeData get dark => _build(MarkoTheme.dark, Brightness.dark);

  /// `MaterialApp.builder`: the theme itself is built without a context, so the
  /// touch-sized minimums are grafted on here, where MediaQuery exists.
  static Widget touchTargets(BuildContext context, Widget? child) {
    final height = MarkoLayout.fieldHeightOf(context);
    if (height == MarkoLayout.fieldHeight) return child!;
    final theme = Theme.of(context);
    ButtonStyle? grow(ButtonStyle? style, Size size) =>
        style?.copyWith(minimumSize: WidgetStatePropertyAll(size));
    final wide = Size(0, height);
    return Theme(
      data: theme.copyWith(
        filledButtonTheme: FilledButtonThemeData(
          style: grow(theme.filledButtonTheme.style, wide),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: grow(theme.outlinedButtonTheme.style, wide),
        ),
        textButtonTheme: TextButtonThemeData(
          style: grow(theme.textButtonTheme.style, wide),
        ),
        iconButtonTheme: IconButtonThemeData(
          style: grow(theme.iconButtonTheme.style, Size.square(height)),
        ),
      ),
      child: child!,
    );
  }

  static ThemeData _build(MarkoTheme colors, Brightness brightness) {
    final colorScheme = ColorScheme(
      brightness: brightness,
      primary: colors.brand,
      onPrimary: Colors.white,
      primaryContainer: colors.brandSoft,
      onPrimaryContainer: colors.ink,
      secondary: colors.ink,
      onSecondary: colors.canvas,
      error: colors.negative,
      onError: Colors.white,
      errorContainer: colors.negativeSoft,
      onErrorContainer: colors.negative,
      surface: colors.surface,
      onSurface: colors.ink,
      outline: colors.border,
      outlineVariant: colors.border,
      inverseSurface: colors.inverseSurface,
      onInverseSurface: colors.onInverse,
    );

    final textTheme = TextTheme(
      displaySmall: TextStyle(
        color: colors.ink,
        fontSize: 32,
        height: 1.15,
        fontWeight: FontWeight.w600,
        letterSpacing: -1.2,
      ),
      headlineMedium: TextStyle(
        color: colors.ink,
        fontSize: 24,
        height: 1.25,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.7,
      ),
      headlineSmall: TextStyle(
        color: colors.ink,
        fontSize: 20,
        height: 1.3,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.45,
      ),
      titleLarge: TextStyle(
        color: colors.ink,
        fontSize: 18,
        height: 1.35,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.3,
      ),
      titleMedium: TextStyle(
        color: colors.ink,
        fontSize: 15,
        height: 1.4,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.15,
      ),
      bodyLarge: TextStyle(
        color: colors.ink,
        fontSize: 16,
        height: 1.5,
        fontWeight: FontWeight.w400,
      ),
      bodyMedium: TextStyle(
        color: colors.ink,
        fontSize: 14,
        height: 1.45,
        fontWeight: FontWeight.w400,
      ),
      bodySmall: TextStyle(
        color: colors.muted,
        fontSize: 12.5,
        height: 1.4,
        fontWeight: FontWeight.w400,
      ),
      labelLarge: TextStyle(
        color: colors.ink,
        fontSize: 13.5,
        height: 1.2,
        fontWeight: FontWeight.w500,
      ),
      labelMedium: TextStyle(
        color: colors.faint,
        fontSize: 12.5,
        height: 1.2,
        fontWeight: FontWeight.w500,
        letterSpacing: 0.1,
      ),
    );

    final inputBorder = OutlineInputBorder(
      borderRadius: BorderRadius.circular(MarkoRadius.md),
      borderSide: BorderSide(color: colors.border),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colorScheme,
      fontFamily: 'Geist',
      fontFamilyFallback: const [
        'Inter',
        'SF Pro Text',
        'Segoe UI',
        'Roboto',
        'system-ui',
      ],
      scaffoldBackgroundColor: colors.canvas,
      canvasColor: colors.canvas,
      focusColor: colors.brand.withValues(alpha: 0.12),
      hoverColor: colors.ink.withValues(alpha: 0.04),
      splashFactory: NoSplash.splashFactory,
      extensions: [colors],
      textTheme: textTheme,
      primaryTextTheme: textTheme,
      appBarTheme: AppBarTheme(
        elevation: 0,
        scrolledUnderElevation: 0,
        backgroundColor: colors.canvas,
        foregroundColor: colors.ink,
        centerTitle: false,
        titleTextStyle: textTheme.titleLarge,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        color: colors.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(colors.panelRadius),
          side: BorderSide(color: colors.border),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colors.surface,
        isDense: true,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: MarkoSpace.md,
          vertical: 9.5,
        ),
        hintStyle: TextStyle(color: colors.faint, fontSize: 13.5),
        labelStyle: TextStyle(color: colors.muted, fontSize: 13.5),
        floatingLabelStyle: TextStyle(
          color: colors.brand,
          fontSize: 11.5,
          fontWeight: FontWeight.w500,
        ),
        prefixStyle: TextStyle(color: colors.faint, fontSize: 13.5),
        prefixIconColor: colors.faint,
        suffixIconColor: colors.faint,
        border: inputBorder,
        enabledBorder: inputBorder,
        disabledBorder: inputBorder.copyWith(
          borderSide: BorderSide(color: colors.border.withValues(alpha: 0.7)),
        ),
        focusedBorder: inputBorder.copyWith(
          borderSide: BorderSide(color: colors.brand, width: 1.4),
        ),
        errorBorder: inputBorder.copyWith(
          borderSide: BorderSide(color: colors.negative),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 38),
          padding: const EdgeInsets.symmetric(horizontal: MarkoSpace.lg),
          elevation: 0,
          backgroundColor: colors.inverseSurface,
          foregroundColor: colors.onInverse,
          disabledBackgroundColor: colors.border,
          disabledForegroundColor: colors.faint,
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(MarkoRadius.md),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 38),
          padding: const EdgeInsets.symmetric(horizontal: MarkoSpace.lg),
          backgroundColor: colors.surface,
          foregroundColor: colors.ink,
          side: BorderSide(color: colors.border),
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(MarkoRadius.md),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: colors.brand,
          padding: const EdgeInsets.symmetric(
            horizontal: MarkoSpace.sm,
            vertical: MarkoSpace.sm,
          ),
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(MarkoRadius.sm),
          ),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          foregroundColor: colors.muted,
          hoverColor: colors.surfaceMuted,
          highlightColor: Colors.transparent,
          minimumSize: const Size.square(36),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(MarkoRadius.md),
          ),
        ),
      ),
      dividerTheme: DividerThemeData(
        color: colors.border,
        thickness: 1,
        space: 1,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: colors.brand,
        linearTrackColor: colors.surfaceMuted,
        circularTrackColor: colors.surfaceMuted,
        linearMinHeight: 3,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: colors.surface,
        selectedColor: colors.brandSoft,
        side: BorderSide(color: colors.border),
        padding: const EdgeInsets.symmetric(
          horizontal: MarkoSpace.sm,
          vertical: MarkoSpace.xs,
        ),
        labelStyle: textTheme.labelLarge,
        secondaryLabelStyle: textTheme.labelLarge,
        showCheckmark: false,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(MarkoRadius.md),
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(
        elevation: 8,
        shadowColor: Colors.black.withValues(alpha: 0.16),
        color: colors.surface,
        surfaceTintColor: Colors.transparent,
        textStyle: textTheme.bodyMedium?.copyWith(
          color: colors.ink,
          fontSize: 13.5,
        ),
        menuPadding: const EdgeInsets.symmetric(
          vertical: MarkoSpace.xs,
          horizontal: MarkoSpace.xs,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(MarkoRadius.md),
          side: BorderSide(color: colors.border),
        ),
      ),
      menuTheme: MenuThemeData(
        style: MenuStyle(
          backgroundColor: WidgetStatePropertyAll(colors.surface),
          elevation: const WidgetStatePropertyAll(10),
          shadowColor: WidgetStatePropertyAll(
            Colors.black.withValues(alpha: 0.16),
          ),
          surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
          shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(MarkoRadius.md),
              side: BorderSide(color: colors.border),
            ),
          ),
          padding: const WidgetStatePropertyAll(EdgeInsets.all(MarkoSpace.xxs)),
        ),
      ),
      menuButtonTheme: MenuButtonThemeData(
        style: ButtonStyle(
          shape: WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(MarkoRadius.sm),
            ),
          ),
          overlayColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.hovered) ||
                states.contains(WidgetState.focused)) {
              return colors.surfaceMuted;
            }
            if (states.contains(WidgetState.pressed)) {
              return colors.border;
            }
            return Colors.transparent;
          }),
        ),
      ),
      dialogTheme: DialogThemeData(
        elevation: 0,
        backgroundColor: colors.surface,
        surfaceTintColor: Colors.transparent,
        // Always a dark scrim: the light theme's ink washes the page out.
        barrierColor: Colors.black.withValues(alpha: 0.45),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(colors.panelRadius),
          side: BorderSide(color: colors.border),
        ),
      ),
      drawerTheme: DrawerThemeData(
        elevation: 0,
        backgroundColor: colors.canvas,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(),
      ),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(
          color: colors.inverseSurface,
          borderRadius: BorderRadius.circular(MarkoRadius.sm),
        ),
        textStyle: TextStyle(color: colors.onInverse, fontSize: 12),
      ),
      scrollbarTheme: ScrollbarThemeData(
        thickness: const WidgetStatePropertyAll(6),
        radius: const Radius.circular(10),
        thumbColor: WidgetStatePropertyAll(colors.faint.withValues(alpha: 0.5)),
      ),
    );
  }
}

const _themeModeKey = 'marko_theme_mode';

/// Light/dark selection with persistence across reloads.
class ThemeModeController extends Notifier<ThemeMode> {
  @override
  ThemeMode build() {
    _loadPersistedTheme();
    return ThemeMode.system;
  }

  Future<void> _loadPersistedTheme() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(_themeModeKey);
      if (saved == 'light') {
        state = ThemeMode.light;
      } else if (saved == 'dark') {
        state = ThemeMode.dark;
      }
    } catch (_) {
      // Best-effort cache read.
    }
  }

  void toggle(Brightness current) {
    final next = current == Brightness.dark ? ThemeMode.light : ThemeMode.dark;
    state = next;
    _persistTheme(next);
  }

  Future<void> _persistTheme(ThemeMode mode) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _themeModeKey,
        mode == ThemeMode.dark ? 'dark' : 'light',
      );
    } catch (_) {
      // Best-effort cache write.
    }
  }
}

final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(
  ThemeModeController.new,
);
