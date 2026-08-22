# Marko Flutter conventions

This client favors a small, explicit structure that is easy to navigate without
knowing Clean Architecture terminology.

## Stack

- Flutter stable
- Riverpod with manual providers; no code generation
- GoRouter
- Plain Dart JSON models
- Firebase Authentication plus the custom Marko FastAPI REST backend

## Directory structure

```text
lib/
├── main.dart                 # runApp and MaterialApp
├── core/                     # infrastructure used by several features
│   ├── api_client.dart
│   ├── app_router.dart
│   ├── app_theme.dart
│   ├── environment.dart
│   ├── firebase_auth_client.dart
│   ├── marko_ui.dart
│   └── widgets/
│       ├── marko_button.dart
│       └── marko_cached_image.dart
└── features/
    ├── auth/
    │   ├── auth_models.dart
    │   ├── auth_api.dart
    │   ├── auth_controller.dart
    │   └── auth_page.dart
    ├── dashboard/
    │   └── dashboard_page.dart   # top bar plus the single main screen
    └── products/                 # the entire app: catalog, filters, import, competitor prices, details
        ├── products_models.dart
        ├── products_api.dart
        ├── products_controller.dart
        ├── products_page.dart
        └── widgets/
            ├── product_card.dart
            ├── source_panel.dart
            ├── competitor_results.dart
            ├── product_details_panel.dart
            └── help_overlay.dart
```

The client has one main screen: the product catalog. Everything the user sees
is a product, its details, competitor price analytics, or catalog import sources.

Keep one flat directory per feature. Create a `widgets/` subdirectory only when
a page becomes difficult to scan or a widget is reused by multiple pages in the
same feature. Do not pre-create layers or empty folders.

`MaterialApp` stays in `main.dart`. Do not create `lib/app` or `lib/shared`.

## Responsibilities

- `*_models.dart`: only data objects and small display getters closely related
  to that data. Add `copyWith` only when state is actually updated immutably.
  Do not add equality, `empty`, or serialization boilerplate without a use.
- `*_api.dart`: endpoint paths, request bodies, and response parsing. API files
  use the single `apiClientProvider`; widgets never perform HTTP calls.
- `*_controller.dart`: Riverpod state and user actions. Controllers call API
  classes and expose simple state to the UI.
- `*_page.dart`: declarative Flutter UI and local UI-only state such as text
  controllers, selected tabs, focus, and password visibility.
- `core/`: only code used by more than one feature. Feature-specific helpers
  stay inside their feature.

This is a practical separation, not a strict dependency ceremony. A feature may
have fewer files when it is small.

## Riverpod

- Declare providers manually. Do not use `@riverpod`, `build_runner`, Freezed,
  or generated JSON serializers.
- Use `ref.watch` while building reactive UI.
- Use `ref.read` in callbacks and controller methods.
- Keep network loading, action errors, and polling in controllers rather than
  duplicating them across widgets.

## Routing

- Routes and auth redirects live together in `core/app_router.dart` so the full
  navigation flow is visible in one short file.
- Use named routes when passing parameters.
- Do not use `Navigator.push` for application navigation.
- Unauthenticated users must be redirected before protected pages are built.

## Backend and authentication

- Firebase is used only for authentication. Business data still goes through
  FastAPI; Flutter never accesses PostgreSQL or Firebase databases directly.
- `firebase_auth` persists and refreshes the session. `ApiClient` attaches the
  current Firebase ID token and retries once after a forced token refresh.
- FastAPI verifies the JWT and owns local users, workspaces, stores, and jobs.
- Never place secret/service-role keys in Flutter, logs, or source control.

## UI

- Keep colors, typography, radii, and component styles in `app_theme.dart`.
  Read semantic product colors through `MarkoTheme.of(context)` instead of
  putting hex values in pages. Spacing, radii, elevation and the monospace
  layer are the constants `MarkoSpace`, `MarkoRadius`, `MarkoShadow` and
  `MarkoType` in the same file — no raw numbers in pages.
- OEM numbers, article codes, prices and timestamps render in `MarkoType`
  monospace; narrative UI stays in the sans stack. Sentence case everywhere.
- Reusable product-wide surfaces and messages live in `core/marko_ui.dart`.
  Standalone interactive components live in `core/widgets/`. Feature-specific
  presentation widgets stay private in their page file.
- Network images use `MarkoCachedImage` so cache hashing, loading shimmer,
  fallbacks, and preload behavior remain consistent across features.
- Prefer straightforward private widget classes in the same page file.
- Split a file when it approaches roughly 300–400 lines or contains a genuinely
  reusable unit; do not split every button into its own file.
- Forms dismiss the keyboard when the user taps outside.
- Business validation and remote errors belong in the controller/backend;
  simple input behavior may remain in the page.

## Before finishing

```bash
dart format lib test
flutter analyze
flutter test
flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=YOUR_PROJECT_ID \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
```

There must be no generated `.g.dart`/`.freezed.dart` files and no directories
named `lib/app` or `lib/shared`.
