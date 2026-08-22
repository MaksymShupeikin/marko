import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/auth/auth_api.dart';
import 'package:marko_client/features/auth/auth_models.dart';

void main() {
  test('loads the local Marko user with a Firebase ID token', () async {
    final api = AuthApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/auth/me');
          expect(request.headers['Authorization'], 'Bearer firebase-id-token');
          return http.Response(jsonEncode(_userJson()), 200);
        }),
        accessToken: () async => 'firebase-id-token',
        baseUrl: 'http://api.test',
      ),
    );

    final user = await api.me();

    expect(user.email, 'seller@example.com');
    expect(user.workspaceId, 'workspace-id');
  });

  test('refreshes the Firebase ID token once after 401 and retries', () async {
    var accessToken = 'expired-access';
    var refreshCalls = 0;
    var protectedCalls = 0;
    final client = ApiClient(
      client: MockClient((request) async {
        protectedCalls++;
        final authorization = request.headers['Authorization'];
        if (authorization == 'Bearer expired-access') {
          return http.Response(jsonEncode({'detail': 'expired'}), 401);
        }
        expect(authorization, 'Bearer new-access');
        return http.Response(jsonEncode({'status': 'ok'}), 200);
      }),
      accessToken: () async => accessToken,
      refreshSession: () async {
        refreshCalls++;
        accessToken = 'new-access';
        return true;
      },
      baseUrl: 'http://api.test',
    );

    final response = await client.getJson('/api/v1/protected');

    expect(response, {'status': 'ok'});
    expect(protectedCalls, 2);
    expect(refreshCalls, 1);
  });
  test('the display name wins over the email, which is the fallback', () {
    AuthUser user(String? displayName) => AuthUser(
      id: 'user-id',
      email: 'seller@example.com',
      displayName: displayName,
      avatarUrl: null,
      workspaceId: 'workspace-id',
    );

    expect(user('Іван Петренко').shortName, 'Іван Петренко');
    expect(user('  ').shortName, 'seller');
    expect(user(null).shortName, 'seller');
  });
}

Map<String, dynamic> _userJson() {
  return {
    'id': 'user-id',
    'email': 'seller@example.com',
    'display_name': null,
    'avatar_url': null,
    'workspace_id': 'workspace-id',
  };
}
