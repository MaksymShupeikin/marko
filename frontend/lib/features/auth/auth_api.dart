import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import 'auth_models.dart';

class AuthApi {
  const AuthApi(this._client);

  final ApiClient _client;

  Future<AuthUser> me() async {
    final payload = await _client.getJson('/api/v1/auth/me');
    return AuthUser.fromJson(payload as Map<String, dynamic>);
  }
}

final authApiProvider = Provider<AuthApi>((ref) {
  return AuthApi(ref.watch(apiClientProvider));
});
