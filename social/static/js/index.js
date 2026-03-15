/* =============================================
   KISHIVIBE LOGIN PAGE — index.js
   Full AJAX login: no page reload on error,
   real-time field feedback, password toggle.
============================================= */
(function () {
  'use strict';

  /* ── XSS guard: escape any server-supplied text before inserting into DOM ── */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }


  /* ── Inject shake keyframe once ── */
  var shakeStyle = document.createElement('style');
  shakeStyle.textContent =
    '@keyframes kishivibeShake{0%,100%{transform:translateX(0)}' +
    '25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}';
  document.head.appendChild(shakeStyle);

  /* ── Splash → skeleton → card ── */
  window.addEventListener('load', function () {
    setTimeout(function () {
      var splash = document.getElementById('kishivibe-splash');
      if (splash) splash.classList.add('kishivibe-hidden');

      setTimeout(function () {
        var skel    = document.getElementById('kishivibe-skeleton');
        var content = document.getElementById('kishivibe-content');
        if (skel)    skel.style.display = 'none';
        if (content) content.classList.add('kishivibe-show');

        var uInp = document.getElementById('kishivibe-username');
        if (uInp) uInp.focus();
      }, 120);
    }, 700);
  });

  /* ── Helpers ── */

  /** Read the Django CSRF cookie */
  function getCsrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  /** Shake an element */
  function shake(el) {
    el.style.animation = 'none';
    void el.offsetWidth;
    el.style.animation = 'kishivibeShake 0.4s ease';
    setTimeout(function () { el.style.animation = ''; }, 400);
  }

  /**
   * Show the top banner.
   * type: 'error' | 'success' | 'info'
   */
  function showAlert(type, msg) {
    var banner = document.getElementById('kv-alert');
    if (!banner) return;

    var icons = { error: 'fa-exclamation-circle', success: 'fa-check-circle', info: 'fa-info-circle' };
    banner.className = 'kv-alert kv-alert-' + type;
    banner.innerHTML =
      '<i class="fas ' + (icons[type] || icons.info) + '" aria-hidden="true"></i> ' + escapeHtml(msg);
    banner.style.display = 'flex';

    /* kishivibe: Auto-dismiss success/info after 4 s */
    if (type !== 'error') {
      clearTimeout(banner._timer);
      banner._timer = setTimeout(function () {
        banner.style.display = 'none';
      }, 4000);
    }
  }

  function hideAlert() {
    var banner = document.getElementById('kv-alert');
    if (banner) banner.style.display = 'none';
  }

  /** Show inline field error */
  function showFieldError(elId, msg) {
    var el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = '<i class="fas fa-exclamation-circle" aria-hidden="true"></i> ' + escapeHtml(msg);
    el.style.display = 'flex';
  }

  function hideFieldError(elId) {
    var el = document.getElementById(elId);
    if (el) el.style.display = 'none';
  }

  function setInputState(inputEl, state) {
    inputEl.classList.remove('kv-input-error');
    if (state === 'error') inputEl.classList.add('kv-input-error');
  }

  /* ── DOM ready ── */
  document.addEventListener('DOMContentLoaded', function () {

    var form     = document.getElementById('kishivibe-form');
    var loginBtn = document.getElementById('kishivibe-login-btn');
    var uInp     = document.getElementById('kishivibe-username');
    var pInp     = document.getElementById('kishivibe-password');
    var toggle   = document.getElementById('kv-pass-toggle');

    /* ── Focus / blur border feedback ── */
    document.querySelectorAll('.kishivibe-input').forEach(function (inp) {
      inp.addEventListener('focus', function () {
        if (!this.classList.contains('kv-input-error')) {
          this.style.borderColor = 'var(--kishivibe-primary)';
          this.style.background  = 'var(--kishivibe-white)';
        }
        /* kishivibe: Clear field error on re-focus so user can try again */
        hideFieldError('kv-user-error');
        hideFieldError('kv-pass-error');
        setInputState(this, 'idle');
      });
      inp.addEventListener('blur', function () {
        if (!this.classList.contains('kv-input-error')) {
          this.style.borderColor = '';
          this.style.background  = '';
        }
      });
    });

    /* ── Password visibility toggle ── */
    if (toggle && pInp) {
      toggle.addEventListener('click', function () {
        var hidden = pInp.type === 'password';
        pInp.type = hidden ? 'text' : 'password';
        toggle.querySelector('i').className = hidden ? 'fas fa-eye-slash' : 'fas fa-eye';
      });
    }

    /* ── Clear banner when user starts typing ── */
    if (uInp) uInp.addEventListener('input', hideAlert);
    if (pInp) pInp.addEventListener('input', hideAlert);

    if (!form) return;

    /* ════════════════════════════════════════════════
       AJAX LOGIN SUBMIT
       POST to the same URL (index view) with
       X-Requested-With header so the view knows
       it's an AJAX call and returns JSON instead
       of a redirect or rendered HTML.
    ════════════════════════════════════════════════ */
    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var userVal = uInp ? uInp.value.trim() : '';
      var passVal = pInp ? pInp.value : '';

      /* ── Client-side empty guard ── */
      if (!userVal) {
        showFieldError('kv-user-error', 'Please enter your username or email');
        setInputState(uInp, 'error');
        shake(uInp);
        if (uInp) uInp.focus();
        return;
      }
      if (!passVal) {
        showFieldError('kv-pass-error', 'Please enter your password');
        setInputState(pInp, 'error');
        shake(pInp);
        if (pInp) pInp.focus();
        return;
      }

      /* ── Show spinner ── */
      loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Logging in…';
      loginBtn.disabled  = true;
      hideAlert();

      var body = new URLSearchParams();
      body.append('user_check', userVal);
      body.append('password',   passVal);
      body.append('csrfmiddlewaretoken', getCsrf());

      fetch(window.location.pathname + (window.location.search || ''), {
        method:  'POST',
        headers: {
          'Content-Type':     'application/x-www-form-urlencoded',
          'X-Requested-With': 'XMLHttpRequest',
          'Accept':           'application/json',
        },
        body: body.toString(),
        credentials: 'same-origin',
      })
      .then(function (res) {
        /* If server redirected (e.g. already logged in), follow it */
        if (res.redirected) {
          window.location.href = res.url;
          return null;
        }
        /* If response is not JSON (HTML error page etc), throw cleanly */
        var ct = res.headers.get('content-type') || '';
        if (!ct.includes('application/json')) {
          throw new Error('server_html:' + res.status);
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) return;  /* handled by redirect above */
        if (data.success) {
          loginBtn.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i> Welcome back!';
          showAlert('success', data.message || 'Login successful — redirecting…');
          setTimeout(function () {
            window.location.href = data.redirect || '/home';
          }, 600);
        } else {
          loginBtn.innerHTML = '<i class="fas fa-sign-in-alt" aria-hidden="true"></i> Log In';
          loginBtn.disabled  = false;
          showAlert('error', data.message || 'Invalid credentials. Please try again.');
          setInputState(uInp, 'error');
          setInputState(pInp, 'error');
          shake(form);
          if (pInp) { pInp.value = ''; pInp.focus(); }
          if (pInp && pInp.type === 'text') {
            pInp.type = 'password';
            if (toggle) toggle.querySelector('i').className = 'fas fa-eye';
          }
        }
      })
      .catch(function (err) {
        /* ── Network / server error ── */
        loginBtn.innerHTML = '<i class="fas fa-sign-in-alt" aria-hidden="true"></i> Log In';
        loginBtn.disabled  = false;
        showAlert('error', 'Connection error — please check your network and try again.');
        shake(form);
      });
    });

  });

})();

