import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_language.dart';
import '../../core/app_theme.dart';
import '../../core/marko_ui.dart';
import 'catalog_import_api.dart';
import 'catalog_import_models.dart';

const _maxCatalogBytes = 25 * 1024 * 1024;
const _requiredImportFields = {'oe', 'name', 'category', 'price'};
const _visibleImportFields = [
  'sku',
  'oe',
  'name',
  'category',
  'price',
  'currency',
  'available',
  'brand',
  'description',
  'product_url',
];

class PickedCatalogFile {
  const PickedCatalogFile({required this.name, required this.bytes});

  final String name;
  final Uint8List bytes;
}

typedef CatalogFilePicker = Future<PickedCatalogFile?> Function();

Future<void> showCatalogImportDialog({
  required BuildContext context,
  required bool canAdministerWorkspace,
  required VoidCallback onImported,
  CatalogFilePicker? pickFile,
}) {
  return showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => CatalogImportDialog(
      canAdministerWorkspace: canAdministerWorkspace,
      onImported: onImported,
      pickFile: pickFile,
    ),
  );
}

class CatalogImportDialog extends ConsumerStatefulWidget {
  const CatalogImportDialog({
    required this.canAdministerWorkspace,
    required this.onImported,
    this.pickFile,
    super.key,
  });

  final bool canAdministerWorkspace;
  final VoidCallback onImported;
  final CatalogFilePicker? pickFile;

  @override
  ConsumerState<CatalogImportDialog> createState() =>
      _CatalogImportDialogState();
}

enum _ImportView {
  empty,
  loading,
  preview,
  uploading,
  success,
  partial,
  failed,
  error,
}

class _CatalogImportDialogState extends ConsumerState<CatalogImportDialog> {
  _ImportView _view = _ImportView.empty;
  PickedCatalogFile? _file;
  CatalogImportPreview? _preview;
  CatalogSheetPreview? _sheet;
  CatalogImportBatch? _result;
  Map<String, String> _mapping = {};
  String? _error;
  bool _forbidden = false;

