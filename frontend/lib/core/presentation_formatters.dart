String formatMoney(
  Object value, {
  required String currency,
  Object? priceTick,
  int? fractionDigits,
}) {
  final amount = formatDecimalAmount(
    value,
    priceTick: priceTick,
    fractionDigits: fractionDigits,
  );
  return '$amount ${currency.trim().toUpperCase()}';
}

String formatLocalDateTime(DateTime value) {
  final local = value.toLocal();
  String twoDigits(int number) => number.toString().padLeft(2, '0');
  return '${twoDigits(local.day)}.${twoDigits(local.month)}.${local.year} '
      '${twoDigits(local.hour)}:${twoDigits(local.minute)}';
}

String formatDecimalAmount(
  Object value, {
  Object? priceTick,
  int? fractionDigits,
}) {
  final amount = DecimalValue.tryParse(value);
  final tick = DecimalValue.tryParse(priceTick);
  if (amount == null || (tick != null && tick.units <= BigInt.zero)) {
    return value is num
        ? value.toStringAsFixed(fractionDigits ?? 2)
        : value.toString();
  }

  final rounded = tick == null ? amount : amount.roundToMultiple(tick);
  final digits = fractionDigits ?? tick?.scale ?? 2;
  return rounded.toFixed(digits);
}

int decimalScale(Object? rawValue, {int fallback = 2}) {
  if (rawValue == null) return fallback;
  final parsed = DecimalValue.tryParse(rawValue);
  return parsed?.scale ?? fallback;
}

String summarizeLimited(
  Iterable<String> values, {
  required int limit,
  required String separator,
  required String Function(int hiddenCount) overflowLabel,
}) {
  final items = values.toList(growable: false);
  final visible = items.take(limit).toList();
  final hidden = items.length - visible.length;
  if (hidden > 0) visible.add(overflowLabel(hidden));
  return visible.join(separator);
}

/// Exact base-10 value used for prices, ticks, and money serialization.
///
/// Parsing never passes through binary floating point. Division is exposed as
/// [ratioTo] so an approximate boundary is explicit and limited to ratios.
class DecimalValue implements Comparable<DecimalValue> {
  const DecimalValue._(this.units, this.scale);

  final BigInt units;
  final int scale;

  static final RegExp _pattern = RegExp(
    r'^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$',
  );

  factory DecimalValue.parse(String rawValue) {
    final value = tryParse(rawValue);
    if (value == null) {
      throw FormatException('Invalid decimal value: $rawValue');
    }
    return value;
  }

  factory DecimalValue.from(Object value) {
    final parsed = tryParse(value);
    if (parsed == null) {
      throw FormatException('Invalid decimal value: $value');
    }
    return parsed;
  }

  static DecimalValue? tryParse(Object? rawValue) {
    if (rawValue == null) return null;
    if (rawValue is DecimalValue) return rawValue;
    final match = _pattern.firstMatch(rawValue.toString().trim());
    if (match == null) return null;
    final sign = match.group(1) == '-' ? -1 : 1;
    final whole = match.group(2)!;
    final fraction = match.group(3) ?? '';
    final exponent = int.tryParse(match.group(4) ?? '0') ?? 0;
    var scale = fraction.length - exponent;
    var units = BigInt.parse('$whole$fraction') * BigInt.from(sign);
    if (scale < 0) {
      units *= _pow10(-scale);
      scale = 0;
    }
    return DecimalValue._(units, scale);
  }

  bool get isZero => units == BigInt.zero;

  bool get isPositive => units > BigInt.zero;

  DecimalValue abs() => units.isNegative ? DecimalValue._(-units, scale) : this;

  DecimalValue roundToMultiple(DecimalValue multiple) {
    final commonScale = scale > multiple.scale ? scale : multiple.scale;
    final amountUnits = units * _pow10(commonScale - scale);
    final multipleUnits =
        multiple.units.abs() * _pow10(commonScale - multiple.scale);
    final absolute = amountUnits.abs();
    var quotient = absolute ~/ multipleUnits;
    final remainder = absolute.remainder(multipleUnits);
    if (remainder * BigInt.two >= multipleUnits) quotient += BigInt.one;
    final rounded = quotient * multipleUnits;
    return DecimalValue._(
      amountUnits.isNegative ? -rounded : rounded,
      commonScale,
    );
  }

