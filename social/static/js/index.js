
(function () {
  "use strict";

  /* kishivibe: Inject shake keyframes once at startup */
  var kishivibeShakeStyle = document.createElement("style");
  kishivibeShakeStyle.textContent =
    "@keyframes kishivibeShake{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}";
  document.head.appendChild(kishivibeShakeStyle);


  window.addEventListener("load", function () {
    setTimeout(function () {
      /* kishivibe: Fade out splash */
      var kishivibeSplash = document.getElementById("kishivibe-splash");
      if (kishivibeSplash) {
        kishivibeSplash.classList.add("kishivibe-hidden");
      }

      /* kishivibe: Replace skeleton with real content */
      setTimeout(function () {
        var kishivibeSkeleton = document.getElementById("kishivibe-skeleton");
        var kishivibeContent  = document.getElementById("kishivibe-content");

        if (kishivibeSkeleton) kishivibeSkeleton.style.display = "none";
        if (kishivibeContent)  kishivibeContent.classList.add("kishivibe-show");

        /* kishivibe: Auto-focus so user can type immediately */
        var kishivibeUsername = document.getElementById("kishivibe-username");
        if (kishivibeUsername) kishivibeUsername.focus();
      }, 120);

    }, 700); /* kishivibe: 700 ms splash → snappier than 1000 ms */
  });

  document.addEventListener("DOMContentLoaded", function () {
    var kishivibeForm     = document.getElementById("kishivibe-form");
    var kishivibeLoginBtn = document.getElementById("kishivibe-login-btn");
    var kishivibeInputs   = document.querySelectorAll(".kishivibe-input");

    /* kishivibe: Input focus/blur visual feedback */
    kishivibeInputs.forEach(function (kishivibeInput) {
      kishivibeInput.addEventListener("focus", function () {
        this.style.borderColor = "var(--kishivibe-primary)";
        this.style.background  = "var(--kishivibe-white)";
      });

      kishivibeInput.addEventListener("blur", function () {
        this.style.borderColor = "";
        this.style.background  = "";
      });
    });

    if (!kishivibeForm) return;

    /* kishivibe: Submit — validate then show loading state */
    kishivibeForm.addEventListener("submit", function (e) {
      var kishivibeUsernameVal = document.getElementById("kishivibe-username").value.trim();
      var kishivibePasswordVal = document.getElementById("kishivibe-password").value.trim();

      /* kishivibe: Client-side empty-field guard */
      if (!kishivibeUsernameVal || !kishivibePasswordVal) {
        e.preventDefault();

        /* kishivibe: Shake form to signal missing fields */
        kishivibeForm.style.animation = "none";
        void kishivibeForm.offsetWidth; /* kishivibe: force reflow to restart animation */
        kishivibeForm.style.animation = "kishivibeShake 0.4s ease";
        setTimeout(function () {
          kishivibeForm.style.animation = "";
        }, 400);

        return false;
      }

      /* kishivibe: Show spinner on button while server processes */
      if (kishivibeLoginBtn) {
        kishivibeLoginBtn.innerHTML =
          '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Logging in…';
        kishivibeLoginBtn.disabled = true;
      }
    });
  });

})();
