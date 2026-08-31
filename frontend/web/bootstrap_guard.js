// The production build does not register a service worker. Remove legacy
// workers and their caches once so a previous release cannot pin stale code.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((registrations) => {
    for (const registration of registrations) registration.unregister();
  });
}
if ('caches' in window) {
  caches.keys().then((names) => {
    for (const name of names) caches.delete(name);
  });
}