  CatalogImportApi get _api => ref.read(catalogImportApiProvider);

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final forbidden = !widget.canAdministerWorkspace || _forbidden;
    return Dialog(
      key: const ValueKey('catalog-import-dialog'),
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 920, maxHeight: 760),
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 20, 12, 14),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      context.localized(
                        ru: 'Импорт каталога XLSX',
                        uk: 'Імпорт каталогу XLSX',
                      ),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    tooltip: context.localized(ru: 'Закрыть', uk: 'Закрити'),
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
            ),
            Divider(height: 1, color: colors.border),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: forbidden
                    ? _ForbiddenImport(onClose: () => Navigator.pop(context))
                    : _body(context),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    return switch (_view) {
      _ImportView.empty => _EmptyImport(onPick: _pickAndPreview),
      _ImportView.loading || _ImportView.uploading => _ImportProgress(
        uploading: _view == _ImportView.uploading,
      ),
      _ImportView.preview => _PreviewImport(
        file: _file!,
        preview: _preview!,
        selectedSheet: _sheet,
        mapping: _mapping,
        onSheetSelected: _selectSheet,
        onMappingChanged: _changeMapping,
        onUpload: _canUpload ? _upload : null,
        onChooseAnother: _pickAndPreview,
      ),
      _ImportView.success ||
      _ImportView.partial ||
      _ImportView.failed => _ImportResult(
        batch: _result!,
        onClose: () => Navigator.pop(context),
        onChooseAnother: _reset,
      ),
      _ImportView.error => _ImportError(
        message:
            _error ??
            context.localized(
              ru: 'Не удалось обработать файл.',
              uk: 'Не вдалося обробити файл.',
            ),
        onRetry: _file == null ? _pickAndPreview : _previewCurrent,
        onChooseAnother: _pickAndPreview,
      ),
    };
  }

  bool get _canUpload =>
      _sheet != null &&
      _requiredImportFields.every(
        (field) => (_mapping[field] ?? '').trim().isNotEmpty,
      );

  Future<void> _pickAndPreview() async {
    final picker = widget.pickFile ?? _pickCatalogFile;
    try {
      final selected = await picker();
      if (selected == null || !mounted) return;
      if (!selected.name.toLowerCase().endsWith('.xlsx')) {
        _showError(
          context.localized(
            ru: 'Выберите файл формата .xlsx.',
            uk: 'Оберіть файл формату .xlsx.',
          ),
          clearFile: true,
        );
        return;
      }
      if (selected.bytes.length > _maxCatalogBytes) {
        _showError(
          context.localized(
            ru: 'Файл больше 25 MB.',
            uk: 'Файл більший за 25 MB.',
          ),
          clearFile: true,
        );
        return;
      }
      setState(() {
        _file = selected;
        _view = _ImportView.loading;
        _error = null;
        _preview = null;
        _sheet = null;
        _mapping = {};
      });
      await _previewCurrent();
    } catch (error) {
      if (mounted) _handleApiError(error);
    }
  }

  Future<void> _previewCurrent() async {
    final file = _file;
    if (file == null) {
      _reset();
      return;
    }
    setState(() {
      _view = _ImportView.loading;
      _error = null;
    });
    try {
      final preview = await _api.preview(
        filename: file.name,
        bytes: file.bytes,
      );
      if (!mounted) return;
      setState(() {
        _preview = preview;
        _sheet = null;
        _mapping = {};
        _view = _ImportView.preview;
      });
    } catch (error) {
      if (mounted) _handleApiError(error);
    }
  }

  void _selectSheet(CatalogSheetPreview? sheet) {
    setState(() {
      _sheet = sheet;
      _mapping = Map<String, String>.from(sheet?.suggestedMapping ?? const {});
    });
  }

  void _changeMapping(String field, String? header) {
    setState(() {
      if (header == null || header.isEmpty) {
        _mapping.remove(field);
      } else {
        _mapping[field] = header;
      }
    });
  }

  Future<void> _upload() async {
    final file = _file;
    final sheet = _sheet;
    if (file == null || sheet == null || !_canUpload) return;
    setState(() {
      _view = _ImportView.uploading;
      _error = null;
    });
    try {
      final result = await _api.upload(
        filename: file.name,
        bytes: file.bytes,
        sheetName: sheet.name,
        mapping: _mapping,
      );
      if (!mounted) return;
      setState(() {
        _result = result;
        // The backend reports `failed` when it could not accept a single row.
        // Announcing that as a success sent every catalog screen off to reload
        // data that had not changed.
        _view = !result.isSuccess
            ? _ImportView.failed
            : result.isPartial
            ? _ImportView.partial
            : _ImportView.success;
      });
      if (!result.isSuccess) return;
      widget.onImported();
    } catch (error) {
      if (mounted) _handleApiError(error);
    }
  }

  void _handleApiError(Object error) {
    if (error is ApiException && error.statusCode == 403) {
      setState(() {
        _forbidden = true;
        _view = _ImportView.error;
      });
      return;
    }
    _showError(error.toString());
  }

  void _showError(String message, {bool clearFile = false}) {
    setState(() {
      _error = message;
      _view = _ImportView.error;
      if (clearFile) _file = null;
    });
  }

  void _reset() {
    setState(() {
      _view = _ImportView.empty;
      _file = null;
      _preview = null;
      _sheet = null;
      _result = null;
      _mapping = {};
      _error = null;
    });
  }
}

Future<PickedCatalogFile?> _pickCatalogFile() async {
  final result = await FilePicker.pickFiles(
    type: FileType.custom,
    allowedExtensions: const ['xlsx'],
    allowMultiple: false,
    withData: true,
  );
  final file = result?.files.single;
  final bytes = file?.bytes;
  if (file == null || bytes == null) return null;
  return PickedCatalogFile(name: file.name, bytes: bytes);
}

class _EmptyImport extends StatelessWidget {
  const _EmptyImport({required this.onPick});

  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) {
    return _StatePanel(
      icon: Icons.upload_file_rounded,
      title: context.localized(
        ru: 'Выберите выгрузку Prom.ua',
        uk: 'Оберіть вивантаження Prom.ua',
      ),
      message: context.localized(
        ru: 'Поддерживается XLSX до 25 MB. Сначала вы увидите листы, колонки и примеры строк — запись начнётся только после подтверждения.',
        uk: 'Підтримується XLSX до 25 MB. Спочатку ви побачите аркуші, колонки й приклади рядків — запис почнеться лише після підтвердження.',
      ),
      action: FilledButton.icon(
        key: const ValueKey('catalog-import-pick-file'),
        onPressed: onPick,
        icon: const Icon(Icons.folder_open_rounded),
        label: Text(context.localized(ru: 'Выбрать XLSX', uk: 'Обрати XLSX')),
      ),
    );
  }
}

class _ImportProgress extends StatelessWidget {
  const _ImportProgress({required this.uploading});

  final bool uploading;

