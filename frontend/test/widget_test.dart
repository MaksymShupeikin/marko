import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/firebase_auth_client.dart';
import 'package:marko_client/main.dart';

void main() {
  testWidgets('renders the email and OAuth sign-in screen', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authClientProvider.overrideWithValue(_SignedOutAuthClient()),
        ],
        child: const MarkoApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Marko'), findsOneWidget);
    expect(find.text('Почта'), findsOneWidget);
    expect(find.text('Пароль'), findsOneWidget);
    expect(find.text('Продолжить с Google'), findsOneWidget);
    expect(find.byType(SelectionArea), findsOneWidget);
  });

  testWidgets('allows rendered text to be selected and copied', (tester) async {
    dynamic clipboardData = <String, dynamic>{'text': null};
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (methodCall) async {
        if (methodCall.method == 'Clipboard.setData') {
          clipboardData = methodCall.arguments;
        }
        if (methodCall.method == 'Clipboard.getData') {
          return clipboardData;
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authClientProvider.overrideWithValue(_SignedOutAuthClient()),
        ],
        child: const MarkoApp(),
      ),
    );
    await tester.pumpAndSettle();

    final paragraph = tester.renderObject<RenderParagraph>(
      find.descendant(
        of: find.text('С возвращением'),
        matching: find.byType(RichText),
      ),
    );
    final gesture = await tester.startGesture(
      _textOffsetToPosition(paragraph, 2),
      kind: PointerDeviceKind.mouse,
    );
    addTearDown(gesture.removePointer);
    await tester.pump();
    await gesture.moveTo(_textOffsetToPosition(paragraph, 8));
    await gesture.up();
    await tester.pump();

    expect(paragraph.selections, isNotEmpty);
    expect(paragraph.selections.single.isCollapsed, isFalse);

    final modifier =
        defaultTargetPlatform == TargetPlatform.macOS ||
            defaultTargetPlatform == TargetPlatform.iOS
        ? LogicalKeyboardKey.meta
        : LogicalKeyboardKey.control;
    await tester.sendKeyDownEvent(modifier);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.keyC);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.keyC);
    await tester.sendKeyUpEvent(modifier);
    await tester.pump();

    expect((clipboardData as Map<String, dynamic>)['text'], 'возвра');
  });
}

Offset _textOffsetToPosition(RenderParagraph paragraph, int offset) {
  const caret = Rect.fromLTWH(0, 0, 2, 20);
  final localOffset =
      paragraph.getOffsetForCaret(TextPosition(offset: offset), caret) +
      Offset(0, paragraph.preferredLineHeight);
  return paragraph.localToGlobal(localOffset) + const Offset(0, -2);
}

class _SignedOutAuthClient implements AuthClient {
  @override
  Stream<AuthSession?> get authStateChanges => const Stream.empty();

  @override
  AuthSession? get currentSession => null;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => null;

  @override
  Future<AuthSession> login(String email, String password) =>
      throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogle() => throw UnimplementedError();

  @override
  Future<void> logout() async {}

  @override
  Future<void> register(String email, String password) =>
      throw UnimplementedError();
}
