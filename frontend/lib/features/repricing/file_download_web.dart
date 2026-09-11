import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Hands the sheet to the browser as a real file download.
///
/// Звіт віддається під токеном, тож просте посилання не спрацює: файл
/// приїжджає байтами, і лише тут стає завантаженням.
bool saveBytes(List<int> bytes, String filename, String mimeType) {
  final blob = web.Blob(
    [Uint8List.fromList(bytes).toJS].toJS,
    web.BlobPropertyBag(type: mimeType),
  );
  final url = web.URL.createObjectURL(blob);
  final anchor = web.document.createElement('a') as web.HTMLAnchorElement
    ..href = url
    ..download = filename;
  anchor.click();
  web.URL.revokeObjectURL(url);
  return true;
}
