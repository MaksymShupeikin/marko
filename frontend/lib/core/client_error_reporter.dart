import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/widgets.dart';

enum ClientErrorKind { flutter, platform, zone }

typedef ClientErrorTransport =
    Future<void> Function(Map<String, dynamic> event);

class ClientErrorReporter {
  ClientErrorReporter({
    ClientErrorTransport? initialTransport,
    this.release = const String.fromEnvironment(
      'CLIENT_RELEASE',
      defaultValue: '1.0.0+1',
    ),
    this.maxBufferedEvents = 50,
    DateTime Function()? now,
  }) : _transport = initialTransport,
       _now = now ?? DateTime.now;

  static final ClientErrorReporter instance = ClientErrorReporter();

  final String release;
  final int maxBufferedEvents;
  final DateTime Function() _now;
  final List<Map<String, dynamic>> _buffer = [];

  ClientErrorTransport? _transport;
  String? _route;
  String? _correlationId;
  bool _isFlushing = false;
  int _sequence = 0;

  int get bufferedEventCount => _buffer.length;

  void attachTransport(ClientErrorTransport transport) {
    _transport = transport;
  }

  void updateRoute(String? route) {
    final normalized = route?.trim();
    _route = normalized == null || normalized.isEmpty
        ? null
        : _bounded(normalized, 200);
  }

  void updateCorrelationId(String? correlationId) {
    final normalized = correlationId?.trim();
    _correlationId =
        normalized != null &&
            RegExp(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$').hasMatch(normalized)
        ? normalized
        : null;
  }

  Future<void> capture(
    Object error,
    StackTrace stackTrace, {
    ClientErrorKind kind = ClientErrorKind.flutter,
  }) async {
    final occurredAt = _now().toUtc();
    final messageFingerprint = _fingerprint(error.toString());
    _sequence += 1;
    final eventSeed =
        '${occurredAt.toIso8601String()}:$messageFingerprint:$_sequence';
    final event = <String, dynamic>{
      'event_id': 'evt-${_fingerprint(eventSeed).substring(0, 24)}',
      'kind': kind.name,
      'exception_type': _bounded(error.runtimeType.toString(), 120),
      'message_fingerprint': messageFingerprint,
      'stack_frames': _safeStackFrames(stackTrace),
      'route': _route,
      'correlation_id': _correlationId,
      'release': _bounded(release, 64),
      'occurred_at': occurredAt.toIso8601String(),
    };
    if (_buffer.length >= maxBufferedEvents) _buffer.removeAt(0);
    _buffer.add(event);
    await flush();
  }

  Future<void> flush() async {
    final transport = _transport;
    if (_isFlushing || transport == null) return;
    _isFlushing = true;
    try {
      while (_buffer.isNotEmpty) {
        try {
          await transport(Map<String, dynamic>.unmodifiable(_buffer.first));
          _buffer.removeAt(0);
        } catch (_) {
          return;
        }
      }
    } finally {
      _isFlushing = false;
    }
  }

  static List<String> _safeStackFrames(StackTrace stackTrace) {
    final framePattern = RegExp(
      r'(?:package:)?(?:[^\s()]+/)?([^/\s():]+\.dart):(\d+):(\d+)',
    );
    return stackTrace
        .toString()
        .split('\n')
        .where((line) => line.trim().isNotEmpty)
        .take(8)
        .map((line) {
          final match = framePattern.firstMatch(line);
          if (match == null) {
            return 'frame:${_fingerprint(line).substring(0, 16)}';
          }
          return '${match.group(1)}:${match.group(2)}:${match.group(3)}';
        })
        .toList(growable: false);
  }

  static String _fingerprint(String value) =>
      sha256.convert(utf8.encode(value)).toString();

  static String _bounded(String value, int limit) =>
      value.length <= limit ? value : value.substring(0, limit);
}

class ClientTelemetryNavigatorObserver extends NavigatorObserver {
  ClientTelemetryNavigatorObserver(this.reporter);

  final ClientErrorReporter reporter;

  void _record(Route<dynamic>? route) {
    final name = route?.settings.name;
    reporter.updateRoute(name == null ? null : '/$name');
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _record(route);
    super.didPush(route, previousRoute);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _record(previousRoute);
    super.didPop(route, previousRoute);
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    _record(newRoute);
    super.didReplace(newRoute: newRoute, oldRoute: oldRoute);
  }
}
