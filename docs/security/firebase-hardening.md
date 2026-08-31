# Firebase / Google Identity hardening checklist

Project in scope: `marko-4941e`.

Repository evidence shows that Marko uses Firebase Core and Firebase
Authentication. It does not import Firestore, Realtime Database or Cloud Storage
SDKs. That does not prove those services are unused by every application sharing
the Firebase project, so deny-all rules must not be deployed until the project
inventory is confirmed.

## Authentication

- Keep only the providers intentionally used by Marko: Google and, if product
  policy requires it, email/password. Disable anonymous, phone and other unused
  providers.
- Enable email-enumeration protection. The frontend no longer probes whether an
  email exists and uses generic sign-in/reset messages, so this control should
  not break the current UI.
- Authentication > Settings > Authorized domains: retain only the Firebase auth
  domain and production domains actually required by the OAuth flow. Remove
  `localhost` from the production project after preview/local testing uses a
  separate Firebase project.
- Verify Google OAuth redirect URIs and JavaScript origins. Delete obsolete
  preview, developer and vendor origins.
- Tighten Identity Toolkit sign-in quotas enough to curb brute force while
  preserving measured peak traffic. Alert on quota errors and unusual failed
  login volume.
- Require MFA for Firebase/Google Cloud administrators. If customer MFA is
  required, upgrade to Authentication with Identity Platform and release it as a
  separate tested product change.
- Review project Owner/Editor/IAM members and service accounts quarterly. Prefer
  least-privilege roles and workload identity; do not create downloadable service
  account keys unless there is no safer mechanism.

## API key and application registration

The Firebase browser API key is public by design and is not an authentication
secret. In Google Cloud Console > APIs & Services > Credentials:

- confirm it is the key created for the Marko web app;
- restrict its API allowlist to the Firebase/Identity APIs actually required;
- do not reuse it for unrelated Google APIs;
- use a separate, appropriately restricted key for any non-Firebase API;
- verify that no server, FCM legacy or service-account secret is present in the
  client bundle.

HTTP-referrer restrictions can be used only after testing the full Firebase Auth
flow on the Firebase auth handler domain and production domain. An incorrect
restriction can break Google sign-in and password recovery.

## App Check

App Check is defense in depth, not a replacement for Firebase Authentication,
backend authorization or rate limits. For the web app:

1. Upgrade Authentication to Identity Platform if required by the current App
   Check-for-Authentication feature.
2. Register the production web app with reCAPTCHA Enterprise.
3. Add the Flutter App Check client and backend token verification in a preview
   environment.
4. Monitor App Check metrics without enforcement first.
5. Enable enforcement per service only after legitimate traffic is clean and a
   rollback owner is present.

Enabling enforcement before the deployed client sends valid tokens would lock
out all users. It therefore must not be bundled invisibly into the first security
release.

## Data-service rules

If the Firebase console confirms that Firestore and Cloud Storage are unused by
all applications in `marko-4941e`, deploy the reference deny-all rules from
`security/firebase/`. If another application shares the project, inventory its
collections/buckets and write tested least-privilege rules instead.

Use the Firebase Emulator Suite and CI tests before every rules deployment. Save
the currently deployed rule versions as rollback evidence.

## Console evidence required for closure

- provider list and authorized-domain list;
- email-enumeration protection status;
- Identity Toolkit quota and alert configuration;
- API-key API restrictions;
- App Check registration, metrics and enforcement status;
- Firestore, Realtime Database and Storage service/rule status;
- IAM principals and service-account key inventory;
- UTC timestamp and reviewer identity.

Until this evidence is collected from an authenticated console session, the
Firebase portion of the external audit remains **prepared but not verified**.
