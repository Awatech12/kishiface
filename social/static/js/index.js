/* =============================================
   KISHIVIBE LOGIN PAGE — index.js
   Normal form POST — no AJAX.
   Handles: splash, skeleton, password toggle,
   shake on empty submit, loading spinner.
============================================= */
(function () {
  'use strict';

  /* ── Shake keyframe ── */
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

        /* Auto-focus username field */
        var uInp = document.getElementById('kishivibe-username');
        if (uInp) uInp.focus();
      }, 120);
    }, 700);
  });

  document.addEventListener('DOMContentLoaded', function () {

    var form     = document.getElementById('kishivibe-form');
    var loginBtn = document.getElementById('kishivibe-login-btn');
    var uInp     = document.getElementById('kishivibe-username');
    var pInp     = document.getElementById('kishivibe-password');
    var toggle   = document.getElementById('kv-pass-toggle');

    /* ── Focus / blur border feedback ── */
    document.querySelectorAll('.kishivibe-input').forEach(function (inp) {
      inp.addEventListener('focus', function () {
        this.style.borderColor = 'var(--kishivibe-primary)';
        this.style.background  = 'var(--kishivibe-white)';
      });
      inp.addEventListener('blur', function () {
        this.style.borderColor = '';
        this.style.background  = '';
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

    if (!form) return;

    /* ── Submit: validate empty fields then show spinner ── */
    form.addEventListener('submit', function (e) {
      var userVal = uInp ? uInp.value.trim() : '';
      var passVal = pInp ? pInp.value.trim() : '';

      /* Client-side empty guard */
      if (!userVal || !passVal) {
        e.preventDefault();
        form.style.animation = 'none';
        void form.offsetWidth;
        form.style.animation = 'kishivibeShake 0.4s ease';
        setTimeout(function () { form.style.animation = ''; }, 400);

        if (!userVal && uInp) uInp.classList.add('kv-input-error');
        if (!passVal && pInp) pInp.classList.add('kv-input-error');
        return false;
      }

      /* Show loading spinner — form submits normally after this */
      if (loginBtn) {
        loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Logging in\u2026';
        loginBtn.disabled = true;
      }
    });

    /* ── Clear error state when user types ── */
    if (uInp) uInp.addEventListener('input', function () { this.classList.remove('kv-input-error'); });
    if (pInp) pInp.addEventListener('input', function () { this.classList.remove('kv-input-error'); });

  });

})();

