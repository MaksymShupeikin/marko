class AuthUser {
  const AuthUser({
    required this.id,
    required this.email,
    required this.displayName,
    required this.avatarUrl,
    required this.workspaceId,
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) {
    return AuthUser(
      id: json['id'] as String,
      email: json['email'] as String,
      displayName: json['display_name'] as String?,
      avatarUrl: json['avatar_url'] as String?,
      workspaceId: json['workspace_id'] as String,
    );
  }

  final String id;
  final String email;
  final String? displayName;
  final String? avatarUrl;
  final String workspaceId;

  /// What to call the user in the UI. Google sign-ins carry a name; an
  /// email/password account falls back to the part before the `@`.
  String get shortName {
    final name = displayName?.trim();
    if (name != null && name.isNotEmpty) return name;
    final local = email.split('@').first;
    return local.isEmpty ? email : local;
  }
}

class MarkoAuthState {
  const MarkoAuthState({
    required this.user,
    required this.busy,
    required this.error,
    required this.notice,
  });

  static const initial = MarkoAuthState(
    user: null,
    busy: false,
    error: null,
    notice: null,
  );

  final AuthUser? user;
  final bool busy;
  final String? error;
  final String? notice;

  MarkoAuthState copyWith({
    AuthUser? user,
    bool? busy,
    String? error,
    String? notice,
    bool clearUser = false,
    bool clearError = false,
    bool clearNotice = false,
  }) {
    return MarkoAuthState(
      user: clearUser ? null : user ?? this.user,
      busy: busy ?? this.busy,
      error: clearError ? null : error ?? this.error,
      notice: clearNotice ? null : notice ?? this.notice,
    );
  }
}
