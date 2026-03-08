/**
 * KVibe Service Worker
 * Version: 1.0.0
 * Strategy: Cache-first for static assets, Network-first for pages,
 *            offline fallback served from cache on failure.
 */

'use strict';

// ─── Cache Configuration ──────────────────────────────────────────────────────

const CACHE_VERSION  = 'v1';
const STATIC_CACHE   = `kvibe-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE  = `kvibe-dynamic-${CACHE_VERSION}`;
const OFFLINE_URL    = '/offline/';

/**
 * Static assets pre-cached at install time.
 * Add any CSS/JS/image paths that must work offline.
 */
const PRECACHE_URLS = [
  OFFLINE_URL,
  '/static/images/logo.jpg',
  '/static/images/small.png',
  '/static/images/big.png',
];

// ─── Install ──────────────────────────────────────────────────────────────────

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())   // Activate immediately on first install
      .catch((err) => console.error('[SW] Pre-cache failed:', err))
  );
});

// ─── Activate ─────────────────────────────────────────────────────────────────

self.addEventListener('activate', (event) => {
  const VALID_CACHES = [STATIC_CACHE, DYNAMIC_CACHE];

  event.waitUntil(
    caches.keys()
      .then((cacheNames) =>
        Promise.all(
          cacheNames
            .filter((name) => !VALID_CACHES.includes(name))
            .map((name) => {
              console.log('[SW] Deleting stale cache:', name);
              return caches.delete(name);
            })
        )
      )
      .then(() => self.clients.claim())  // Take control of all open tabs
  );
});

// ─── Fetch ────────────────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin requests (skip CDN, Cloudinary, etc.)
  if (url.origin !== self.location.origin) return;

  // Skip non-GET requests (POST/PUT/DELETE must always go to network)
  if (request.method !== 'GET') return;

  // Skip Django admin, API endpoints, and auth routes
  if (
    url.pathname.startsWith('/admin/') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/accounts/') ||
    url.pathname.startsWith('/load-more-posts/')
  ) return;

  // ── Static assets: Cache-first ──────────────────────────────────────────────
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname.match(/\.(js|css|woff2?|ttf|eot|ico|png|jpg|jpeg|gif|svg|webp)$/)
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── HTML navigation: Network-first with offline fallback ────────────────────
  if (request.mode === 'navigate' || request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(networkFirstWithOfflineFallback(request));
    return;
  }

  // ── Everything else: Network-first ─────────────────────────────────────────
  event.respondWith(networkFirst(request));
});

// ─── Strategies ───────────────────────────────────────────────────────────────

/**
 * Cache-first: serve from cache, fall back to network and update cache.
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Static asset not available offline — return empty 204
    return new Response('', { status: 204 });
  }
}

/**
 * Network-first: try network, fall back to cache, then offline page.
 */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached ?? new Response('Offline', { status: 503 });
  }
}

/**
 * Network-first for HTML pages with full offline page fallback.
 */
async function networkFirstWithOfflineFallback(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      // Cache the home page so we have something meaningful offline
      if (new URL(request.url).pathname === '/') {
        const cache = await caches.open(DYNAMIC_CACHE);
        cache.put(request, response.clone());
      }
    }
    return response;
  } catch {
    // Network failed — try cached version of same page first
    const cached = await caches.match(request);
    if (cached) return cached;

    // Final fallback: offline page
    const offlinePage = await caches.match(OFFLINE_URL);
    return offlinePage ?? new Response(
      '<h1>You are offline</h1>',
      { status: 503, headers: { 'Content-Type': 'text/html' } }
    );
  }
}

// ─── Background Sync (optional future use) ────────────────────────────────────

self.addEventListener('sync', (event) => {
  if (event.tag === 'kvibe-sync') {
    console.log('[SW] Background sync triggered');
    // Future: replay queued POST requests (likes, follows, etc.)
  }
});

// ─── Push Notifications (future use) ─────────────────────────────────────────

self.addEventListener('push', (event) => {
  if (!event.data) return;

  let data = {};
  try { data = event.data.json(); } catch { data = { title: 'KVibe', body: event.data.text() }; }

  const options = {
    body:    data.body    || 'You have a new notification',
    icon:    '/static/images/small.png',
    badge:   '/static/images/small.png',
    vibrate: [100, 50, 100],
    data:    { url: data.url || '/' },
    actions: [
      { action: 'open',    title: 'Open KVibe' },
      { action: 'dismiss', title: 'Dismiss'    },
    ],
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'KVibe', options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'dismiss') return;

  const targetUrl = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((windowClients) => {
        const existing = windowClients.find((c) => c.url === targetUrl && 'focus' in c);
        if (existing) return existing.focus();
        if (clients.openWindow) return clients.openWindow(targetUrl);
      })
  );
});