  @override
  Widget build(BuildContext context) {
    return _StatePanel(
      icon: uploading ? Icons.cloud_upload_outlined : Icons.fact_check_outlined,
      title: uploading
          ? context.localized(
              ru: 'Импортируем каталог…',
              uk: 'Імпортуємо каталог…',
            )
          : context.localized(
              ru: 'Проверяем структуру…',
              uk: 'Перевіряємо структуру…',
            ),
      message: uploading
          ? context.localized(
              ru: 'Файл записывается атомарно. Не закрывайте окно до результата.',
              uk: 'Файл записується атомарно. Не закривайте вікно до результату.',
            )
          : context.localized(
              ru: 'Читаем только заголовки и примеры; данные ещё не записываются.',
              uk: 'Читаємо лише заголовки й приклади; дані ще не записуються.',
            ),
      action: const SizedBox.square(
        dimension: 28,
        child: CircularProgressIndicator(strokeWidth: 3),
      ),
    );
  }
}

class _ForbiddenImport extends StatelessWidget {
  const _ForbiddenImport({required this.onClose});

  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return _StatePanel(
      icon: Icons.lock_outline_rounded,
      title: context.localized(
        ru: 'Импорт доступен администратору',
        uk: 'Імпорт доступний адміністратору',
      ),
      message: context.localized(
        ru: 'Попросите владельца или администратора рабочей области загрузить каталог.',
        uk: 'Попросіть власника або адміністратора робочої області завантажити каталог.',
      ),
      action: OutlinedButton(
        onPressed: onClose,
        child: Text(context.localized(ru: 'Закрыть', uk: 'Закрити')),
      ),
    );
  }
}

class _ImportError extends StatelessWidget {
  const _ImportError({
    required this.message,
    required this.onRetry,
    required this.onChooseAnother,
  });

  final String message;
  final VoidCallback onRetry;
  final VoidCallback onChooseAnother;

  @override
  Widget build(BuildContext context) {
    return _StatePanel(
      icon: Icons.error_outline_rounded,
      title: context.localized(
        ru: 'Импорт не выполнен',
        uk: 'Імпорт не виконано',
      ),
      message: message,
      action: Wrap(
        spacing: 10,
        runSpacing: 8,
        alignment: WrapAlignment.center,
        children: [
          FilledButton(
            onPressed: onRetry,
            child: Text(context.localized(ru: 'Повторить', uk: 'Повторити')),
          ),
          OutlinedButton(
            onPressed: onChooseAnother,
            child: Text(context.localized(ru: 'Другой файл', uk: 'Інший файл')),
          ),
        ],
      ),
    );
  }
}

class _PreviewImport extends StatelessWidget {
  const _PreviewImport({
    required this.file,
    required this.preview,
    required this.selectedSheet,
    required this.mapping,
    required this.onSheetSelected,
    required this.onMappingChanged,
    required this.onUpload,
    required this.onChooseAnother,
  });

