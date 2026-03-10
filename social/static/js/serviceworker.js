/**
 * KVibe Service Worker v3.0
 * Strategies:
 *   - Static assets : Cache-first
 *   - HTML pages    : Network-first + offline fallback
 *   - Everything else: Network-first
 *
 * URLs verified against urls.py:
 *   home              → /home         (no trailing slash)
 *   notification_list → /list
 *   inbox             → /inbox        (no trailing slash)
 *   search            → /search       (no trailing slash)
 *   post              → /post         (no trailing slash)
 *   spotlight         → /spotlight/
 *   explore           → /explore/
 *   channel_create    → /create_channel
 */

'use strict';

// --- Cache names -------------------------------------------------------------

const CACHE_VERSION = 'v3';
const STATIC_CACHE  = 'kvibe-static-' + CACHE_VERSION;
const DYNAMIC_CACHE = 'kvibe-dynamic-' + CACHE_VERSION;
const OFFLINE_URL   = '/offline/';

// --- Pre-cache at install ----------------------------------------------------

const PRECACHE_URLS = [
  // --- Core navigation pages (verified from urls.py) ---
  '/home',           // {% url 'home' %}
  '/explore/',       // {% url 'explore' %}
  '/search',         // {% url 'search' %}
  '/post',           // {% url 'post' %}
  '/spotlight/',     // {% url 'spotlight' %}
  '/list',           // {% url 'notification_list' %}
  '/inbox',          // {% url 'inbox' %}
  '/create_channel', // {% url 'channel_create' %}

  // --- Static assets ---
  '/static/images/logo.jpg',
  '/static/images/chat.png',
  '/static/images/small.png',
  '/static/images/big.png',
  '/static/images/verify1.jpg',
];

// --- Install -----------------------------------------------------------------
// Cache the offline page FIRST separately so a single bad URL in PRECACHE_URLS
// never prevents the offline fallback from being stored.

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(function(cache) {
        // 1. Offline page — this MUST succeed
        return cache.add(OFFLINE_URL);
      })
      .then(function() {
        // 2. Everything else — skip individual failures silently
        return caches.open(STATIC_CACHE).then(function(cache) {
          return Promise.all(
            PRECACHE_URLS.map(function(url) {
              return cache.add(url).catch(function(err) {
                console.warn('[SW] Skipped precache (404?):', url, err);
              });
            })
          );
        });
      })
      .then(function() { return self.skipWaiting(); })
  );
});

// --- Activate - clean old caches ---------------------------------------------

self.addEventListener('activate', function(event) {
  var VALID = [STATIC_CACHE, DYNAMIC_CACHE];
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return !VALID.includes(n); })
             .map(function(n) {
               console.log('[SW] Deleting stale cache:', n);
               return caches.delete(n);
             })
      );
    }).then(function() { return self.clients.claim(); })
  );
});

// --- Fetch -------------------------------------------------------------------

