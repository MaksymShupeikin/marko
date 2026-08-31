import 'dart:io';

Never _fail(String message) {
  stderr.writeln('Web artifact verification failed: $message');
  exit(1);
}

void main(List<String> arguments) {
  if (arguments.length != 1) _fail('expected one BUILD_DIR argument');
  final build = Directory(arguments.single);
  if (!build.existsSync()) _fail('build directory does not exist');

  String read(String relative) {
    final file = File('${build.path}/$relative');
    if (!file.existsSync()) _fail('missing $relative');
    return file.readAsStringSync();
  }

  final index = read('index.html');
  final manifest = read('manifest.json');
  final headers = read('_headers');
  final redirects = read('_redirects');
  final robots = read('robots.txt');
  read('sitemap.xml');
  read('404.html');
  read('about/index.html');

  if ('$index\n$manifest'.contains('A new Flutter project.')) {
    _fail('Flutter placeholder metadata remains');
  }
  if (RegExp(r'<script(?![^>]*\bsrc=)', caseSensitive: false).hasMatch(index)) {
    _fail('index.html contains an inline script incompatible with strict CSP');
  }
  for (final required in [
    'Strict-Transport-Security:',
    'Content-Security-Policy:',
    "frame-ancestors 'none'",
    'X-Frame-Options: DENY',
    'Permissions-Policy:',
    'Cross-Origin-Opener-Policy:',
    "'sha256-ior38pot2y2xKR0mRpdVTgX2efww2Rmy0xUUJ5GkoUg='",
    "'sha256-pgBvvN9AhuQ6TmYKoXen82lBdMudCw0oKGu+CZSF0Gc='",
    'https://www.gstatic.com',
  ]) {
    if (!headers.contains(required)) _fail('_headers lacks $required');
  }
  if (headers.replaceAll("'wasm-unsafe-eval'", '').contains("'unsafe-eval'")) {
    _fail('script CSP contains unrestricted unsafe-eval');
  }
  if (redirects.split('\n').any((line) => line.trim().startsWith('/* '))) {
    _fail('catch-all SPA rewrite would turn unknown paths into HTTP 200');
  }
  if (!robots.startsWith('User-agent: *\n')) _fail('robots.txt is malformed');
  final fontManifest = read('assets/FontManifest.json');
  for (final font in ['Roboto', 'Roboto Mono']) {
    if (!fontManifest.contains('"family":"$font"')) {
      _fail('$font is not bundled in the web artifact');
    }
  }

  final mainFiles = build
      .listSync()
      .whereType<File>()
      .where(
        (file) => RegExp(r'/main\.[0-9a-f]{16}\.dart\.js$').hasMatch(file.path),
      )
      .toList();
  if (mainFiles.length != 1) {
    _fail('expected exactly one fingerprinted main bundle');
  }
  if (File('${build.path}/main.dart.js').existsSync()) {
    _fail('unfingerprinted main.dart.js remains');
  }
  final mainName = mainFiles.single.uri.pathSegments.last;
  if (!read('flutter_bootstrap.js').contains('"mainJsPath":"$mainName"')) {
    _fail('Flutter bootstrap does not reference $mainName');
  }

  const secretMarkers = [
    'sk-proj-',
    'CLOUDFLARE_TUNNEL_TOKEN=',
    'POSTGRES_PASSWORD=',
  ];
  const textExtensions = {'.css', '.html', '.js', '.json', '.txt', '.xml'};
  for (final entity in build.listSync(recursive: true).whereType<File>()) {
    if (!textExtensions.any(entity.path.endsWith)) continue;
    final text = entity.readAsStringSync();
    for (final marker in secretMarkers) {
      if (text.contains(marker)) {
        _fail('${entity.path} contains secret marker $marker');
      }
    }
  }
  stdout.writeln('Web artifact verified: $mainName');
}
