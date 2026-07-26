import 'dart:convert';
import 'dart:typed_data';

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
    Map<String, dynamic>? queryParameters,
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

  Future<dynamic> deleteJson(String path, {bool authenticated = true}) {
    return _request('DELETE', path, authenticated: authenticated);
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
    Map<String, dynamic>? queryParameters,
    Map<String, dynamic>? body,
    required bool authenticated,
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
    return request.timeout(const Duration(seconds: 15));
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
