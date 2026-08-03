import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'environment.dart';
import 'firebase_auth_client.dart';
import 'client_error_reporter.dart';

class ApiValidationError {
  const ApiValidationError({
    required this.type,
    required this.location,
    required this.message,
  });

  factory ApiValidationError.fromJson(Map<String, dynamic> json) {
    final rawLocation = json['loc'];
    return ApiValidationError(
      type: json['type']?.toString() ?? 'validation_error',
      location: rawLocation is List
          ? rawLocation.map((part) => part.toString()).toList(growable: false)
          : const [],
      message: json['msg']?.toString() ?? 'Invalid value',
    );
  }

  final String type;
  final List<String> location;
  final String message;
}

class ApiException implements Exception {
  const ApiException(
    this.message, {
    this.statusCode,
    this.code,
    this.detail,
    this.requiredRoles = const [],
    this.actualRole,
    this.validationErrors = const [],
    this.metadata = const {},
  });

  final String message;
  final int? statusCode;
  final String? code;
  final Object? detail;
  final List<String> requiredRoles;
  final String? actualRole;
  final List<ApiValidationError> validationErrors;
  final Map<String, dynamic> metadata;

  @override
  String toString() => message;
}

/// The session is gone or unrefreshable — the client already spent its one
/// refresh attempt before letting a 401 out.
///
/// A 401 is the single API failure that a retry can never fix and that the
/// operator can actually resolve, so it must never reach them as a message.
/// It arrives from three directions — a notifier failing to build, a refresh,
/// and a pagination request — and classifying it separately in each place is
/// how two of the three ended up printing the backend's English
/// "Authentication required". Every caller asks this one question instead.
bool markoIsSessionExpired(Object? error) =>
    error is ApiException && error.statusCode == 401;

class BinaryDownload {
  const BinaryDownload({
    required this.bytes,
    required this.filename,
    required this.contentType,
    this.rowCount,
  });

  final Uint8List bytes;
  final String filename;
  final String? contentType;
  final int? rowCount;
}

class ApiClient {
  ApiClient({
    required this.client,
    Future<String?> Function()? accessToken,
    Future<bool> Function()? refreshSession,
    String? baseUrl,
  }) : _accessToken = accessToken ?? (() async => null),
       _refreshSession = refreshSession ?? (() async => false),
       baseUrl = _normalizeBaseUrl(baseUrl ?? Environment.apiBaseUrl);

  final http.Client client;
  final Future<String?> Function() _accessToken;
  final Future<bool> Function() _refreshSession;
  final String baseUrl;

  Future<bool>? _refreshing;

  Future<dynamic> getJson(
    String path, {
    Map<String, dynamic>? queryParameters,
    bool authenticated = true,
    Duration? timeout,
  }) async {
    return _request(
      'GET',
      path,
      queryParameters: queryParameters,
      authenticated: authenticated,
      timeout: timeout,
    );
  }