  final PickedCatalogFile file;
  final CatalogImportPreview preview;
  final CatalogSheetPreview? selectedSheet;
  final Map<String, String> mapping;
  final ValueChanged<CatalogSheetPreview?> onSheetSelected;
  final void Function(String field, String? header) onMappingChanged;
  final VoidCallback? onUpload;
  final VoidCallback onChooseAnother;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        MarkoInlineMessage(
          message: context.localized(
            ru: '${file.name} · ${(file.bytes.length / 1024).ceil()} KB. Выберите лист явно: сервис не угадывает между похожими листами.',
            uk: '${file.name} · ${(file.bytes.length / 1024).ceil()} KB. Оберіть аркуш явно: сервіс не вгадує між схожими аркушами.',
          ),
          tone: MarkoMessageTone.info,
        ),
        const SizedBox(height: 18),
        DropdownButtonFormField<CatalogSheetPreview>(
          key: const ValueKey('catalog-import-sheet'),
          initialValue: selectedSheet,
          decoration: InputDecoration(
            labelText: context.localized(
              ru: 'Лист каталога',
              uk: 'Аркуш каталогу',
            ),
            helperText: context.localized(
              ru: 'Выбор обязателен',
              uk: 'Вибір обов’язковий',
            ),
          ),
          items: preview.sheets
              .map(
                (sheet) => DropdownMenuItem(
                  value: sheet,
                  child: Text(
                    '${sheet.name} · ${sheet.rowCount} '
                    '${context.localized(ru: 'строк', uk: 'рядків')}'
                    '${sheet.isCatalogCandidate ? '' : ' · !'}',
                  ),
                ),
              )
              .toList(growable: false),
          onChanged: onSheetSelected,
        ),
        if (selectedSheet != null) ...[
          const SizedBox(height: 18),
          if (selectedSheet!.mappingError != null) ...[
            MarkoInlineMessage(
              message: selectedSheet!.mappingError!,
              tone: MarkoMessageTone.warning,
            ),
            const SizedBox(height: 14),
          ],
          Text(
            context.localized(
              ru: 'Сопоставление колонок',
              uk: 'Зіставлення колонок',
            ),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          LayoutBuilder(
            builder: (context, constraints) {
              final width = constraints.maxWidth >= 680
                  ? (constraints.maxWidth - 12) / 2
                  : constraints.maxWidth;
              return Wrap(
                spacing: 12,
                runSpacing: 12,
                children: _visibleImportFields
                    .map(
                      (field) => SizedBox(
                        width: width,
                        child: DropdownButtonFormField<String>(
                          key: ValueKey('catalog-import-mapping-$field'),
                          initialValue: mapping[field],
                          decoration: InputDecoration(
                            labelText:
                                '${_fieldLabel(context, field)}'
                                '${_requiredImportFields.contains(field) ? ' *' : ''}',
                          ),
                          items: [
                            if (!_requiredImportFields.contains(field))
                              DropdownMenuItem(
                                value: '',
                                child: Text(
                                  context.localized(
                                    ru: 'Не импортировать',
                                    uk: 'Не імпортувати',
                                  ),
                                ),
                              ),
                            ...selectedSheet!.headers.map(
                              (header) => DropdownMenuItem(
                                value: header,
                                child: Text(
                                  header,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ),
                          ],
                          onChanged: (value) => onMappingChanged(field, value),
                        ),
                      ),
                    )
                    .toList(growable: false),
              );
            },
          ),
          if (selectedSheet!.sampleRows.isNotEmpty) ...[
            const SizedBox(height: 20),
            Text(
              context.localized(
                ru: 'Пример строк (без себестоимости)',
                uk: 'Приклад рядків (без собівартості)',
              ),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Container(
              decoration: BoxDecoration(
                border: Border.all(color: colors.border),
                borderRadius: BorderRadius.circular(10),
              ),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: selectedSheet!.headers
                      .where(
                        (header) =>
                            selectedSheet!.sampleRows.first.containsKey(header),
                      )
                      .take(8)
                      .map((header) => DataColumn(label: Text(header)))
                      .toList(growable: false),
                  rows: selectedSheet!.sampleRows
                      .map(
                        (row) => DataRow(
                          cells: selectedSheet!.headers
                              .where(row.containsKey)
                              .take(8)
                              .map(
                                (header) => DataCell(
                                  ConstrainedBox(
                                    constraints: const BoxConstraints(
                                      maxWidth: 180,
                                    ),
                                    child: Text(
                                      row[header]?.toString() ?? '',
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ),
                              )
                              .toList(growable: false),
                        ),
                      )
                      .toList(growable: false),
                ),
              ),
            ),
          ],
        ],
        const SizedBox(height: 22),
        Wrap(
          alignment: WrapAlignment.end,
          spacing: 10,
          runSpacing: 8,
          children: [
            OutlinedButton(
              onPressed: onChooseAnother,
              child: Text(
                context.localized(ru: 'Другой файл', uk: 'Інший файл'),
              ),
            ),
            FilledButton.icon(
              key: const ValueKey('catalog-import-submit'),
              onPressed: onUpload,
              icon: const Icon(Icons.cloud_upload_outlined),
              label: Text(
                context.localized(ru: 'Импортировать', uk: 'Імпортувати'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _ImportResult extends StatelessWidget {
  const _ImportResult({
    required this.batch,
    required this.onClose,
    required this.onChooseAnother,
  });

  final CatalogImportBatch batch;
  final VoidCallback onClose;
  final VoidCallback onChooseAnother;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    final failed = !batch.isSuccess;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _StatePanel(
          icon: failed
              ? Icons.error_outline_rounded
              : batch.isPartial
              ? Icons.warning_amber_rounded
              : Icons.check_circle_outline_rounded,
          iconColor: failed ? colors.negative : colors.brand,
          title: failed
              ? context.localized(
                  ru: 'Каталог не импортирован',
                  uk: 'Каталог не імпортовано',
                )
              : batch.isPartial
              ? context.localized(
                  ru: 'Каталог импортирован частично',
                  uk: 'Каталог імпортовано частково',
                )
              : context.localized(
                  ru: 'Каталог импортирован',
                  uk: 'Каталог імпортовано',
                ),
          message: failed
              ? context.localized(
                  ru:
                      'Записано ${batch.importedRows} из ${batch.totalRows}; отклонено ${batch.rejectedRows}. '
                      'Ни одна строка не принята — проверьте выбранный лист и сопоставление колонок. Каталог не изменился.',
                  uk:
                      'Записано ${batch.importedRows} з ${batch.totalRows}; відхилено ${batch.rejectedRows}. '
                      'Жоден рядок не прийнято — перевірте вибраний аркуш і зіставлення колонок. Каталог не змінився.',
                )
              : context.localized(
                  ru: 'Записано ${batch.importedRows} из ${batch.totalRows}; отклонено ${batch.rejectedRows}.',
                  uk: 'Записано ${batch.importedRows} з ${batch.totalRows}; відхилено ${batch.rejectedRows}.',
                ),
          action: Wrap(
            alignment: WrapAlignment.center,
            spacing: 10,
            runSpacing: 8,
            children: [
              if (failed)
                FilledButton(
                  key: const ValueKey('catalog-import-retry-failed'),
                  onPressed: onChooseAnother,
                  child: Text(
                    context.localized(
                      ru: 'Выбрать файл заново',
                      uk: 'Обрати файл заново',
                    ),
                  ),
                )
              else ...[
                FilledButton(
                  key: const ValueKey('catalog-import-close-success'),
                  onPressed: onClose,
                  child: Text(context.localized(ru: 'Готово', uk: 'Готово')),
                ),
                OutlinedButton(
                  onPressed: onChooseAnother,
                  child: Text(
                    context.localized(
                      ru: 'Импортировать другой',
                      uk: 'Імпортувати інший',
                    ),
                  ),
                ),
              ],
              if (failed)
                OutlinedButton(
                  key: const ValueKey('catalog-import-close-failed'),
                  onPressed: onClose,
                  child: Text(context.localized(ru: 'Закрыть', uk: 'Закрити')),
                ),
            ],
          ),
        ),
        if (batch.errorLog.isNotEmpty) ...[
          const SizedBox(height: 18),
          Text(
            context.localized(ru: 'Отклонённые строки', uk: 'Відхилені рядки'),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          ...batch.errorLog.map(
            (issue) => ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: CircleAvatar(radius: 16, child: Text('${issue.row}')),
              title: Text(_issueLabel(context, issue.code)),
              subtitle: Text(issue.message),
            ),
          ),
        ],
      ],
    );
  }
}

class _StatePanel extends StatelessWidget {
  const _StatePanel({
    required this.icon,
    required this.title,
    required this.message,
    required this.action,
    this.iconColor,
  });

  final IconData icon;
  final String title;
  final String message;
  final Widget action;
  final Color? iconColor;

  @override
  Widget build(BuildContext context) {
    final colors = MarkoTheme.of(context);
    return MarkoPanel(
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          Icon(icon, size: 38, color: iconColor ?? colors.brand),
          const SizedBox(height: 14),
          Text(
            title,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          Text(
            message,
            textAlign: TextAlign.center,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: colors.muted),
          ),
          const SizedBox(height: 18),
          action,
        ],
      ),
    );
  }
}

String _fieldLabel(BuildContext context, String field) => switch (field) {
  'sku' => context.localized(ru: 'Артикул / SKU', uk: 'Артикул / SKU'),
  'oe' => 'OE / OEM',
  'name' => context.localized(ru: 'Название', uk: 'Назва'),
  'category' => context.localized(ru: 'Категория', uk: 'Категорія'),
  'price' => context.localized(ru: 'Цена', uk: 'Ціна'),
  'currency' => context.localized(ru: 'Валюта', uk: 'Валюта'),
  'available' => context.localized(ru: 'Наличие', uk: 'Наявність'),
  'brand' => context.localized(ru: 'Бренд', uk: 'Бренд'),
  'description' => context.localized(ru: 'Описание', uk: 'Опис'),
  'product_url' => context.localized(ru: 'Ссылка', uk: 'Посилання'),
  _ => field,
};

String _issueLabel(BuildContext context, String code) => switch (code) {
  'NORMALIZED_OE_COLLISION' => context.localized(
    ru: 'Коллизия нормализованного OE — нужна ручная проверка',
    uk: 'Колізія нормалізованого OE — потрібна ручна перевірка',
  ),
  'INVALID_ROW' => context.localized(
    ru: 'Невалидная строка',
    uk: 'Невалідний рядок',
  ),
  'WORKER_LOST' => context.localized(
    ru: 'Обработка прервана; частичный результат сохранён',
    uk: 'Обробку перервано; частковий результат збережено',
  ),
  _ => context.localized(
    ru: 'Строка требует проверки ($code)',
    uk: 'Рядок потребує перевірки ($code)',
  ),
};