self.addEventListener('fetch', function(event) {
  var request = event.request;
  var url = new URL(request.url);

  // Only same-origin GET requests
  if (url.origin !== self.location.origin) return;
  if (request.method !== 'GET') return;

  // Skip admin / auth / non-cacheable endpoints
  if (url.pathname.startsWith('/admin/') ||
      url.pathname.startsWith('/api/') ||
      url.pathname.startsWith('/accounts/') ||
      url.pathname.startsWith('/hx/') ||
      url.pathname.startsWith('/ws/')) return;

  // Static assets -- cache-first
  if (url.pathname.startsWith('/static/') ||
      /\.(js|css|woff2?|ttf|eot|ico|png|jpg|jpeg|gif|svg|webp)$/.test(url.pathname)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // HTML navigation -- network-first with offline fallback
  if (request.mode === 'navigate' ||
      (request.headers.get('Accept') || '').includes('text/html')) {
    event.respondWith(networkFirstWithOfflineFallback(request));
    return;
  }

  // Everything else -- network-first
  event.respondWith(networkFirst(request));
});

// --- Strategy: cache-first ---------------------------------------------------

function cacheFirst(request) {
  return caches.match(request).then(function(cached) {
    if (cached) return cached;
    return fetch(request).then(function(response) {
      if (response.ok) {
        caches.open(STATIC_CACHE).then(function(cache) {
          cache.put(request, response.clone());
        });
      }
      return response;
    }).catch(function() {
      return new Response('', { status: 204 });
    });
  });
}

// --- Strategy: network-first -------------------------------------------------

function networkFirst(request) {
  return fetch(request).then(function(response) {
    if (response.ok) {
      caches.open(DYNAMIC_CACHE).then(function(cache) {
        cache.put(request, response.clone());
      });
    }
    return response;
  }).catch(function() {
    return caches.match(request).then(function(cached) {
      return cached || new Response('Offline', { status: 503 });
    });
  });
}

// --- Strategy: network-first for HTML with offline fallback ------------------

function networkFirstWithOfflineFallback(request) {
  var requestUrl = request.url;
  return fetch(request).then(function(response) {
    // Cache every HTML page visited while online
    if (response.ok) {
      caches.open(DYNAMIC_CACHE).then(function(cache) {
        cache.put(request, response.clone());
      });
    }
    return response;
  }).catch(function() {
    return caches.match(request).then(function(cached) {

      // Page was previously visited — inject offline banner then serve from cache
      if (cached) {
        return cached.text().then(function(html) {
          var banner =
            '<style>' +
              '#kvibe-offline-banner{' +
                'position:fixed;top:54px;left:0;right:0;z-index:99998;' +
                'background:#fff3cd;border-bottom:2px solid #ffc107;' +
                'color:#664d03;text-align:center;padding:8px 16px;' +
                'font-family:-apple-system,BlinkMacSystemFont,sans-serif;' +
                'font-size:13px;font-weight:500;height:40px;' +
                'display:flex;align-items:center;justify-content:center;}' +
              /* Push mood filter bar + any sticky element below the banner */
              '.kvibe-mood-filter-bar{top:94px !important;}' +
            '<\/style>' +
            '<div id="kvibe-offline-banner">' +
              '<i class="fas fa-wifi" style="margin-right:8px;opacity:0.6;"></i>' +
              'You\'re offline \u2014 showing cached content' +
              '<button onclick="location.reload()" style="' +
                'margin-left:12px;padding:4px 10px;' +
                'border:1px solid #ffc107;background:transparent;' +
                'border-radius:12px;cursor:pointer;' +
                'font-size:12px;color:#664d03;">Retry</button>' +
            '</div>';
          var injected = html.replace('<body>', '<body>' + banner);
          return new Response(injected, {
            status: 200,
            headers: { 'Content-Type': 'text/html; charset=utf-8' }
          });
        });
      }

      // Page not in cache -- serve offline.html with injected path
      // Never use Response.redirect() as it causes redirect loops
      var attemptedPath = new URL(requestUrl).pathname;
      return caches.match(OFFLINE_URL).then(function(offlinePage) {
        if (offlinePage) {
          return offlinePage.text().then(function(html) {
            var injected = html.replace(
              '<body>',
              '<body><script>window.KVIBE_REQUESTED_PATH=' +
                JSON.stringify(attemptedPath) +
              ';<\/script>'
            );
            return new Response(injected, {
              status: 200,
              headers: { 'Content-Type': 'text/html; charset=utf-8' }
            });
          });
        }
        // offline.html itself not cached — show a better minimal fallback
        return new Response(
          '<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:40px">' +
          '<h2>You are offline</h2><p>Please check your connection and try again.</p>' +
          '<button onclick="location.reload()">Retry</button></body></html>',
          { status: 503, headers: { 'Content-Type': 'text/html' } }
        );
      });
    });
  });
}

// --- Background sync (future use) --------------------------------------------

self.addEventListener('sync', function(event) {
  if (event.tag === 'kvibe-sync') {
    console.log('[SW] Background sync triggered');
  }
});

// --- Push notifications ------------------------------------------------------

self.addEventListener('push', function(event) {
  if (!event.data) return;
  var data = {};
  try { data = event.data.json(); } catch(e) { data = { title: 'KVibe', body: event.data.text() }; }

  event.waitUntil(
    self.registration.showNotification(data.title || 'KVibe', {
      body:    data.body || 'You have a new notification',
      icon:    '/static/images/small.png',
      badge:   '/static/images/small.png',
      vibrate: [100, 50, 100],
      data:    { url: data.url || '/home' },
      actions: [
        { action: 'open',    title: 'Open KVibe' },
        { action: 'dismiss', title: 'Dismiss'    }
      ]
    })
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  if (event.action === 'dismiss') return;
  var targetUrl = (event.notification.data && event.notification.data.url) || '/home';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(wcs) {
      var existing = wcs.find(function(c) { return c.url === targetUrl && 'focus' in c; });
      if (existing) return existing.focus();
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