  Future<dynamic> postJson(
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
    Duration? timeout,
  }) {
    return _request(
      'POST',
      path,
      body: body,
      authenticated: authenticated,
      timeout: timeout,
    );
  }

  Future<dynamic> deleteJson(
    String path, {
    bool authenticated = true,
    Duration? timeout,
  }) {
    return _request(
      'DELETE',
      path,
      authenticated: authenticated,
      timeout: timeout,
    );
  }

  Future<BinaryDownload> getBytes(
    String path, {
    Map<String, dynamic>? queryParameters,
    bool authenticated = true,
    String fallbackFilename = 'download.bin',
  }) async {
    var response = await _send(
      'GET',
      path,
      queryParameters: queryParameters,
      authenticated: authenticated,
    );
    if (response.statusCode == 401 && authenticated && await _refreshOnce()) {
      response = await _send(
        'GET',
        path,
        queryParameters: queryParameters,
        authenticated: true,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      _decode(response);
    }
    _rememberCorrelationId(response);
    return BinaryDownload(
      bytes: response.bodyBytes,
      filename:
          _filenameFromDisposition(response.headers['content-disposition']) ??
          fallbackFilename,
      contentType: response.headers['content-type'],
      rowCount: int.tryParse(response.headers['x-export-row-count'] ?? ''),
    );
  }

  Future<dynamic> postMultipart(
    String path, {
    required String filename,
    required Uint8List bytes,
    Map<String, String>? fields,
    bool authenticated = true,
  }) async {
    var response = await _sendMultipart(
      path,
      filename: filename,
      bytes: bytes,
      fields: fields,
      authenticated: authenticated,
    );
    if (response.statusCode == 401 && authenticated && await _refreshOnce()) {
      response = await _sendMultipart(
        path,
        filename: filename,
        bytes: bytes,
        fields: fields,
        authenticated: true,
      );
    }
    return _decode(response);
  }

  Future<dynamic> _request(
    String method,
    String path, {
    Map<String, dynamic>? queryParameters,
    Map<String, dynamic>? body,
    required bool authenticated,
    Duration? timeout,
  }) async {
    var response = await _send(
      method,
      path,
      queryParameters: queryParameters,
      body: body,
      authenticated: authenticated,
      timeout: timeout,
    );
    if (response.statusCode == 401 && authenticated && await _refreshOnce()) {
      response = await _send(
        method,
        path,
        queryParameters: queryParameters,
        body: body,
        authenticated: true,
        timeout: timeout,
      );
    }
    return _decode(response);
  }

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, dynamic>? queryParameters,
    Map<String, dynamic>? body,
    required bool authenticated,
    Duration? timeout,
  }) async {
    final uri = Uri.parse(
      '$baseUrl$path',
    ).replace(queryParameters: queryParameters);
    final headers = <String, String>{'Content-Type': 'application/json'};
    final accessToken = await _accessToken();
    if (authenticated && accessToken != null) {
      headers['Authorization'] = 'Bearer $accessToken';
    }
    final encodedBody = body == null ? null : jsonEncode(body);
    final request = switch (method) {
      'POST' => client.post(uri, headers: headers, body: encodedBody),
      'DELETE' => client.delete(uri, headers: headers),
      _ => client.get(uri, headers: headers),
    };
    return request.timeout(timeout ?? const Duration(seconds: 15));
  }

  Future<http.Response> _sendMultipart(
    String path, {
    required String filename,
    required Uint8List bytes,
    Map<String, String>? fields,
    required bool authenticated,
  }) async {
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl$path'));
    request.fields.addAll(fields ?? const {});
    request.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );
    final accessToken = await _accessToken();
    if (authenticated && accessToken != null) {
      request.headers['Authorization'] = 'Bearer $accessToken';
    }
    final streamed = await client
        .send(request)
        .timeout(const Duration(minutes: 2));
    return http.Response.fromStream(streamed);
  }

  Future<bool> _refreshOnce() async {
    final running = _refreshing;
    if (running != null) return running;
    if (await _accessToken() == null) return false;

    final future = _refreshSession();
    _refreshing = future;
    try {
      return await future;
    } finally {
      _refreshing = null;
    }
  }

  dynamic _decode(http.Response response) {
    _rememberCorrelationId(response);
    dynamic payload;
    if (response.body.isNotEmpty) {
      try {
        payload = jsonDecode(response.body);
      } on FormatException {
        payload = response.body;
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = payload is Map<String, dynamic>
          ? payload['detail']
          : payload;
      final structured = detail is Map<String, dynamic> ? detail : null;
      final validationErrors = detail is List
          ? detail
                .whereType<Map<String, dynamic>>()
                .map(ApiValidationError.fromJson)
                .toList(growable: false)
          : const <ApiValidationError>[];
      final requiredRoles = structured?['required_roles'] is List
          ? (structured!['required_roles'] as List)
                .map((role) => role.toString())
                .toList(growable: false)
          : const <String>[];
      final metadata = structured == null
          ? <String, dynamic>{}
          : Map<String, dynamic>.from(structured);
      metadata
        ..remove('code')
        ..remove('message')
        ..remove('required_roles')
        ..remove('actual_role');
      final message =
          structured?['message']?.toString() ??
          (validationErrors.isNotEmpty
              ? 'API validation failed'
              : detail is String && detail.isNotEmpty
              ? detail
              : 'API returned HTTP ${response.statusCode}');
      throw ApiException(
        message,
        statusCode: response.statusCode,
        code: structured?['code']?.toString(),
        detail: detail,
        requiredRoles: requiredRoles,
        actualRole: structured?['actual_role']?.toString(),
        validationErrors: validationErrors,
        metadata: metadata,
      );
    }
    return payload;
  }

  void _rememberCorrelationId(http.Response response) {
    ClientErrorReporter.instance.updateCorrelationId(
      response.headers['x-correlation-id'],
    );
  }

  static String? _filenameFromDisposition(String? value) {
    if (value == null || value.isEmpty) return null;
    final encoded = RegExp(
      r"filename\*=UTF-8''([^;]+)",
      caseSensitive: false,
    ).firstMatch(value)?.group(1);
    if (encoded != null) return Uri.decodeComponent(encoded);
    return RegExp(
      r'filename="?([^";]+)"?',
      caseSensitive: false,
    ).firstMatch(value)?.group(1);
  }

  static String _normalizeBaseUrl(String value) {
    return value.endsWith('/') ? value.substring(0, value.length - 1) : value;
  }
}

final httpClientProvider = Provider<http.Client>((ref) {
  final client = http.Client();
  ref.onDispose(client.close);
  return client;
});

final apiClientProvider = Provider<ApiClient>((ref) {
  final auth = ref.watch(authClientProvider);
  return ApiClient(
    client: ref.watch(httpClientProvider),
    accessToken: () => auth.idToken(),
    refreshSession: () async {
      try {
        return await auth.idToken(forceRefresh: true) != null;
      } catch (_) {
        return false;
      }
    },
  );
});
