import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'environment.dart';
import 'firebase_auth_client.dart';

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
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
    Map<String, String>? queryParameters,
    bool authenticated = true,
  }) async {
    return _request(
      'GET',
      path,
      queryParameters: queryParameters,
      authenticated: authenticated,
    );
  }

  Future<dynamic> postJson(
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
  }) {
    return _request('POST', path, body: body, authenticated: authenticated);
  }

  Future<dynamic> patchJson(
    String path, {
    Map<String, dynamic>? body,
    bool authenticated = true,
  }) {
    return _request('PATCH', path, body: body, authenticated: authenticated);
  }

  Future<dynamic> deleteJson(String path, {bool authenticated = true}) {
    return _request('DELETE', path, authenticated: authenticated);
  }

  /// Raw bytes for a file download. JSON decoding would destroy the payload,
  /// so this stays outside [_request]; a catalog-sized sheet also needs more
  /// than the default JSON timeout.
  Future<List<int>> getBytes(
    String path, {
    bool authenticated = true,
    Duration timeout = const Duration(seconds: 60),
  }) async {
    var response = await _send(
      'GET',
      path,
      authenticated: authenticated,
      timeout: timeout,
    );
    if (response.statusCode == 401 && authenticated && await _refreshOnce()) {
      response = await _send(
        'GET',
        path,
        authenticated: true,
        timeout: timeout,
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        'Не вдалося завантажити файл.',
        statusCode: response.statusCode,
      );
    }
    return response.bodyBytes;
  }

  /// Uploads one file as multipart/form-data. Catalog files are large and the
  /// server parses them inline, so this uses a longer timeout than JSON calls.
  Future<dynamic> postFile(
    String path, {
    required String field,
    required String filename,
    required List<int> bytes,
    Duration timeout = const Duration(seconds: 120),
  }) async {
    final request = http.MultipartRequest('POST', Uri.parse('$baseUrl$path'))
      ..files.add(
        http.MultipartFile.fromBytes(field, bytes, filename: filename),
      );
    final accessToken = await _accessToken();
    if (accessToken != null) {
      request.headers['Authorization'] = 'Bearer $accessToken';
    }
    final streamed = await client.send(request).timeout(timeout);
    return _decode(await http.Response.fromStream(streamed));
  }

  /// Server-sent events: yields each decoded `data:` payload as it arrives.
  // ponytail: без повтору на 401 — токен беремо перед стартом потоку.
  Stream<Map<String, dynamic>> streamJson(
    String path, {
    Map<String, String>? queryParameters,
    Duration timeout = const Duration(minutes: 3),
  }) async* {
    final uri = Uri.parse(
      '$baseUrl$path',
    ).replace(queryParameters: queryParameters);
    final request = http.Request('GET', uri)
      ..headers['Accept'] = 'text/event-stream';
    final accessToken = await _accessToken();
    if (accessToken != null) {
      request.headers['Authorization'] = 'Bearer $accessToken';
    }
    final response = await client.send(request).timeout(timeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        'API returned HTTP ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    final lines = response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter());
    await for (final line in lines) {
      if (!line.startsWith('data:')) continue;
      final payload = jsonDecode(line.substring(5).trim());
      if (payload is Map<String, dynamic>) yield payload;
    }
  }

  Future<dynamic> _request(
    String method,
    String path, {
    Map<String, String>? queryParameters,
    Map<String, dynamic>? body,
    required bool authenticated,
  }) async {
    var response = await _send(
      method,
      path,
      queryParameters: queryParameters,
      body: body,
      authenticated: authenticated,
    );
    if (response.statusCode == 401 && authenticated && await _refreshOnce()) {
      response = await _send(
        method,
        path,
        queryParameters: queryParameters,
        body: body,
        authenticated: true,
      );
    }
    return _decode(response);
  }

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, String>? queryParameters,
    Map<String, dynamic>? body,
    required bool authenticated,
    Duration timeout = const Duration(seconds: 15),
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
      'PATCH' => client.patch(uri, headers: headers, body: encodedBody),
      'DELETE' => client.delete(uri, headers: headers),
      _ => client.get(uri, headers: headers),
    };
    return request.timeout(timeout);
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
      throw ApiException(
        detail?.toString() ?? 'API returned HTTP ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return payload;
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
