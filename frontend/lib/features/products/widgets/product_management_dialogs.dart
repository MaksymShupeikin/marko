import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:heroicons/heroicons.dart';

import '../../../core/app_theme.dart';
import '../../../core/marko_ui.dart';
import '../../../core/widgets/marko_button.dart';
import '../../../core/widgets/marko_toast.dart';
import '../products_controller.dart';
import '../products_models.dart';

Future<void> showProductEditor(
  BuildContext context, {
  required StoreProduct product,
}) {
  return showMarkoModal(
    context,
    title: 'Редагувати товар',
    child: _ProductEditForm(product: product),
  );
}

Future<bool> confirmProductDeletion(
  BuildContext context, {
  required StoreProduct product,
}) async {
  return await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (context) => _DeleteProductDialog(product: product),
      ) ??
      false;
}

/// Asks before a bulk delete; the removal itself belongs to the caller, which
/// already knows which products are ticked.
Future<bool> confirmBulkProductDeletion(
  BuildContext context, {
  required int count,
}) async {
  final colors = MarkoTheme.of(context);
  return await showDialog<bool>(
        context: context,
        barrierDismissible: true,
        builder: (context) => AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(colors.panelRadius),
            side: BorderSide(color: colors.border),
          ),
          backgroundColor: colors.surface,
          surfaceTintColor: Colors.transparent,
          icon: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: colors.negative.withValues(alpha: 0.10),
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: HeroIcon(
              HeroIcons.trash,
              color: colors.negative,
              size: 22,
            ),
          ),
          title: Text(
            'Видалити товарів: $count?',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: 18,
                ),
          ),
          content: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: colors.surfaceMuted,
                    borderRadius: BorderRadius.circular(MarkoRadius.md),
                    border: Border.all(color: colors.border),
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 32,
                        height: 32,
                        decoration: BoxDecoration(
                          color: colors.negativeSoft,
                          shape: BoxShape.circle,
                          border: Border.all(
                            color: colors.negative.withValues(alpha: 0.24),
                          ),
                        ),
                        alignment: Alignment.center,
                        child: HeroIcon(
                          HeroIcons.archiveBox,
                          size: 16,
                          color: colors.negative,
                        ),
                      ),
                      const SizedBox(width: MarkoSpace.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Позначені товари',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(
                                    fontWeight: FontWeight.w600,
                                  ),
                            ),
                            Text(
                              'Кількість: $count',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: MarkoType.caption.copyWith(
                                color: colors.faint,
                                fontSize: 11.5,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: MarkoSpace.md),
                Text(
                  'Позначені товари зникнуть з каталогу. Наступна синхронізація не додасть їх знову.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colors.muted,
                      ),
                ),
              ],
            ),
          ),
          actionsPadding: const EdgeInsets.fromLTRB(
            MarkoSpace.lg,
            0,
            MarkoSpace.lg,
            MarkoSpace.lg,
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Скасувати'),
            ),
            MarkoButton.danger(
              label: 'Видалити',
              icon: HeroIcons.trash,
              onPressed: () => Navigator.of(context).pop(true),
            ),
          ],
        ),
      ) ??
      false;
}

class _ProductEditForm extends ConsumerStatefulWidget {
  const _ProductEditForm({required this.product});

  final StoreProduct product;

  @override
  ConsumerState<_ProductEditForm> createState() => _ProductEditFormState();
}

