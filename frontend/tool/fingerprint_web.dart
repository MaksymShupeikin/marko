import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

void main(List<String> arguments) {
  if (arguments.length != 1) {
    stderr.writeln('Usage: dart run tool/fingerprint_web.dart BUILD_DIR');
    exitCode = 64;
    return;
  }
  final build = Directory(arguments.single);
  final source = File('${build.path}/main.dart.js');
  if (!source.existsSync()) {
    stderr.writeln('Missing ${source.path}; run flutter build web first.');
    exitCode = 66;
    return;
  }

  final bootstrap = File('${build.path}/flutter_bootstrap.js');
  final original = bootstrap.readAsStringSync();
  const marker = '"mainJsPath":"main.dart.js"';
  if (!original.contains(marker)) {
    stderr.writeln(
      'Flutter bootstrap does not contain the expected entrypoint.',
    );
    exitCode = 65;
    return;
  }
  final bytes = source.readAsBytesSync();
  final digest = sha256.convert(bytes).toString().substring(0, 16);
  final fingerprintedName = 'main.$digest.dart.js';
  final fingerprinted = File('${build.path}/$fingerprintedName');
  final staleBundlePattern = RegExp(r'^main\.[0-9a-f]{16}\.dart\.js$');
  for (final entity in build.listSync().whereType<File>()) {
    final name = entity.uri.pathSegments.last;
    if (staleBundlePattern.hasMatch(name)) {
      entity.deleteSync();
    }
  }
  source.renameSync(fingerprinted.path);
  bootstrap.writeAsStringSync(
    original.replaceFirst(marker, '"mainJsPath":"$fingerprintedName"'),
    encoding: utf8,
  );
  stdout.writeln(fingerprintedName);
}
