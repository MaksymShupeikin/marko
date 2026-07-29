String formatMoney(
  num value, {
  required String currency,
  num? priceTick,
  int? fractionDigits,
}) {
  final amount = formatDecimalAmount(
    value,
    priceTick: priceTick,
    fractionDigits: fractionDigits,
  );
  return '$amount ${currency.trim().toUpperCase()}';
}

String formatDecimalAmount(num value, {num? priceTick, int? fractionDigits}) {
  final amount = _ScaledInteger.tryParse(value.toString());
  final tick = priceTick == null
      ? null
      : _ScaledInteger.tryParse(priceTick.toString());
  if (amount == null || (tick != null && tick.units <= BigInt.zero)) {
    return value.toStringAsFixed(fractionDigits ?? 2);
  }

  final rounded = tick == null ? amount : amount.roundToMultiple(tick);
  final digits = fractionDigits ?? tick?.scale ?? 2;
  return rounded.toFixed(digits);
}

int decimalScale(Object? rawValue, {int fallback = 2}) {
  if (rawValue == null) return fallback;
  final parsed = _ScaledInteger.tryParse(rawValue.toString());
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

class _ScaledInteger {
  const _ScaledInteger(this.units, this.scale);

  final BigInt units;
  final int scale;

  static final RegExp _pattern = RegExp(
    r'^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$',
  );

  static _ScaledInteger? tryParse(String rawValue) {
    final match = _pattern.firstMatch(rawValue.trim());
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
    return _ScaledInteger(units, scale);
  }

  _ScaledInteger roundToMultiple(_ScaledInteger multiple) {
    final commonScale = scale > multiple.scale ? scale : multiple.scale;
    final amountUnits = units * _pow10(commonScale - scale);
    final multipleUnits =
        multiple.units.abs() * _pow10(commonScale - multiple.scale);
    final absolute = amountUnits.abs();
    var quotient = absolute ~/ multipleUnits;
    final remainder = absolute.remainder(multipleUnits);
    if (remainder * BigInt.two >= multipleUnits) quotient += BigInt.one;
    final rounded = quotient * multipleUnits;
    return _ScaledInteger(
      amountUnits.isNegative ? -rounded : rounded,
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

  static BigInt _pow10(int exponent) => BigInt.from(10).pow(exponent);
}
