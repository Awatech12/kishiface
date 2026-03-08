/**
 * KVibe PWA Install Manager
 * ─────────────────────────
 * Detects as fast as possible whether the app is already installed,
 * then shows a native-style install banner only to users who haven't
 * installed yet.
 *
 * Detection methods used (in order of speed):
 *   1. CSS media query  display-mode: standalone   — synchronous, instant
 *   2. navigator.standalone                        — iOS Safari, synchronous
 *   3. navigator.getInstalledRelatedApps()         — Android Chrome, async ~50 ms
 *   4. beforeinstallprompt event                   — Chrome/Edge, fires early
 *   5. localStorage "pwa-installed" flag           — set on install, instant
 *
 * Usage: <script src="{% static 'js/pwa-install.js' %}"></script>
 *        Place this tag in <head> — no defer/async needed, it's tiny.
 */

(function () {
  'use strict';

  // ── Constants ──────────────────────────────────────────────────────────────
  const STORAGE_KEY      = 'kvibe-pwa-installed';
  const DISMISS_KEY      = 'kvibe-pwa-dismissed';
  const DISMISS_DAYS     = 3;          // Re-show banner after N days if dismissed
  const BANNER_DELAY_MS  = 800;        // ms after page load before banner appears
  const BANNER_ID        = 'kvibe-pwa-banner';

  // ── 1. Synchronous checks — run immediately (no waiting) ──────────────────

  function isRunningStandalone () {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||  // Android / desktop
      window.matchMedia('(display-mode: fullscreen)').matches  ||  // some Android
      window.matchMedia('(display-mode: minimal-ui)').matches  ||  // some browsers
      navigator.standalone === true ||                              // iOS Safari
      document.referrer.startsWith('android-app://')            ||  // TWA
      localStorage.getItem(STORAGE_KEY) === '1'                     // our own flag
    );
  }

  function wasDismissedRecently () {
    const ts = parseInt(localStorage.getItem(DISMISS_KEY) || '0', 10);
    return ts && (Date.now() - ts) < DISMISS_DAYS * 86400 * 1000;
  }

  // Bail out immediately if already installed — zero wasted work
  if (isRunningStandalone()) return;

  // ── State ──────────────────────────────────────────────────────────────────
  let deferredPrompt   = null;   // Saved beforeinstallprompt event
  let bannerShown      = false;

  // ── 2. beforeinstallprompt — fires within ~100 ms on Chrome/Edge ──────────
  //    We capture it as early as possible (script is in <head>, no defer).

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();           // Don't show browser's default mini-bar
    deferredPrompt = e;

    if (!bannerShown && !wasDismissedRecently()) {
      scheduleBanner();
    }
  }, { once: true });

  // ── 3. getInstalledRelatedApps — Android Chrome ~50 ms async check ────────
  //    Requires   "related_applications" in manifest.json  pointing to your app.
  //    If the native/TWA app is installed this returns a non-empty array.

  if ('getInstalledRelatedApps' in navigator) {
    navigator.getInstalledRelatedApps().then(function (apps) {
      if (apps && apps.length > 0) {
        // PWA / related app is installed — mark and hide banner
        localStorage.setItem(STORAGE_KEY, '1');
        hideBanner();
      }
    }).catch(function () { /* ignore — not critical */ });
  }

  // ── 4. appinstalled event — mark permanently after install ────────────────

  window.addEventListener('appinstalled', function () {
    localStorage.setItem(STORAGE_KEY, '1');
    hideBanner();
    deferredPrompt = null;
  });

  // ── Banner injection ───────────────────────────────────────────────────────

  function scheduleBanner () {
    if (bannerShown) return;
    // Wait until DOM is ready, then show after a short delay so it
    // doesn't flash on top of the initial page render.
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        setTimeout(showBanner, BANNER_DELAY_MS);
      });
    } else {
      setTimeout(showBanner, BANNER_DELAY_MS);
    }
  }

  function showBanner () {
    if (bannerShown || isRunningStandalone() || wasDismissedRecently()) return;
    bannerShown = true;

    injectStyles();

    const banner = document.createElement('div');
    banner.id            = BANNER_ID;
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Install KVibe app');

    // Detect iOS separately (no beforeinstallprompt, needs manual instructions)
    const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;

    banner.innerHTML = isIOS ? iosHTML() : androidHTML();
    document.body.appendChild(banner);

    // Animate in
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        banner.classList.add('kvibe-pwa-banner--visible');
      });
    });

    // Wire up buttons
    const installBtn = document.getElementById('kvibe-pwa-install-btn');
    const dismissBtn = document.getElementById('kvibe-pwa-dismiss-btn');

    if (installBtn) {
      installBtn.addEventListener('click', triggerInstall);
    }
    if (dismissBtn) {
      dismissBtn.addEventListener('click', dismissBanner);
    }
  }

  function hideBanner () {
    const banner = document.getElementById(BANNER_ID);
    if (banner) {
      banner.classList.remove('kvibe-pwa-banner--visible');
      setTimeout(function () { banner.remove(); }, 350);
    }
    bannerShown = false;
  }

  function dismissBanner () {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    hideBanner();
  }

  // ── Install trigger ────────────────────────────────────────────────────────

  async function triggerInstall () {
    if (!deferredPrompt) return;

    const installBtn = document.getElementById('kvibe-pwa-install-btn');
    if (installBtn) {
      installBtn.disabled     = true;
      installBtn.textContent  = 'Installing…';
    }

    deferredPrompt.prompt();

    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;

    if (outcome === 'accepted') {
      localStorage.setItem(STORAGE_KEY, '1');
      hideBanner();
    } else {
      // User declined — treat like dismiss
      dismissBanner();
    }
  }

  // ── HTML templates ─────────────────────────────────────────────────────────

  function androidHTML () {
    return [
      '<div class="kvibe-pwa-inner">',
      '  <div class="kvibe-pwa-app-row">',
      '    <img class="kvibe-pwa-icon" src="/static/images/small.png" alt="KishiVibe" ',
      '         onerror="this.style.display=\'none\'">',
      '    <div class="kvibe-pwa-info">',
      '      <div class="kvibe-pwa-name">KishiVibe</div>',
      '      <div class="kvibe-pwa-desc">Add to Home Screen for faster access</div>',
      '    </div>',
      '    <button class="kvibe-pwa-dismiss-x" id="kvibe-pwa-dismiss-btn" ',
      '            aria-label="Dismiss">&#x2715;</button>',
      '  </div>',
      '  <div class="kvibe-pwa-actions">',
      '    <button class="kvibe-pwa-btn-secondary" id="kvibe-pwa-dismiss-btn2">',
      '      Not now',
      '    </button>',
      '    <button class="kvibe-pwa-btn-primary" id="kvibe-pwa-install-btn">',
      '      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" ',
      '           stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">',
      '        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
      '        <polyline points="7 10 12 15 17 10"/>',
      '        <line x1="12" y1="15" x2="12" y2="3"/>',
      '      </svg>',
      '      Install App',
      '    </button>',
      '  </div>',
      '</div>',
    ].join('');
  }

  function iosHTML () {
    return [
      '<div class="kvibe-pwa-inner">',
      '  <div class="kvibe-pwa-app-row">',
      '    <img class="kvibe-pwa-icon" src="/static/images/small.png" alt="KishiVibe" ',
      '         onerror="this.style.display=\'none\'">',
      '    <div class="kvibe-pwa-info">',
      '      <div class="kvibe-pwa-name">Install KishiVibe</div>',
      '      <div class="kvibe-pwa-desc">Add to Home Screen for the best experience</div>',
      '    </div>',
      '    <button class="kvibe-pwa-dismiss-x" id="kvibe-pwa-dismiss-btn" ',
      '            aria-label="Dismiss">&#x2715;</button>',
      '  </div>',
      '  <div class="kvibe-pwa-ios-steps">',
      '    <div class="kvibe-pwa-ios-step">',
      '      <span class="kvibe-pwa-step-num">1</span>',
      '      Tap the <strong>Share</strong> button',
      '      <svg class="kvibe-pwa-ios-share" viewBox="0 0 24 24" fill="none" ',
      '           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
      '        <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>',
      '        <polyline points="16 6 12 2 8 6"/>',
      '        <line x1="12" y1="2" x2="12" y2="15"/>',
      '      </svg>',
      '    </div>',
      '    <div class="kvibe-pwa-ios-step">',
      '      <span class="kvibe-pwa-step-num">2</span>',
      '      Tap <strong>Add to Home Screen</strong>',
      '    </div>',
      '  </div>',
      '  <div class="kvibe-pwa-ios-arrow"></div>',
      '</div>',
    ].join('');
  }

  // ── Styles (injected once) ─────────────────────────────────────────────────

  function injectStyles () {
    if (document.getElementById('kvibe-pwa-styles')) return;

    const style = document.createElement('style');
    style.id    = 'kvibe-pwa-styles';
    style.textContent = [
      /* Banner base */
      '#' + BANNER_ID + '{',
      '  position:fixed;bottom:0;left:0;right:0;z-index:99999;',
      '  background:#fff;',
      '  border-top:1px solid #dbdbdb;',
      '  border-radius:16px 16px 0 0;',
      '  box-shadow:0 -4px 24px rgba(0,0,0,0.12);',
      '  padding:16px 16px 20px;',
      '  transform:translateY(110%);',          /* start off-screen */
      '  transition:transform 0.35s cubic-bezier(.32,1,.6,1);',
      '  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;',
      '  -webkit-font-smoothing:antialiased;',
      '  max-width:600px;',
      '  margin:0 auto;',
      '}',

      /* Slide-in class */
      '#' + BANNER_ID + '.kvibe-pwa-banner--visible{transform:translateY(0);}',

      /* App icon row */
      '.kvibe-pwa-inner{width:100%;}',
      '.kvibe-pwa-app-row{display:flex;align-items:center;gap:12px;margin-bottom:14px;}',
      '.kvibe-pwa-icon{width:48px;height:48px;border-radius:12px;object-fit:cover;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.12);}',
      '.kvibe-pwa-info{flex:1;min-width:0;}',
      '.kvibe-pwa-name{font-size:15px;font-weight:700;color:#262626;}',
      '.kvibe-pwa-desc{font-size:12px;color:#8e8e8e;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',

      /* Dismiss X */
      '.kvibe-pwa-dismiss-x{',
      '  background:none;border:none;cursor:pointer;padding:4px;',
      '  font-size:18px;color:#8e8e8e;line-height:1;flex-shrink:0;',
      '  border-radius:50%;width:30px;height:30px;',
      '  display:flex;align-items:center;justify-content:center;',
      '  transition:background 0.15s;',
      '}',
      '.kvibe-pwa-dismiss-x:hover{background:#f0f0f0;}',

      /* Action buttons */
      '.kvibe-pwa-actions{display:flex;gap:10px;}',
      '.kvibe-pwa-btn-secondary{',
      '  flex:1;padding:11px;border-radius:8px;border:1px solid #dbdbdb;',
      '  background:#fff;color:#262626;font-size:14px;font-weight:500;',
      '  cursor:pointer;transition:background 0.15s;',
      '}',
      '.kvibe-pwa-btn-secondary:hover{background:#f5f5f5;}',
      '.kvibe-pwa-btn-primary{',
      '  flex:2;padding:11px;border-radius:8px;border:none;',
      '  background:#0095f6;color:#fff;font-size:14px;font-weight:600;',
      '  cursor:pointer;display:flex;align-items:center;justify-content:center;gap:7px;',
      '  transition:background 0.15s,transform 0.1s;',
      '}',
      '.kvibe-pwa-btn-primary:hover{background:#0081d6;}',
      '.kvibe-pwa-btn-primary:active{transform:scale(0.97);}',
      '.kvibe-pwa-btn-primary:disabled{background:#b2d9fb;cursor:not-allowed;}',

      /* iOS steps */
      '.kvibe-pwa-ios-steps{display:flex;flex-direction:column;gap:10px;margin-bottom:8px;}',
      '.kvibe-pwa-ios-step{',
      '  display:flex;align-items:center;gap:10px;',
      '  font-size:13px;color:#262626;',
      '}',
      '.kvibe-pwa-step-num{',
      '  width:22px;height:22px;border-radius:50%;',
      '  background:#0095f6;color:#fff;',
      '  font-size:11px;font-weight:700;',
      '  display:flex;align-items:center;justify-content:center;flex-shrink:0;',
      '}',
      '.kvibe-pwa-ios-share{width:18px;height:18px;margin-left:4px;color:#0095f6;flex-shrink:0;}',

      /* iOS arrow pointing down to Safari share bar */
      '.kvibe-pwa-ios-arrow{',
      '  width:0;height:0;margin:8px auto 0;',
      '  border-left:10px solid transparent;',
      '  border-right:10px solid transparent;',
      '  border-top:10px solid #0095f6;',
      '}',

      /* Respect bottom nav height on mobile */
      '@media(max-width:767px){',
      '  #' + BANNER_ID + '{padding-bottom:calc(20px + env(safe-area-inset-bottom));}',
      '}',
    ].join('\n');

    document.head.appendChild(style);
  }

  // ── Wire up secondary dismiss button (rendered inside androidHTML) ─────────
  // We use event delegation because the button is injected after this code runs.

  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'kvibe-pwa-dismiss-btn2') {
      dismissBanner();
    }
  });

})();