class _ProductEditFormState extends ConsumerState<_ProductEditForm> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _sku;
  late final TextEditingController _brand;
  late final TextEditingController _price;
  late final TextEditingController _oem;
  late final TextEditingController _imageUrl;
  late String _availability;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final product = widget.product;
    _name = TextEditingController(text: product.name);
    _sku = TextEditingController(text: product.sku ?? '');
    _brand = TextEditingController(text: product.brand ?? '');
    _price = TextEditingController(
      text: product.price == null ? '' : _editablePrice(product.price!),
    );
    _oem = TextEditingController(text: product.oemNumbers.join(', '));
    _imageUrl = TextEditingController(text: product.imageUrl ?? '');
    _availability = switch (product.isAvailable) {
      true => 'available',
      false => 'unavailable',
      null => 'unknown',
    };
  }

  @override
  void dispose() {
    _name.dispose();
    _sku.dispose();
    _brand.dispose();
    _price.dispose();
    _oem.dispose();
    _imageUrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _LabeledField(
            label: 'Назва товару',
            required: true,
            controller: _name,
            autofocus: true,
            textInputAction: TextInputAction.next,
            validator: (value) => value == null || value.trim().isEmpty
                ? 'Вкажіть назву товару'
                : null,
          ),
          const SizedBox(height: MarkoSpace.lg),
          LayoutBuilder(
            builder: (context, constraints) {
              final fields = [
                Expanded(
                  child: _LabeledField(
                    label: 'Артикул',
                    controller: _sku,
                    textInputAction: TextInputAction.next,
                  ),
                ),
                const SizedBox(width: MarkoSpace.md),
                Expanded(
                  child: _LabeledField(
                    label: 'Бренд',
                    controller: _brand,
                    textInputAction: TextInputAction.next,
                  ),
                ),
              ];
              if (constraints.maxWidth >= 400) return Row(children: fields);
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _LabeledField(
                    label: 'Артикул',
                    controller: _sku,
                    textInputAction: TextInputAction.next,
                  ),
                  const SizedBox(height: MarkoSpace.lg),
                  _LabeledField(
                    label: 'Бренд',
                    controller: _brand,
                    textInputAction: TextInputAction.next,
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: MarkoSpace.lg),
          _LabeledField(
            label: 'Ціна, ₴',
            controller: _price,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9\s,.]')),
            ],
            textInputAction: TextInputAction.next,
            validator: (value) {
              if (value == null || value.trim().isEmpty) return null;
              return parsePrice(value) == null
                  ? 'Вкажіть коректну ціну'
                  : null;
            },
          ),
          const SizedBox(height: MarkoSpace.lg),
          Text('Наявність', style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: MarkoSpace.sm),
          DropdownButtonFormField<String>(
            initialValue: _availability,
            decoration: const InputDecoration(),
            items: const [
              DropdownMenuItem(value: 'available', child: Text('В наявності')),
              DropdownMenuItem(
                value: 'unavailable',
                child: Text('Немає в наявності'),
              ),
              DropdownMenuItem(
                value: 'unknown',
                child: Text('Наявність невідома'),
              ),
            ],
            onChanged: _saving
                ? null
                : (value) {
                    if (value != null) {
                      setState(() => _availability = value);
                    }
                  },
          ),
          const SizedBox(height: MarkoSpace.lg),
          _LabeledField(
            label: 'OEM номери',
            helper: 'Розділяйте номери комою.',
            controller: _oem,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: MarkoSpace.lg),
          _LabeledField(
            label: 'Посилання на зображення',
            controller: _imageUrl,
            keyboardType: TextInputType.url,
            textInputAction: TextInputAction.done,
            onFieldSubmitted: (_) => _save(),
            validator: (value) {
              final normalized = value?.trim() ?? '';
              if (normalized.isEmpty) return null;
              final uri = Uri.tryParse(normalized);
              if (uri == null ||
                  !uri.hasScheme ||
                  (uri.scheme != 'http' && uri.scheme != 'https')) {
                return 'Вкажіть посилання, що починається з http:// або https://';
              }
              return null;
            },
          ),
          if (_error != null) ...[
            const SizedBox(height: MarkoSpace.lg),
            MarkoInlineMessage(message: _error!, tone: MarkoMessageTone.error),
          ],
          const SizedBox(height: MarkoSpace.xl),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: _saving ? null : () => Navigator.of(context).pop(),
                child: const Text('Скасувати'),
              ),
              const SizedBox(width: MarkoSpace.sm),
              MarkoButton(
                label: 'Зберегти',
                icon: HeroIcons.check,
                loading: _saving,
                onPressed: _saving ? null : _save,
              ),
            ],
          ),
          const SizedBox(height: MarkoSpace.xs),
          Text(
            'Посилання на товар і магазин керуються джерелом імпорту.',
            textAlign: TextAlign.right,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.faint),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    if (_saving || !_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref
          .read(productsControllerProvider.notifier)
          .updateProduct(
            widget.product.id,
            ProductUpdate(
              name: _name.text.trim(),
              sku: _emptyToNull(_sku.text),
              brand: _emptyToNull(_brand.text),
              price: parsePrice(_price.text),
              isAvailable: switch (_availability) {
                'available' => true,
                'unavailable' => false,
                _ => null,
              },
              imageUrl: _emptyToNull(_imageUrl.text),
              oemNumbers: _oem.text
                  .split(RegExp(r'[,;\n]'))
                  .map((value) => value.trim())
                  .where((value) => value.isNotEmpty)
                  .toSet()
                  .toList(growable: false),
            ),
          );
      if (!mounted) return;
      showMarkoToast(context, message: 'Зміни збережено');
      Navigator.of(context).pop();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = error.toString();
      });
    }
  }
}

