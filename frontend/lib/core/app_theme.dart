import 'package:flutter/material.dart';

@immutable
class MarkoTheme extends ThemeExtension<MarkoTheme> {
  const MarkoTheme({
    required this.canvas,
    required this.surface,
    required this.surfaceMuted,
    required this.ink,
    required this.muted,
    required this.border,
    required this.brand,
    required this.brandSoft,
    required this.positive,
    required this.positiveSoft,
    required this.negative,
    required this.negativeSoft,
    required this.warning,
    required this.warningSoft,
    required this.panelRadius,
  });

  static const light = MarkoTheme(
    canvas: Color(0xFFF6F7F4),
    surface: Color(0xFFFFFFFF),
    surfaceMuted: Color(0xFFF0F2EF),
    ink: Color(0xFF151817),
    muted: Color(0xFF68706C),
    border: Color(0xFFE1E5E1),
    brand: Color(0xFF3157D5),
    brandSoft: Color(0xFFEBEFFF),
    positive: Color(0xFF167A55),
    positiveSoft: Color(0xFFE7F4EE),
    negative: Color(0xFFC44F4F),
    negativeSoft: Color(0xFFFBECEC),
    warning: Color(0xFFA86D16),
    warningSoft: Color(0xFFFFF3DC),
    panelRadius: 12,
  );

  final Color canvas;
  final Color surface;
  final Color surfaceMuted;
  final Color ink;
  final Color muted;
  final Color border;
  final Color brand;
  final Color brandSoft;
  final Color positive;
  final Color positiveSoft;
  final Color negative;
  final Color negativeSoft;
  final Color warning;
  final Color warningSoft;
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
    Color? border,
    Color? brand,
    Color? brandSoft,
    Color? positive,
    Color? positiveSoft,
    Color? negative,
    Color? negativeSoft,
    Color? warning,
    Color? warningSoft,
    double? panelRadius,
  }) {
    return MarkoTheme(
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceMuted: surfaceMuted ?? this.surfaceMuted,
      ink: ink ?? this.ink,
      muted: muted ?? this.muted,
      border: border ?? this.border,
      brand: brand ?? this.brand,
      brandSoft: brandSoft ?? this.brandSoft,
      positive: positive ?? this.positive,
      positiveSoft: positiveSoft ?? this.positiveSoft,
      negative: negative ?? this.negative,
      negativeSoft: negativeSoft ?? this.negativeSoft,
      warning: warning ?? this.warning,
      warningSoft: warningSoft ?? this.warningSoft,
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
      border: Color.lerp(border, other.border, t)!,
      brand: Color.lerp(brand, other.brand, t)!,
      brandSoft: Color.lerp(brandSoft, other.brandSoft, t)!,
      positive: Color.lerp(positive, other.positive, t)!,
      positiveSoft: Color.lerp(positiveSoft, other.positiveSoft, t)!,
      negative: Color.lerp(negative, other.negative, t)!,
      negativeSoft: Color.lerp(negativeSoft, other.negativeSoft, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      warningSoft: Color.lerp(warningSoft, other.warningSoft, t)!,
      panelRadius: panelRadius + (other.panelRadius - panelRadius) * t,
    );
  }
}

abstract final class AppTheme {
  static ThemeData get light {
    final colors = MarkoTheme.light;
    final colorScheme = ColorScheme.light(
      primary: colors.brand,
      onPrimary: Colors.white,
      primaryContainer: colors.brandSoft,
      onPrimaryContainer: colors.ink,
      secondary: colors.ink,
      onSecondary: Colors.white,
      error: colors.negative,
      onError: Colors.white,
      errorContainer: colors.negativeSoft,
      onErrorContainer: colors.negative,
      surface: colors.surface,
      onSurface: colors.ink,
      outline: colors.border,
      outlineVariant: colors.border,
    );

    final textTheme = TextTheme(
      displaySmall: TextStyle(
        color: colors.ink,
        fontSize: 36,
        height: 1.08,
        fontWeight: FontWeight.w600,
        letterSpacing: -1.2,
      ),
      headlineMedium: TextStyle(
        color: colors.ink,
        fontSize: 28,
        height: 1.15,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.7,
      ),
      headlineSmall: TextStyle(
        color: colors.ink,
        fontSize: 22,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.35,
      ),
      titleLarge: TextStyle(
        color: colors.ink,
        fontSize: 18,
        height: 1.3,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.15,
      ),
      titleMedium: TextStyle(
        color: colors.ink,
        fontSize: 15,
        height: 1.35,
        fontWeight: FontWeight.w600,
      ),
      bodyLarge: TextStyle(
        color: colors.ink,
        fontSize: 15,
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
        fontSize: 14,
        height: 1.2,
        fontWeight: FontWeight.w600,
      ),
      labelMedium: TextStyle(
        color: colors.muted,
        fontSize: 12,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.15,
      ),
    );

    final inputBorder = OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: BorderSide(color: colors.border),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: colorScheme,
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
        titleTextStyle: TextStyle(
          color: colors.ink,
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
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
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 14,
        ),
        hintStyle: TextStyle(color: colors.muted, fontSize: 14),
        labelStyle: TextStyle(color: colors.muted, fontSize: 14),
        floatingLabelStyle: TextStyle(
          color: colors.brand,
          fontSize: 13,
          fontWeight: FontWeight.w600,
        ),
        prefixIconColor: colors.muted,
        suffixIconColor: colors.muted,
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
          minimumSize: const Size(0, 44),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          elevation: 0,
          backgroundColor: colors.brand,
          foregroundColor: Colors.white,
          disabledBackgroundColor: colors.border,
          disabledForegroundColor: colors.muted,
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 44),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          foregroundColor: colors.ink,
          side: BorderSide(color: colors.border),
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: colors.brand,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          textStyle: textTheme.labelLarge,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          foregroundColor: colors.muted,
          hoverColor: colors.surfaceMuted,
          highlightColor: Colors.transparent,
          minimumSize: const Size.square(44),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
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
      ),
      chipTheme: ChipThemeData(
        backgroundColor: colors.surfaceMuted,
        selectedColor: colors.brandSoft,
        side: BorderSide.none,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        labelStyle: textTheme.labelMedium,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
      ),
      dialogTheme: DialogThemeData(
        elevation: 16,
        backgroundColor: colors.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(colors.panelRadius),
          side: BorderSide(color: colors.border),
        ),
      ),
      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(
          color: colors.ink,
          borderRadius: BorderRadius.circular(6),
        ),
        textStyle: const TextStyle(color: Colors.white, fontSize: 12),
      ),
      scrollbarTheme: ScrollbarThemeData(
        thickness: const WidgetStatePropertyAll(6),
        radius: const Radius.circular(10),
        thumbColor: WidgetStatePropertyAll(
          colors.muted.withValues(alpha: 0.35),
        ),
      ),
    );
  }
}
