class CatalogImportIssue {
  const CatalogImportIssue({
    required this.row,
    required this.code,
    required this.message,
  });

  factory CatalogImportIssue.fromJson(Map<String, dynamic> json) {
    return CatalogImportIssue(
      row: (json['row'] as num?)?.toInt() ?? 0,
      code: json['code']?.toString() ?? 'UNKNOWN',
      message: json['message']?.toString() ?? '',
    );
  }

  final int row;
  final String code;
  final String message;
}

class CatalogImportBatch {
  const CatalogImportBatch({
    required this.id,
    required this.filename,
    required this.status,
    required this.columnMapping,
    required this.totalRows,
    required this.importedRows,
    required this.rejectedRows,
    required this.errorLog,
    required this.createdAt,
  });

  factory CatalogImportBatch.fromJson(Map<String, dynamic> json) {
    return CatalogImportBatch(
      id: json['id'] as String,
      filename: json['filename'] as String,
      status: json['status'] as String,
      columnMapping:
          (json['column_mapping'] as Map<String, dynamic>? ?? const {}).map(
            (key, value) => MapEntry(key, value.toString()),
          ),
      totalRows: (json['total_rows'] as num).toInt(),
      importedRows: (json['imported_rows'] as num).toInt(),
      rejectedRows: (json['rejected_rows'] as num).toInt(),
      errorLog: (json['error_log'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(CatalogImportIssue.fromJson)
          .toList(growable: false),
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  final String id;
  final String filename;
  final String status;
  final Map<String, String> columnMapping;
  final int totalRows;
  final int importedRows;
  final int rejectedRows;
  final List<CatalogImportIssue> errorLog;
  final DateTime createdAt;

  bool get isPartial => status == 'partial';
  bool get isSuccess => status == 'completed' || status == 'partial';
}

class CatalogSheetPreview {
  const CatalogSheetPreview({
    required this.name,
    required this.rowCount,
    required this.headers,
    required this.suggestedMapping,
    required this.mappingError,
    required this.sampleRows,
    required this.isCatalogCandidate,
  });

  factory CatalogSheetPreview.fromJson(Map<String, dynamic> json) {
    return CatalogSheetPreview(
      name: json['name'] as String,
      rowCount: (json['row_count'] as num).toInt(),
      headers: (json['headers'] as List<dynamic>)
          .map((value) => value.toString())
          .toList(growable: false),
      suggestedMapping:
          (json['suggested_mapping'] as Map<String, dynamic>? ?? const {}).map(
            (key, value) => MapEntry(key, value.toString()),
          ),
      mappingError: json['mapping_error']?.toString(),
      sampleRows: (json['sample_rows'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .toList(growable: false),
      isCatalogCandidate: json['is_catalog_candidate'] as bool? ?? false,
    );
  }

  final String name;
  final int rowCount;
  final List<String> headers;
  final Map<String, String> suggestedMapping;
  final String? mappingError;
  final List<Map<String, dynamic>> sampleRows;
  final bool isCatalogCandidate;
}

class CatalogImportPreview {
  const CatalogImportPreview({
    required this.filename,
    required this.contentSize,
    required this.sheets,
    required this.requiresSheetChoice,
    required this.maxSizeBytes,
  });

  factory CatalogImportPreview.fromJson(Map<String, dynamic> json) {
    return CatalogImportPreview(
      filename: json['filename'] as String,
      contentSize: (json['content_size'] as num).toInt(),
      sheets: (json['sheets'] as List<dynamic>)
          .map(
            (item) =>
                CatalogSheetPreview.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      requiresSheetChoice: json['requires_sheet_choice'] as bool? ?? true,
      maxSizeBytes: (json['max_size_bytes'] as num).toInt(),
    );
  }

  final String filename;
  final int contentSize;
  final List<CatalogSheetPreview> sheets;
  final bool requiresSheetChoice;
  final int maxSizeBytes;
}
