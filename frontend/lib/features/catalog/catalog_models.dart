class CatalogImport {
  const CatalogImport({
    required this.id,
    required this.filename,
    required this.status,
    required this.totalRows,
    required this.importedRows,
    required this.rejectedRows,
    required this.errors,
    required this.createdAt,
  });

  factory CatalogImport.fromJson(Map<String, dynamic> json) {
    return CatalogImport(
      id: json['id'] as String,
      filename: json['filename'] as String,
      status: json['status'] as String,
      totalRows: (json['total_rows'] as num).toInt(),
      importedRows: (json['imported_rows'] as num).toInt(),
      rejectedRows: (json['rejected_rows'] as num).toInt(),
      errors: (json['error_log'] as List<dynamic>? ?? const [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList(growable: false),
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  final String id;
  final String filename;
  final String status;
  final int totalRows;
  final int importedRows;
  final int rejectedRows;
  final List<Map<String, dynamic>> errors;
  final DateTime createdAt;

  bool get canRun =>
      importedRows > 0 && (status == 'completed' || status == 'partial');

  String get statusLabel => switch (status) {
    'completed' => 'готов',
    'partial' => 'готов с ошибками',
    'failed' => 'ошибка',
    'running' => 'импортируется',
    _ => status,
  };
}

class CatalogImportPage {
  const CatalogImportPage({required this.items, required this.total});

  factory CatalogImportPage.fromJson(Map<String, dynamic> json) {
    return CatalogImportPage(
      items: (json['items'] as List<dynamic>)
          .map((item) => CatalogImport.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      total: (json['total'] as num).toInt(),
    );
  }

  final List<CatalogImport> items;
  final int total;
}
