/**
 * KishiHub PWA Install Manager
 * ─────────────────────────────
 * Forces install prompt on every browser that supports PWA installation.
 *
 * Detection methods used (in order of speed):
 *   1. CSS media query  display-mode: standalone   — synchronous, instant
 *   2. navigator.standalone                        — iOS Safari, synchronous
 *   3. navigator.getInstalledRelatedApps()         — Android Chrome, async ~50 ms
 *   4. beforeinstallprompt event                   — Chrome/Edge/Samsung, fires early
 *   5. localStorage "pwa-installed" flag           — set on install, instant
 *   6. Manual instructions banner                  — Firefox, Opera, other browsers
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

  // ── Browser / OS detection ─────────────────────────────────────────────────

  var ua = navigator.userAgent || '';

  function _detect () {
    var isIOS        = /iphone|ipad|ipod/i.test(ua) && !window.MSStream;
    var isSafariIOS  = isIOS && /safari/i.test(ua) && !/crios|fxios|opios/i.test(ua);
    // Chrome on iOS opens its own sheet but still can't use beforeinstallprompt
    var isChromeIOS  = isIOS && /crios/i.test(ua);
    var isAndroid    = /android/i.test(ua);
    var isFirefox    = /firefox|fxios/i.test(ua) && !/seamonkey/i.test(ua);
    var isSamsung    = /samsungbrowser/i.test(ua);
    var isOpera      = /opr\//i.test(ua) || /opera/i.test(ua);
    var isEdge       = /edg\//i.test(ua);
    var isChrome     = /chrome/i.test(ua) && !isEdge && !isSamsung && !isOpera;
    var isBrave      = isChrome && (navigator.brave !== undefined);
    // Browsers that fire beforeinstallprompt natively
    var hasNativePrompt = isChrome || isEdge || isSamsung || isOpera || isBrave;

    return {
      isIOS, isSafariIOS, isChromeIOS,
      isAndroid, isFirefox, isSamsung,
      isOpera, isEdge, isChrome, isBrave,
      hasNativePrompt,
    };
  }

  var B = _detect();

  // ── 1. Synchronous checks — run immediately (no waiting) ──────────────────

  function isRunningStandalone () {
    return (
      window.matchMedia('(display-mode: standalone)').matches  ||
      window.matchMedia('(display-mode: fullscreen)').matches  ||
      window.matchMedia('(display-mode: minimal-ui)').matches  ||
      navigator.standalone === true                            ||
      document.referrer.startsWith('android-app://')          ||
      localStorage.getItem(STORAGE_KEY) === '1'
    );
  }

  function wasDismissedRecently () {
    var ts = parseInt(localStorage.getItem(DISMISS_KEY) || '0', 10);
    return ts && (Date.now() - ts) < DISMISS_DAYS * 86400 * 1000;
  }

  // Bail out immediately if already installed
  if (isRunningStandalone()) return;

  // ── State ──────────────────────────────────────────────────────────────────
  var deferredPrompt   = null;
  var bannerShown      = false;

  // ── 2. beforeinstallprompt — Chrome / Edge / Samsung / Opera ──────────────

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;

    if (!bannerShown && !wasDismissedRecently()) {
      scheduleBanner('native');
    }
  }, { once: true });

  // ── 3. getInstalledRelatedApps — Android Chrome async check ───────────────

  if ('getInstalledRelatedApps' in navigator) {
    navigator.getInstalledRelatedApps().then(function (apps) {
      if (apps && apps.length > 0) {
        localStorage.setItem(STORAGE_KEY, '1');
        hideBanner();
      }
    }).catch(function () {});
  }

  // ── 4. appinstalled event ─────────────────────────────────────────────────

  window.addEventListener('appinstalled', function () {
    localStorage.setItem(STORAGE_KEY, '1');
    hideBanner();
    deferredPrompt = null;
  });

  // ── 5. Fallback for browsers without beforeinstallprompt ─────────────────
  //    After DOM is ready, if no native prompt fired and browser supports PWA,
  //    show manual instructions.

  function onDOMReady (fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  onDOMReady(function () {
    // Wait a bit longer than the native prompt timeout to avoid race
    setTimeout(function () {
      if (bannerShown || isRunningStandalone() || wasDismissedRecently()) return;
      // Only show manual banner if native prompt hasn't been captured
      if (!deferredPrompt) {
        var mode = _getManualMode();
        if (mode) scheduleBanner(mode);
      }
    }, BANNER_DELAY_MS + 600);
  });

  /**
   * Returns the manual instruction mode for browsers that don't fire
   * beforeinstallprompt, or null if unsupported.
   */
  function _getManualMode () {
    // iOS Safari — show Share → Add to Home Screen steps
    if (B.isSafariIOS) return 'ios-safari';
    // Chrome on iOS — must use Share sheet too
    if (B.isChromeIOS) return 'ios-chrome';
    // Firefox on Android
    if (B.isFirefox && B.isAndroid) return 'firefox-android';
    // Firefox on desktop
    if (B.isFirefox && !B.isAndroid && !B.isIOS) return 'firefox-desktop';
    // Any other browser on Android that doesn't have native prompt
    if (B.isAndroid && !B.hasNativePrompt) return 'android-generic';
    return null;
  }

  // ── Banner scheduling ──────────────────────────────────────────────────────

  function scheduleBanner (mode) {
    if (bannerShown) return;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        setTimeout(function () { showBanner(mode); }, BANNER_DELAY_MS);
      });
    } else {
      setTimeout(function () { showBanner(mode); }, BANNER_DELAY_MS);
    }
  }

  function showBanner (mode) {
    if (bannerShown || isRunningStandalone() || wasDismissedRecently()) return;
    bannerShown = true;

    injectStyles();

    var banner = document.createElement('div');
    banner.id = BANNER_ID;
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Install KishiHub app');

    var html = '';
    switch (mode) {
      case 'native':          html = nativeHTML();         break;
      case 'ios-safari':      html = iosSafariHTML();      break;
      case 'ios-chrome':      html = iosChromeHTML();      break;
      case 'firefox-android': html = firefoxAndroidHTML(); break;
      case 'firefox-desktop': html = firefoxDesktopHTML(); break;
      case 'android-generic': html = androidGenericHTML(); break;
      default:                html = nativeHTML();
    }

    banner.innerHTML = html;
    document.body.appendChild(banner);

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        banner.classList.add('kvibe-pwa-banner--visible');
      });
    });

    var installBtn = document.getElementById('kvibe-pwa-install-btn');
    var dismissBtn = document.getElementById('kvibe-pwa-dismiss-btn');

    if (installBtn) installBtn.addEventListener('click', triggerInstall);
    if (dismissBtn) dismissBtn.addEventListener('click', dismissBanner);
  }

  function hideBanner () {
    var banner = document.getElementById(BANNER_ID);
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

  // ── Install trigger (native prompt) ───────────────────────────────────────

  async function triggerInstall () {
    if (!deferredPrompt) return;

    var installBtn = document.getElementById('kvibe-pwa-install-btn');
    if (installBtn) {
      installBtn.disabled    = true;
      installBtn.textContent = 'Installing…';
    }

    deferredPrompt.prompt();
    var result = await deferredPrompt.userChoice;
    deferredPrompt = null;

    if (result.outcome === 'accepted') {
      localStorage.setItem(STORAGE_KEY, '1');
      hideBanner();
    } else {
      dismissBanner();
    }
  }

  // ── HTML templates ─────────────────────────────────────────────────────────

  var _icon = '<img class="kvibe-pwa-icon" src="/static/images/small.png" alt="KishiHub" onerror="this.style.display=\'none\'">';
  var _downloadSVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';

  function _appRow (title, desc) {
    return (
      '<div class="kvibe-pwa-app-row">' +
        _icon +
        '<div class="kvibe-pwa-info">' +
          '<div class="kvibe-pwa-name">' + title + '</div>' +
          '<div class="kvibe-pwa-desc">' + desc + '</div>' +
        '</div>' +
        '<button class="kvibe-pwa-dismiss-x" id="kvibe-pwa-dismiss-btn" aria-label="Dismiss">&#x2715;</button>' +
      '</div>'
    );
  }

  function _step (num, html) {
    return (
      '<div class="kvibe-pwa-step">' +
        '<span class="kvibe-pwa-step-num">' + num + '</span>' +
        '<span>' + html + '</span>' +
      '</div>'
    );
  }

  // Chrome / Edge / Samsung / Opera — native prompt available
  function nativeHTML () {
    return (
      '<div class="kvibe-pwa-inner">' +
        _appRow('KishiHub', 'Add to Home Screen for faster access') +
        '<div class="kvibe-pwa-actions">' +
          '<button class="kvibe-pwa-btn-secondary" id="kvibe-pwa-dismiss-btn2">Not now</button>' +
          '<button class="kvibe-pwa-btn-primary" id="kvibe-pwa-install-btn">' +
            _downloadSVG + 'Install App' +
          '</button>' +
        '</div>' +
      '</div>'
    );
  }

  // iOS Safari — Share → Add to Home Screen
  function iosSafariHTML () {
    var shareSVG =
      '<svg class="kvibe-pwa-ios-share" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>' +
        '<polyline points="16 6 12 2 8 6"/>' +
        '<line x1="12" y1="2" x2="12" y2="15"/>' +
      '</svg>';

    return (
      '<div class="kvibe-pwa-inner">' +
        _appRow('Install KishiHub', 'Add to Home Screen for the best experience') +
        '<div class="kvibe-pwa-steps">' +
          _step(1, 'Tap the <strong>Share</strong> button ' + shareSVG + ' at the bottom of Safari') +
          _step(2, 'Scroll down and tap <strong>Add to Home Screen</strong>') +
          _step(3, 'Tap <strong>Add</strong> to confirm') +
        '</div>' +
        '<div class="kvibe-pwa-ios-arrow"></div>' +
      '</div>'
    );
  }

  // Chrome on iOS — Share → Add to Home Screen (same as Safari but different wording)
  function iosChromeHTML () {
    var shareSVG =
      '<svg class="kvibe-pwa-ios-share" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>' +
        '<polyline points="16 6 12 2 8 6"/>' +
        '<line x1="12" y1="2" x2="12" y2="15"/>' +
      '</svg>';

    return (
      '<div class="kvibe-pwa-inner">' +
        _appRow('Install KishiHub', 'Add to your Home Screen') +
        '<div class="kvibe-pwa-steps">' +
          _step(1, 'Tap ' + shareSVG + ' <strong>Share</strong> in the Chrome menu') +
          _step(2, 'Tap <strong>Add to Home Screen</strong>') +
          _step(3, 'Tap <strong>Add</strong>') +
        '</div>' +
        '<div class="kvibe-pwa-ios-arrow"></div>' +
      '</div>'
    );
  }

  // Firefox on Android — three-dot menu → Install
  function firefoxAndroidHTML () {
    var menuSVG =
      '<svg class="kvibe-pwa-menu-icon" viewBox="0 0 24 24" fill="currentColor" width="16" height="16">' +
        '<circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/>' +
      '</svg>';

    return (
      '<div class="kvibe-pwa-inner">' +
        _appRow('Install KishiHub', 'Get the app on your Home Screen') +
        '<div class="kvibe-pwa-steps">' +
          _step(1, 'Tap the ' + menuSVG + ' <strong>menu (⋮)</strong> in Firefox') +
          _step(2, 'Tap <strong>Install</strong> or <strong>Add to Home Screen</strong>') +
          _step(3, 'Tap <strong>Add</strong> to confirm') +
        '</div>' +
      '</div>'
    );
  }

  // Firefox on Desktop — address bar icon or menu
  function firefoxDesktopHTML () {
    return (
      '<div class="kvibe-pwa-inner">' +
        _appRow('Install KishiHub', 'Install as a desktop app') +
        '<div class="kvibe-pwa-steps kvibe-pwa-steps--horizontal">' +
          _step(1, 'Click the <strong>install icon</strong> <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> in the address bar') +
          _step(2, 'Or open Firefox <strong>menu → Install</strong>') +
          _step(3, 'Click <strong>Install</strong> to confirm') +
        '</div>' +
        '<div class="kvibe-pwa-actions kvibe-pwa-actions--single">' +
          '<button class="kvibe-pwa-btn-secondary" id="kvibe-pwa-dismiss-btn2">Got it</button>' +
        '</div>' +
      '</div>'
    );
  }

  // Generic Android browser (Opera Mini, UC, etc.)
  function androidGenericHTML () {
    return (
      '<div class="kvibe-pwa-inner">' +
        _appRow('Install KishiHub', 'Add to Home Screen for the best experience') +
        '<div class="kvibe-pwa-steps">' +
          _step(1, 'Open your browser <strong>menu (⋮ or ☰)</strong>') +
          _step(2, 'Tap <strong>Add to Home Screen</strong> or <strong>Install App</strong>') +
          _step(3, 'Tap <strong>Add</strong> to confirm') +
        '</div>' +
      '</div>'
    );
  }

  // ── Styles ─────────────────────────────────────────────────────────────────

  function injectStyles () {
    if (document.getElementById('kvibe-pwa-styles')) return;

    var style = document.createElement('style');
    style.id = 'kvibe-pwa-styles';
    style.textContent = [

      /* Banner base */
      '#' + BANNER_ID + '{',
      '  position:fixed;bottom:0;left:0;right:0;z-index:99999;',
      '  background:#fff;',
      '  border-top:1px solid #dbdbdb;',
      '  border-radius:16px 16px 0 0;',
      '  box-shadow:0 -4px 24px rgba(0,0,0,0.12);',
      '  padding:16px 16px 20px;',
      '  transform:translateY(110%);',
      '  transition:transform 0.35s cubic-bezier(.32,1,.6,1);',
      '  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;',
      '  -webkit-font-smoothing:antialiased;',
      '  max-width:600px;',
      '  margin:0 auto;',
      '}',

      '#' + BANNER_ID + '.kvibe-pwa-banner--visible{transform:translateY(0);}',

      '.kvibe-pwa-inner{width:100%;}',
      '.kvibe-pwa-app-row{display:flex;align-items:center;gap:12px;margin-bottom:14px;}',
      '.kvibe-pwa-icon{width:48px;height:48px;border-radius:12px;object-fit:cover;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.12);}',
      '.kvibe-pwa-info{flex:1;min-width:0;}',
      '.kvibe-pwa-name{font-size:15px;font-weight:700;color:#262626;}',
      '.kvibe-pwa-desc{font-size:12px;color:#8e8e8e;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',

      '.kvibe-pwa-dismiss-x{',
      '  background:none;border:none;cursor:pointer;padding:4px;',
      '  font-size:18px;color:#8e8e8e;line-height:1;flex-shrink:0;',
      '  border-radius:50%;width:30px;height:30px;',
      '  display:flex;align-items:center;justify-content:center;',
      '  transition:background 0.15s;',
      '}',
      '.kvibe-pwa-dismiss-x:hover{background:#f0f0f0;}',

      /* Action row */
      '.kvibe-pwa-actions{display:flex;gap:10px;margin-top:4px;}',
      '.kvibe-pwa-actions--single{justify-content:flex-end;}',
      '.kvibe-pwa-btn-secondary{',
      '  flex:1;padding:11px;border-radius:8px;border:1px solid #dbdbdb;',
      '  background:#fff;color:#262626;font-size:14px;font-weight:500;',
      '  cursor:pointer;transition:background 0.15s;',
      '}',
      '.kvibe-pwa-actions--single .kvibe-pwa-btn-secondary{flex:0;padding:11px 22px;}',
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

      /* Step list */
      '.kvibe-pwa-steps{display:flex;flex-direction:column;gap:10px;margin-bottom:8px;}',
      '.kvibe-pwa-steps--horizontal{gap:8px;}',
      '.kvibe-pwa-step{',
      '  display:flex;align-items:center;gap:10px;',
      '  font-size:13px;color:#262626;line-height:1.4;',
      '}',
      '.kvibe-pwa-step-num{',
      '  width:22px;height:22px;border-radius:50%;flex-shrink:0;',
      '  background:#0095f6;color:#fff;',
      '  font-size:11px;font-weight:700;',
      '  display:flex;align-items:center;justify-content:center;',
      '}',

      /* Inline icons inside steps */
      '.kvibe-pwa-ios-share{width:18px;height:18px;margin:0 3px;color:#0095f6;flex-shrink:0;vertical-align:middle;}',
      '.kvibe-pwa-menu-icon{margin:0 3px;color:#262626;vertical-align:middle;}',

      /* iOS bottom arrow */
      '.kvibe-pwa-ios-arrow{',
      '  width:0;height:0;margin:8px auto 0;',
      '  border-left:10px solid transparent;',
      '  border-right:10px solid transparent;',
      '  border-top:10px solid #0095f6;',
      '}',

      /* Safe area on mobile */
      '@media(max-width:767px){',
      '  #' + BANNER_ID + '{padding-bottom:calc(20px + env(safe-area-inset-bottom));}',
      '}',

    ].join('\n');

    document.head.appendChild(style);
  }

  // ── Event delegation for secondary dismiss button ──────────────────────────

  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'kvibe-pwa-dismiss-btn2') {
      dismissBanner();
    }
  });

})();