class _LabeledField extends StatelessWidget {
  const _LabeledField({
    required this.label,
    required this.controller,
    this.required = false,
    this.helper,
    this.autofocus = false,
    this.keyboardType,
    this.inputFormatters,
    this.textInputAction,
    this.onFieldSubmitted,
    this.validator,
  });

  final String label;
  final TextEditingController controller;
  final bool required;
  final String? helper;
  final bool autofocus;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? inputFormatters;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onFieldSubmitted;
  final FormFieldValidator<String>? validator;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          required ? '$label *' : label,
          style: Theme.of(context).textTheme.labelMedium,
        ),
        const SizedBox(height: MarkoSpace.sm),
        TextFormField(
          controller: controller,
          autofocus: autofocus,
          keyboardType: keyboardType,
          inputFormatters: inputFormatters,
          textInputAction: textInputAction,
          onFieldSubmitted: onFieldSubmitted,
          validator: validator,
        ),
        if (helper != null) ...[
          const SizedBox(height: MarkoSpace.xs),
          Text(
            helper!,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: colors.faint),
          ),
        ],
      ],
    );
  }
}

class _DeleteProductDialog extends ConsumerStatefulWidget {
  const _DeleteProductDialog({required this.product});

  final StoreProduct product;

  @override
  ConsumerState<_DeleteProductDialog> createState() =>
      _DeleteProductDialogState();
}

class _DeleteProductDialogState extends ConsumerState<_DeleteProductDialog> {
  bool _deleting = false;
  String? _error;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final details = [
      if (widget.product.brand != null && widget.product.brand!.isNotEmpty)
        widget.product.brand,
      if (widget.product.sku != null && widget.product.sku!.isNotEmpty)
        'АРТ: ${widget.product.sku}',
    ].join(' · ');
    final subtitle = details.isNotEmpty
        ? details
        : (widget.product.price != null
            ? '${widget.product.price!.toStringAsFixed(0)} ${widget.product.currency}'
            : 'Товар з каталогу');

    return AlertDialog(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(colors.panelRadius),
        side: BorderSide(color: colors.border),
      ),
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      icon: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: colors.negative.withValues(alpha: 0.10),
          shape: BoxShape.circle,
        ),
        alignment: Alignment.center,
        child: HeroIcon(
          HeroIcons.trash,
          color: colors.negative,
          size: 22,
        ),
      ),
      title: Text(
        'Видалити товар?',
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
              fontSize: 18,
            ),
      ),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 380),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
              decoration: BoxDecoration(
                color: colors.surfaceMuted,
                borderRadius: BorderRadius.circular(MarkoRadius.md),
                border: Border.all(color: colors.border),
              ),
              child: Row(
                children: [
                  Container(
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(
                      color: colors.negativeSoft,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: colors.negative.withValues(alpha: 0.24),
                      ),
                    ),
                    alignment: Alignment.center,
                    child: HeroIcon(
                      HeroIcons.archiveBox,
                      size: 16,
                      color: colors.negative,
                    ),
                  ),
                  const SizedBox(width: MarkoSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.product.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context)
                              .textTheme
                              .bodyMedium
                              ?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                        Text(
                          subtitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: MarkoType.caption.copyWith(
                            color: colors.faint,
                            fontSize: 11.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: MarkoSpace.md),
            Text(
              'Товар зникне з каталогу. Наступна синхронізація не додасть його знову.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colors.muted,
                  ),
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
      actionsPadding: const EdgeInsets.fromLTRB(
        MarkoSpace.lg,
        0,
        MarkoSpace.lg,
        MarkoSpace.lg,
      ),
      actions: [
        TextButton(
          onPressed: _deleting ? null : () => Navigator.of(context).pop(false),
          child: const Text('Скасувати'),
        ),
        MarkoButton.danger(
          label: 'Видалити',
          icon: HeroIcons.trash,
          loading: _deleting,
          onPressed: _deleting ? null : _delete,
        ),
      ],
    );
  }

  Future<void> _delete() async {
    setState(() {
      _deleting = true;
      _error = null;
    });
    try {
      await ref
          .read(productsControllerProvider.notifier)
          .deleteProduct(widget.product.id);
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _deleting = false;
        _error = error.toString();
      });
    }
  }
}

String? _emptyToNull(String value) {
  final normalized = value.trim();
  return normalized.isEmpty ? null : normalized;
}

String _editablePrice(double value) => value == value.truncateToDouble()
    ? value.toStringAsFixed(0)
    : value.toStringAsFixed(2);
