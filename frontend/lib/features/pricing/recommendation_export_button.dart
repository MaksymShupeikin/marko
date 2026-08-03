import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_language.dart';
import '../../core/environment.dart';
import '../../core/session_expiry.dart';
import '../../core/widgets/marko_menu.dart';
import 'pricing_api.dart';

typedef RecommendationDownloadSaver =
    Future<String?> Function(BinaryDownload download);

class RecommendationExportButton extends ConsumerStatefulWidget {
  const RecommendationExportButton({
    required this.queue,
    required this.sort,
    this.action,
    this.runId,
    this.saveDownload,
    super.key,
  });

  final String queue;
  final String sort;
  final String? action;

  /// The pricing run currently on screen. Without it the backend exports the
  /// newest run, which is not necessarily the one being looked at.
  final String? runId;
  final RecommendationDownloadSaver? saveDownload;

  @override
  ConsumerState<RecommendationExportButton> createState() =>
      _RecommendationExportButtonState();
}

class _RecommendationExportButtonState
    extends ConsumerState<RecommendationExportButton> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    // Мёртвый токен — состояние приложения: 401 мог прийти из списка, из
    // расчёта или отсюда же. Предлагать выгрузку после него значит обещать
    // файл, которого не будет, и прятать единственное действие, которое
    // что-то меняет.
    final sessionExpired = ref.watch(markoSessionExpiredProvider);
    final entries = <MarkoMenuEntry<String>>[
      MarkoMenuEntry(
        value: 'xlsx',
        label: context.localized(ru: 'Excel (.xlsx)', uk: 'Excel (.xlsx)'),
        icon: Icons.table_view_outlined,
      ),
      MarkoMenuEntry(
        value: 'csv',
        label: context.localized(ru: 'CSV (.csv)', uk: 'CSV (.csv)'),
        icon: Icons.text_snippet_outlined,
      ),
    ];
    return MarkoMenuButton<String>(
      key: const ValueKey('recommendations-export'),
      enabled: !_busy && !sessionExpired,
      tooltip: context.localized(
        ru: 'Выгрузить активную выборку',
        uk: 'Вивантажити активну вибірку',
      ),
      selected: null,
      entries: entries,
      onSelected: (format) => unawaited(_export(format)),
      minWidth: 210,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          border: Border.all(color: Theme.of(context).colorScheme.outline),
          borderRadius: BorderRadius.circular(9),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_busy)
              const SizedBox.square(
                dimension: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              const Icon(Icons.download_rounded, size: 19),
            const SizedBox(width: 8),
            Text(context.localized(ru: 'Экспорт', uk: 'Експорт')),
            const SizedBox(width: 4),
            const Icon(Icons.arrow_drop_down_rounded, size: 19),
          ],
        ),
      ),
    );
  }

  Future<void> _export(String format) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final download = await ref
          .read(pricingApiProvider)
          .exportRecommendations(
            format: format,
            queue: widget.queue,
            sort: widget.sort,
            action: widget.action,
            runId: widget.runId,
          );
      final saver =
          widget.saveDownload ??
          (Environment.e2eMode ? _acknowledgeE2eDownload : _saveDownload);
      final path = await saver(download);
      if (!mounted || path == null) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Выгружено ${download.rowCount ?? 0} строк: ${download.filename}',
              uk: 'Вивантажено ${download.rowCount ?? 0} рядків: ${download.filename}',
            ),
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      // A snackbar carrying the backend's "Authentication required" would
      // scroll away in four seconds and offer nothing. The page answers an
      // expired session in place, with the sign-in that resolves it.
      if (ref.classifySessionExpiry(error)) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            context.localized(
              ru: 'Не удалось выгрузить рекомендации: $error',
              uk: 'Не вдалося вивантажити рекомендації: $error',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

Future<String?> _acknowledgeE2eDownload(BinaryDownload download) async =>
    '/e2e/${download.filename}';

Future<String?> _saveDownload(BinaryDownload download) {
  final extension = download.filename.toLowerCase().endsWith('.csv')
      ? 'csv'
      : 'xlsx';
  return FilePicker.saveFile(
    dialogTitle: 'Marko · export',
    fileName: download.filename,
    type: FileType.custom,
    allowedExtensions: [extension],
    bytes: download.bytes,
  );
}
