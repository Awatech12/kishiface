/**
 * KVibe Service Worker v2.0
 * Strategies:
 *   - Static assets     : Cache-first
 *   - HTML pages        : Network-first + offline fallback
 *   - /load-more-posts/ : Network-first + saves posts JSON to kvibe-posts cache
 *   - Everything else   : Network-first
 */

'use strict';

// --- Cache names -------------------------------------------------------------

const CACHE_VERSION = 'v2';
const STATIC_CACHE  = 'kvibe-static-' + CACHE_VERSION;
const DYNAMIC_CACHE = 'kvibe-dynamic-' + CACHE_VERSION;
const POSTS_CACHE   = 'kvibe-posts-' + CACHE_VERSION;
const OFFLINE_URL   = '/offline/';
const POSTS_KEY     = '/kvibe-cached-posts-data/';

// --- Pre-cache at install ----------------------------------------------------
// All key navigation pages + static assets cached immediately on SW install
// so they are available offline even before the user visits them.

const PRECACHE_URLS = [
  // Offline fallback page
  OFFLINE_URL,

  // --- Core navigation pages (from footer nav bar) ---
  '/',               // Home       {% url 'home' %}
  '/explore/',       // Explore    {% url 'explore' %}
  '/post/',          // Create     {% url 'post' %}
  '/spotlight/',     // Spotlight  {% url 'spotlight' %}
  '/notification/',  // Alerts     {% url 'notification_list' %}

  // --- Header nav links ---
  '/channel/create/', // Channel create  {% url 'channel_create' %}
  '/inbox/',          // Messages        {% url 'inbox' %}

  // --- Static assets used in header/footer ---
  '/static/images/logo.jpg',
  '/static/images/chat.png',
  '/static/images/small.png',
  '/static/images/big.png',
];

// --- Install -----------------------------------------------------------------

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(function(cache) { return cache.addAll(PRECACHE_URLS); })
      .then(function() { return self.skipWaiting(); })
      .catch(function(err) { console.error('[SW] Pre-cache failed:', err); })
  );
});

// --- Activate - clean old caches ---------------------------------------------

self.addEventListener('activate', function(event) {
  var VALID = [STATIC_CACHE, DYNAMIC_CACHE, POSTS_CACHE];
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

  // /load-more-posts/ -- intercept to cache post data
  if (url.pathname.startsWith('/load-more-posts/')) {
    event.respondWith(fetchAndCachePosts(request));
    return;
  }

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

// --- Strategy: fetch posts and save to POSTS_CACHE --------------------------

function fetchAndCachePosts(request) {
  return fetch(request).then(function(response) {
    if (response.ok) {
      var clone = response.clone();
      clone.json().then(function(data) {
        if (data.posts && data.posts.length) {
          caches.open(POSTS_CACHE).then(function(cache) {
            var existing = [];
            cache.match(POSTS_KEY).then(function(prev) {
              if (prev) {
                prev.json().then(function(old) {
                  existing = old || [];
                }).catch(function() {}).finally(function() {
                  saveMerged(cache, data.posts, existing);
                });
              } else {
                saveMerged(cache, data.posts, existing);
              }
            }).catch(function() {
              saveMerged(cache, data.posts, existing);
            });
          }).catch(function() {});
        }
      }).catch(function() {});
    }
    return response;
  }).catch(function() {
    return new Response(JSON.stringify({ posts: [], has_next: false }), {
      headers: { 'Content-Type': 'application/json' }
    });
  });
}

function saveMerged(cache, newPosts, existing) {
  var merged = newPosts.concat(existing);
  var seen   = {};
  var unique = [];
  for (var i = 0; i < merged.length; i++) {
    var id = merged[i].post_id;
    if (!seen[id]) {
      seen[id] = true;
      unique.push(merged[i]);
    }
    if (unique.length >= 50) break;
  }
  cache.put(POSTS_KEY, new Response(JSON.stringify(unique), {
    headers: { 'Content-Type': 'application/json' }
  }));
  console.log('[SW] Cached ' + unique.length + ' posts for offline');
}

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
      // Page was previously visited -- serve it from cache
      if (cached) return cached;

      // Page not in cache -- serve the offline page but inject the attempted
      // path into the HTML so offline.html knows what page was requested.
      // We NEVER use Response.redirect() here as it causes redirect loops.
      var attemptedPath = new URL(requestUrl).pathname;
      return caches.match(OFFLINE_URL).then(function(offlinePage) {
        if (offlinePage) {
          return offlinePage.text().then(function(html) {
            // Inject a small script at the top of <body> so offline.html
            // can read window.KVIBE_REQUESTED_PATH without any redirect
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
        return new Response(
          '<h1>You are offline</h1>',
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
      data:    { url: data.url || '/' },
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
  var targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(wcs) {
      var existing = wcs.find(function(c) { return c.url === targetUrl && 'focus' in c; });
      if (existing) return existing.focus();
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
