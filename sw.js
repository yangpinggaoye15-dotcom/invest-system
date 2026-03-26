const CACHE_NAME = 'minervini-v1';
const STATIC_ASSETS = ['/', '/index.html', '/lightweight-charts.js', '/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
  ));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Only cache static assets, not API calls or data
  if (url.origin === self.location.origin && STATIC_ASSETS.some(a => url.pathname.endsWith(a.replace('/', '')))) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
