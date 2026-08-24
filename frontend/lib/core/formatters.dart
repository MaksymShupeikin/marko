/// Formats a decimal price with space grouping and optional decimals (e.g. 1 250 or 1 250.50).
String formatPriceNumber(double price) {
  final isWhole = price.truncateToDouble() == price;
  final fixed = price.toStringAsFixed(isWhole ? 0 : 2);
  final parts = fixed.split('.');
  final whole = parts[0].replaceAllMapped(
    RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
    (m) => '${m[1]} ',
  );
  return parts.length > 1 ? '$whole.${parts[1]}' : whole;
}

/// Parses user price input back into a number: tolerates the space grouping
/// [ThousandsPriceInputFormatter] inserts and a comma decimal separator.
/// Empty or unparsable input means no value.
double? parsePrice(String value) {
  final normalized = value.trim().replaceAll(' ', '').replaceAll(',', '.');
  return normalized.isEmpty ? null : double.tryParse(normalized);
}

/// Normalizes currency strings into standard symbols (UAH -> ₴, USD -> $, EUR -> €).
String formatCurrency(String currency) {
  switch (currency.toUpperCase()) {
    case 'UAH':
    case 'ГРН':
      return '₴';
    case 'USD':
      return '\$';
    case 'EUR':
      return '€';
    default:
      return currency;
  }
}

const _ukrainianMonthsGenitive = [
  'січня',
  'лютого',
  'березня',
  'квітня',
  'травня',
  'червня',
  'липня',
  'серпня',
  'вересня',
  'жовтня',
  'листопада',
  'грудня',
];

/// Formats a DateTime in Ukrainian style: e.g. "21 вересня 2026 о 12:36".
String formatDateTimeUk(DateTime dateTime) {
  final local = dateTime.toLocal();
  final day = local.day;
  final month = _ukrainianMonthsGenitive[local.month - 1];
  final year = local.year;
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '$day $month $year о $hour:$minute';
}