  DecimalValue operator +(Object other) {
    final pair = _aligned(other);
    return DecimalValue._(pair.$1 + pair.$2, pair.$3);
  }

  DecimalValue operator -(Object other) {
    final pair = _aligned(other);
    return DecimalValue._(pair.$1 - pair.$2, pair.$3);
  }

  DecimalValue operator *(Object other) {
    final right = DecimalValue.from(other);
    return DecimalValue._(units * right.units, scale + right.scale);
  }

  DecimalValue operator -() => DecimalValue._(-units, scale);

  double ratioTo(Object other) {
    final denominator = DecimalValue.from(other);
    if (denominator.isZero) {
      throw UnsupportedError('Cannot divide by a zero DecimalValue');
    }
    return toDouble() / denominator.toDouble();
  }

  double toDouble() => double.parse(toString());

  bool operator <(Object other) => compareTo(DecimalValue.from(other)) < 0;

  bool operator <=(Object other) => compareTo(DecimalValue.from(other)) <= 0;

  bool operator >(Object other) => compareTo(DecimalValue.from(other)) > 0;

  bool operator >=(Object other) => compareTo(DecimalValue.from(other)) >= 0;

  @override
  int compareTo(DecimalValue other) {
    final commonScale = scale > other.scale ? scale : other.scale;
    final left = units * _pow10(commonScale - scale);
    final right = other.units * _pow10(commonScale - other.scale);
    return left.compareTo(right);
  }

  (BigInt, BigInt, int) _aligned(Object other) {
    final right = DecimalValue.from(other);
    final commonScale = scale > right.scale ? scale : right.scale;
    return (
      units * _pow10(commonScale - scale),
      right.units * _pow10(commonScale - right.scale),
      commonScale,
    );
  }

  String toFixed(int fractionDigits) {
    final safeDigits = fractionDigits < 0 ? 0 : fractionDigits;
    var outputUnits = units;
    if (scale < safeDigits) {
      outputUnits *= _pow10(safeDigits - scale);
    } else if (scale > safeDigits) {
      final divisor = _pow10(scale - safeDigits);
      final absolute = outputUnits.abs();
      var quotient = absolute ~/ divisor;
      if (absolute.remainder(divisor) * BigInt.two >= divisor) {
        quotient += BigInt.one;
      }
      outputUnits = outputUnits.isNegative ? -quotient : quotient;
    }

    final negative = outputUnits.isNegative;
    var digits = outputUnits.abs().toString();
    if (safeDigits > 0) {
      digits = digits.padLeft(safeDigits + 1, '0');
      final split = digits.length - safeDigits;
      digits = '${digits.substring(0, split)}.${digits.substring(split)}';
    }
    return negative ? '-$digits' : digits;
  }

  String toStringAsFixed(int fractionDigits) => toFixed(fractionDigits);

  @override
  String toString() {
    final negative = units.isNegative;
    var digits = units.abs().toString();
    if (scale > 0) {
      digits = digits.padLeft(scale + 1, '0');
      final split = digits.length - scale;
      digits = '${digits.substring(0, split)}.${digits.substring(split)}';
    }
    return negative ? '-$digits' : digits;
  }

  String toJson() => toString();

  @override
  bool operator ==(Object other) {
    final parsed = tryParse(other);
    return parsed != null && compareTo(parsed) == 0;
  }

  @override
  int get hashCode {
    var canonicalUnits = units;
    var canonicalScale = scale;
    while (canonicalScale > 0 &&
        canonicalUnits.remainder(BigInt.from(10)) == BigInt.zero) {
      canonicalUnits ~/= BigInt.from(10);
      canonicalScale -= 1;
    }
    return Object.hash(canonicalUnits, canonicalScale);
  }

  static BigInt _pow10(int exponent) => BigInt.from(10).pow(exponent);
}
