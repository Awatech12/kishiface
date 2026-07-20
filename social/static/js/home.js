/// ===== GLOBAL MEDIA TRACKING =====
let kvibeCurrentlyPlayingMedia = null;

// ===== FEED IMAGE LIGHTBOX =====
(function () {
  'use strict';

  var _flbImages   = [];   // [{src, postId, avatar, username, profileUrl, time}]
  var _flbIndex    = 0;
  var _flbScale    = 1;
  var _flbDragStartX = 0;
  var _flbDragging   = false;
  // pinch-to-zoom
  var _flbPinchStartDist = 0;
  var _flbPinchLastScale = 1;
  // swipe-down to dismiss
  var _flbSwipeStartY = 0;

  /* ── open ─────────────────────────────────────────────────────────────── */
  function kvibeOpenFeedLightbox(images, startIndex) {
    _flbImages = images;
    _flbIndex  = startIndex || 0;
    _flbScale  = 1;

    var lb = document.getElementById('kvibeFeedLightbox');
    if (!lb) return;

    _flbRender();
    lb.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Swipe-down on the whole lightbox
    lb.addEventListener('touchstart', _flbSwipeStart, { passive: true });
    lb.addEventListener('touchmove',  _flbSwipeMove,  { passive: false });
    lb.addEventListener('touchend',   _flbSwipeEnd,   { passive: true  });
  }

  /* ── close ────────────────────────────────────────────────────────────── */
  function kvibeCloseFeedLightbox() {
    var lb  = document.getElementById('kvibeFeedLightbox');
    var img = document.getElementById('kvibeFeedLbImg');
    if (!lb) return;
    lb.classList.remove('open');
    if (img) { img.src = ''; img.style.transform = 'scale(1)'; img.classList.remove('zoomed'); }
    _flbScale = 1;
    document.body.style.overflow = '';
    lb.removeEventListener('touchstart', _flbSwipeStart);
    lb.removeEventListener('touchmove',  _flbSwipeMove);
    lb.removeEventListener('touchend',   _flbSwipeEnd);
  }

  /* ── navigate ─────────────────────────────────────────────────────────── */
  function kvibeFlbGo(idx) {
    if (_flbImages.length === 0) return;
    if (idx < 0) idx = _flbImages.length - 1;
    if (idx >= _flbImages.length) idx = 0;
    _flbIndex = idx;
    _flbScale = 1;
    _flbRender();
  }
  function kvibeFlbPrev() { kvibeFlbGo(_flbIndex - 1); }
  function kvibeFlbNext() { kvibeFlbGo(_flbIndex + 1); }

  /* ── render current slide ─────────────────────────────────────────────── */
  function _flbRender() {
    var item    = _flbImages[_flbIndex];
    var img     = document.getElementById('kvibeFeedLbImg');
    var avEl    = document.getElementById('kvibeFeedLbAvatar');
    var nameEl  = document.getElementById('kvibeFeedLbUsername');
    var linkEl  = document.getElementById('kvibeFeedLbAuthorLink');
    var prevBtn = document.getElementById('kvibeFeedLbPrev');
    var nextBtn = document.getElementById('kvibeFeedLbNext');
    var dotsEl  = document.getElementById('kvibeFeedLbDots');
    var counter = document.getElementById('kvibeFeedLbCounter');

    if (!item) return;

    if (img) {
      img.style.transition = 'none';
      img.src = item.src;
      img.style.transform = 'scale(1)';
      img.classList.remove('zoomed');
    }

    if (avEl)   { avEl.src = item.avatar || ''; avEl.style.display = item.avatar ? '' : 'none'; }
    if (nameEl) nameEl.textContent = item.username || '';
    if (linkEl) linkEl.href = item.profileUrl || '#';

    var total = _flbImages.length;
    if (prevBtn) prevBtn.hidden = (total <= 1);
    if (nextBtn) nextBtn.hidden = (total <= 1);

    // dots
    if (dotsEl) {
      if (total <= 1) {
        dotsEl.style.display = 'none';
      } else {
        dotsEl.style.display = 'flex';
        dotsEl.innerHTML = '';
        for (var i = 0; i < total; i++) {
          var d = document.createElement('button');
          d.className = 'kvibe-feed-lb-dot' + (i === _flbIndex ? ' active' : '');
          d.setAttribute('aria-label', 'Image ' + (i + 1));
          (function (idx) { d.addEventListener('click', function () { kvibeFlbGo(idx); }); })(i);
          dotsEl.appendChild(d);
        }
      }
    }

    // counter (only shown for multi-image)
    if (counter) {
      counter.textContent = total > 1 ? (_flbIndex + 1) + ' / ' + total : '';
      counter.style.display = total > 1 ? '' : 'none';
    }
  }

  /* ── double-tap / double-click zoom ────────────────────────────────────── */
  var _flbLastTap = 0;
  function _flbTapZoom(e) {
    var now = Date.now();
    var img = document.getElementById('kvibeFeedLbImg');
    if (!img) return;
    if (now - _flbLastTap < 280) {
      e.preventDefault();
      _flbScale = _flbScale > 1 ? 1 : 2.5;
      img.style.transition = 'transform 0.22s ease';
      img.style.transform  = 'scale(' + _flbScale + ')';
      img.classList.toggle('zoomed', _flbScale > 1);
    }
    _flbLastTap = now;
  }

  /* ── pinch-to-zoom ───────────────────────────────────────────────────── */
  function _flbPinchStart(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      _flbPinchStartDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      _flbPinchLastScale = _flbScale;
    }
  }
  function _flbPinchMove(e) {
    var img = document.getElementById('kvibeFeedLbImg');
    if (!img) return;
    if (e.touches.length === 2) {
      e.preventDefault();
      var dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      _flbScale = Math.min(4, Math.max(1, _flbPinchLastScale * (dist / _flbPinchStartDist)));
      img.style.transition = 'none';
      img.style.transform  = 'scale(' + _flbScale + ')';
      img.classList.toggle('zoomed', _flbScale > 1);
    }
  }
  function _flbPinchEnd() {
    if (_flbScale < 1.05) {
      _flbScale = 1;
      var img = document.getElementById('kvibeFeedLbImg');
      if (img) { img.style.transform = 'scale(1)'; img.classList.remove('zoomed'); }
    }
  }

  /* ── swipe-down to dismiss ───────────────────────────────────────────── */
  function _flbSwipeStart(e) {
    if (_flbScale > 1) return;
    _flbSwipeStartY = e.touches[0].clientY;
  }
  function _flbSwipeMove(e) {
    if (_flbScale > 1 || e.touches.length !== 1) return;
    var dy = e.touches[0].clientY - _flbSwipeStartY;
    if (Math.abs(dy) > 8) {
      e.preventDefault();
      var lb = document.getElementById('kvibeFeedLightbox');
      if (lb) lb.style.opacity = Math.max(0.3, 1 - Math.abs(dy) / 280);
    }
  }
  function _flbSwipeEnd(e) {
    var dy = e.changedTouches[0].clientY - _flbSwipeStartY;
    var lb = document.getElementById('kvibeFeedLightbox');
    if (Math.abs(dy) > 80) {
      kvibeCloseFeedLightbox();
    } else {
      if (lb) lb.style.opacity = '';
    }
  }

  /* ── keyboard navigation ─────────────────────────────────────────────── */
  document.addEventListener('keydown', function (e) {
    var lb = document.getElementById('kvibeFeedLightbox');
    if (!lb || !lb.classList.contains('open')) return;
    if (e.key === 'Escape')      kvibeCloseFeedLightbox();
    else if (e.key === 'ArrowLeft')  kvibeFlbPrev();
    else if (e.key === 'ArrowRight') kvibeFlbNext();
  });

  /* ── attach touch-zoom to body on open ──────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    var body = document.getElementById('kvibeFeedLbBody');
    var img  = document.getElementById('kvibeFeedLbImg');
    if (!body || !img) return;

    img.addEventListener('touchstart',  _flbTapZoom,   { passive: false });
    img.addEventListener('dblclick',    _flbTapZoom,   { passive: false });
    body.addEventListener('touchstart', _flbPinchStart, { passive: false });
    body.addEventListener('touchmove',  _flbPinchMove,  { passive: false });
    body.addEventListener('touchend',   _flbPinchEnd,   { passive: true  });
  });

  /* ── expose globally ────────────────────────────────────────────────── */
  window.kvibeOpenFeedLightbox  = kvibeOpenFeedLightbox;
  window.kvibeCloseFeedLightbox = kvibeCloseFeedLightbox;
  window.kvibeFlbPrev           = kvibeFlbPrev;
  window.kvibeFlbNext           = kvibeFlbNext;
  window.kvibeFlbGo             = kvibeFlbGo;
}());


// ===== OLD LIGHTBOX SHIM (kept for any existing callers) =====
var kvibeLightboxImages  = [];
var kvibeLightboxIndex   = 0;
var kvibeLightboxPostData = {};

function kvibeOpenLightbox(images, startIndex, postData) {
  // Map old signature to new feed lightbox
  var mapped = images.map(function (img) {
    return {
      src:        img.src,
      avatar:     (postData && postData.avatar)     || '',
      username:   (postData && postData.username)   || '',
      profileUrl: (postData && postData.profileUrl) || '#',
      time:       (postData && postData.time)       || ''
    };
  });
  kvibeOpenFeedLightbox(mapped, startIndex || 0);
}
function kvibeCloseLightbox() { kvibeCloseFeedLightbox(); }
function kvibeLightboxPrev()  { kvibeFlbPrev(); }
function kvibeLightboxNext()  { kvibeFlbNext(); }
function kvibeLightboxGoTo(i) { kvibeFlbGo(i); }
function kvibeLightboxUpdate() {}


// ===== VIDEO CONTROLS & SYNC =====
function kvibeTogglePlayPause(videoId, event) {
    if (event) event.stopPropagation();
    const video = document.getElementById(videoId);
    if (!video) return;

    if (video.paused) {
        document.querySelectorAll('video, audio').forEach(m => {
            if (m !== video && !m.paused) m.pause();
        });
        video.play().catch(err => console.warn("Autoplay blocked or failed", err));
    } else {
        video.pause();
    }
}

function kvibeSeekVideo(videoId, seconds) {
    const video = document.getElementById(videoId);
    if (video) video.currentTime += seconds;
}

document.addEventListener('play', (e) => {
    if (e.target.tagName === 'VIDEO') {
        const container = e.target.closest('.kvibe-video-container');
        if (container) container.classList.remove('paused');
    }
}, true);

document.addEventListener('pause', (e) => {
    if (e.target.tagName === 'VIDEO') {
        const container = e.target.closest('.kvibe-video-container');
        if (container) container.classList.add('paused');
    }
}, true);


// ===== CAROUSEL =====

/**
 * Navigate to a specific slide index (absolute, not relative).
 * Called by arrow buttons and touch/drag handlers.
 */
function kvibeSlideCarousel(postId, index) {
    var carousel = document.getElementById('kvibe-carousel-' + postId);
    if (!carousel) return;
    var track = carousel.querySelector('.kvibe-image-track');
    if (!track) return;
    var total = parseInt(carousel.dataset.total, 10) || 1;

    var nextIdx = index;
    if (nextIdx < 0) nextIdx = 0;             // clamp: no wrap-around on edge
    if (nextIdx >= total) nextIdx = total - 1;

    carousel.dataset.slide = nextIdx;
    track.classList.remove('dragging');
    track.style.transform = 'translateX(-' + nextIdx * 100 + '%)';

    // Dots
    carousel.querySelectorAll('.kvibe-indicator').forEach(function (dot, i) {
        dot.classList.toggle('active', i === nextIdx);
    });
    // Counter
    var counter = carousel.querySelector('.kvibe-slide-counter');
    if (counter) counter.textContent = (nextIdx + 1) + ' / ' + total;

    // Arrow disabled state
    var prev = carousel.querySelector('.kvibe-carousel-prev');
    var next = carousel.querySelector('.kvibe-carousel-next');
    if (prev) prev.disabled = (nextIdx === 0);
    if (next) next.disabled = (nextIdx === total - 1);
}

/* ── Inject desktop arrow buttons ─────────────────────────────────────── */
function kvibeInjectCarouselArrows(carousel) {
    var total = parseInt(carousel.dataset.total || '1', 10);
    if (total <= 1) return;
    if (carousel.querySelector('.kvibe-carousel-prev')) return; // idempotent

    var postId = carousel.id.replace('kvibe-carousel-', '');

    var prev = document.createElement('button');
    prev.className = 'kvibe-carousel-prev';
    prev.setAttribute('aria-label', 'Previous image');
    prev.disabled = true; // starts on slide 0
    prev.innerHTML = '<i class="fas fa-chevron-left"></i>';
    prev.addEventListener('click', function (e) {
        e.stopPropagation();
        kvibeSlideCarousel(postId, parseInt(carousel.dataset.slide, 10) - 1);
    });

    var next = document.createElement('button');
    next.className = 'kvibe-carousel-next';
    next.setAttribute('aria-label', 'Next image');
    next.innerHTML = '<i class="fas fa-chevron-right"></i>';
    next.addEventListener('click', function (e) {
        e.stopPropagation();
        kvibeSlideCarousel(postId, parseInt(carousel.dataset.slide, 10) + 1);
    });

    carousel.appendChild(prev);
    carousel.appendChild(next);
}

/* ── Attach swipe + live-drag to a single carousel (idempotent) ─────────── */
function kvibeInitCarouselSwipe(carousel) {
    if (carousel.dataset.swipeInit === '1') return;
    carousel.dataset.swipeInit = '1';

    var postId = carousel.id.replace('kvibe-carousel-', '');
    var track  = carousel.querySelector('.kvibe-image-track');
    if (!track) return;

    // ── Touch ──────────────────────────────────────────────────────────────
    var touchStartX = 0;
    var touchStartY = 0;
    var touchLive   = false;
    var totalW      = 0;

    carousel.addEventListener('touchstart', function (e) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        touchLive   = true;
        totalW      = carousel.offsetWidth;
        track.classList.add('dragging');
    }, { passive: true });

    carousel.addEventListener('touchmove', function (e) {
        if (!touchLive || e.touches.length !== 1) return;
        var dx = e.touches[0].clientX - touchStartX;
        var dy = e.touches[0].clientY - touchStartY;
        if (Math.abs(dx) > Math.abs(dy)) {
            e.preventDefault(); // block vertical scroll only when horizontal
            var cur = parseInt(carousel.dataset.slide, 10) || 0;
            var base = -cur * 100;
            var pct  = (dx / totalW) * 100;
            track.style.transform = 'translateX(' + (base + pct) + '%)';
        }
    }, { passive: false });

    carousel.addEventListener('touchend', function (e) {
        if (!touchLive) return;
        touchLive = false;
        var dx  = e.changedTouches[0].clientX - touchStartX;
        var dy  = e.changedTouches[0].clientY - touchStartY;
        var cur = parseInt(carousel.dataset.slide, 10) || 0;
        track.classList.remove('dragging');
        if (Math.abs(dx) > 42 && Math.abs(dx) > Math.abs(dy) * 1.2) {
            kvibeSlideCarousel(postId, dx > 0 ? cur - 1 : cur + 1);
        } else {
            // Snap back without snap sound
            track.style.transform = 'translateX(-' + cur * 100 + '%)';
        }
    }, { passive: true });

    // ── Mouse drag (desktop) ───────────────────────────────────────────────
    var mouseStartX = 0;
    var mouseDrag   = false;
    var mouseTotalW = 0;

    carousel.addEventListener('mousedown', function (e) {
        if (e.button !== 0 || e.target.closest('button, a')) return;
        mouseStartX = e.clientX;
        mouseDrag   = true;
        mouseTotalW = carousel.offsetWidth;
        track.classList.add('dragging');
        e.preventDefault();
    });

    window.addEventListener('mousemove', function (e) {
        if (!mouseDrag) return;
        var dx   = e.clientX - mouseStartX;
        var cur  = parseInt(carousel.dataset.slide, 10) || 0;
        var base = -cur * 100;
        var pct  = (dx / mouseTotalW) * 100;
        track.style.transform = 'translateX(' + (base + pct) + '%)';
    });

    window.addEventListener('mouseup', function (e) {
        if (!mouseDrag) return;
        mouseDrag = false;
        var dx  = e.clientX - mouseStartX;
        var cur = parseInt(carousel.dataset.slide, 10) || 0;
        track.classList.remove('dragging');
        if (Math.abs(dx) > 42) {
            kvibeSlideCarousel(postId, dx > 0 ? cur - 1 : cur + 1);
        } else {
            track.style.transform = 'translateX(-' + cur * 100 + '%)';
        }
    });

    carousel.addEventListener('mouseleave', function () {
        // don't cancel — window mouseup handles it
    });

    // ── Click-to-lightbox on individual slides ────────────────────────────
    _kvibeAttachSlideClickHandlers(carousel);
}

/* ── Attach click → lightbox on each slide img ─────────────────────────── */
function _kvibeAttachSlideClickHandlers(carousel) {
    if (carousel.dataset.lbInit === '1') return;
    carousel.dataset.lbInit = '1';

    var postArticle = carousel.closest('article.kvibe-post');
    var authorLink  = postArticle  ? postArticle.querySelector('a.kvibe-username')   : null;
    var authorAvImg = postArticle  ? postArticle.querySelector('img.kvibe-profile-pic') : null;
    var timeEl      = postArticle  ? postArticle.querySelector('.kvibe-post-time')    : null;

    var avatarSrc  = authorAvImg ? authorAvImg.src   : '';
    var username   = authorLink  ? authorLink.textContent.trim() : '';
    var profileUrl = authorLink  ? authorLink.href   : '#';
    var time       = timeEl      ? timeEl.textContent.trim()     : '';

    var slides = carousel.querySelectorAll('.kvibe-image-slide');
    var images = [];
    slides.forEach(function (slide) {
        var img = slide.querySelector('img');
        if (img) images.push({ src: img.src, avatar: avatarSrc, username: username, profileUrl: profileUrl, time: time });
    });

    slides.forEach(function (slide, idx) {
        slide.style.cursor = 'zoom-in';
        slide.addEventListener('click', function (e) {
            // Only open if the user didn't drag
            if (Math.abs(parseInt(carousel.dataset.dragDx || '0', 10)) < 5) {
                kvibeOpenFeedLightbox(images, idx);
            }
        });
    });
}

/* ── Attach click → lightbox on a standalone single-image slide ─────────── */
function _kvibeAttachSingleSlideClickHandler(slide) {
    if (slide.dataset.lbInit === '1') return;
    slide.dataset.lbInit = '1';

    var postArticle = slide.closest('article.kvibe-post');
    var authorLink  = postArticle ? postArticle.querySelector('a.kvibe-username')    : null;
    var authorAvImg = postArticle ? postArticle.querySelector('img.kvibe-profile-pic') : null;
    var timeEl      = postArticle ? postArticle.querySelector('.kvibe-post-time')     : null;

    var img = slide.querySelector('img');
    if (!img) return;

    var images = [{
        src:        img.src || img.dataset.src || '',
        avatar:     authorAvImg ? authorAvImg.src            : '',
        username:   authorLink  ? authorLink.textContent.trim() : '',
        profileUrl: authorLink  ? authorLink.href            : '#',
        time:       timeEl      ? timeEl.textContent.trim()  : ''
    }];

    // Update src reference once image loads (for lazy images)
    img.addEventListener('load', function () { images[0].src = img.src; });

    slide.style.cursor = 'zoom-in';
    slide.addEventListener('click', function () {
        images[0].src = img.src; // always latest
        kvibeOpenFeedLightbox(images, 0);
    });
}

/* ── Detect orientation of first image and set class on carousel ──────── */
function _kvibeSetCarouselAspect(carousel) {
    if (carousel.dataset.aspectSet === '1') return;
    var firstImg = carousel.querySelector('.kvibe-image-slide img');
    if (!firstImg) return;

    function applyAspect() {
        if (!firstImg.naturalWidth || !firstImg.naturalHeight) return;
        var ratio = firstImg.naturalWidth / firstImg.naturalHeight;
        carousel.classList.remove('portrait', 'landscape');
        if (ratio < 0.9) carousel.classList.add('portrait');        // taller than wide
        else if (ratio > 1.2) carousel.classList.add('landscape');  // wider than tall
        // else: stays square (default)
        carousel.dataset.aspectSet = '1';
    }

    if (firstImg.complete && firstImg.naturalWidth) {
        applyAspect();
    } else {
        firstImg.addEventListener('load', applyAspect, { once: true });
    }
}

/* ── Same for standalone single-image slides ─────────────────────────── */
function _kvibeSetSingleSlideAspect(slide) {
    if (slide.dataset.aspectSet === '1') return;
    var img = slide.querySelector('img');
    if (!img) return;

    function applyAspect() {
        if (!img.naturalWidth || !img.naturalHeight) return;
        var ratio = img.naturalWidth / img.naturalHeight;
        slide.classList.remove('portrait', 'landscape');
        if (ratio < 0.9) slide.classList.add('portrait');
        else if (ratio > 1.2) slide.classList.add('landscape');
        slide.dataset.aspectSet = '1';
    }

    if (img.complete && img.naturalWidth) {
        applyAspect();
    } else {
        img.addEventListener('load', applyAspect, { once: true });
    }
}

/* ── Track which carousel is currently hovered (for arrow-key nav) ────── */
var _kvibeHoveredCarousel = null;

function _kvibeAttachHoverTracking(carousel) {
    if (carousel.dataset.hoverInit === '1') return;
    carousel.dataset.hoverInit = '1';
    carousel.addEventListener('mouseenter', function () { _kvibeHoveredCarousel = carousel; });
    carousel.addEventListener('mouseleave', function () {
        if (_kvibeHoveredCarousel === carousel) _kvibeHoveredCarousel = null;
    });
}

/* ── Global arrow-key handler (desktop only, fires once) ────────────────── */
(function () {
    document.addEventListener('keydown', function (e) {
        // Only on desktop
        if (window.innerWidth < 768) return;
        // Don't steal keys from inputs / textareas
        var tag = document.activeElement && document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        // Don't fire when feed lightbox or any modal is open
        var feedLb = document.getElementById('kvibeFeedLightbox');
        if (feedLb && feedLb.classList.contains('open')) return;
        var dmModal = document.getElementById('kvibeDmModal');
        if (dmModal && dmModal.classList.contains('open')) return;

        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;

        var carousel = _kvibeHoveredCarousel;
        if (!carousel) return;

        e.preventDefault(); // stop page scroll
        var postId = carousel.id.replace('kvibe-carousel-', '');
        var cur    = parseInt(carousel.dataset.slide || '0', 10);
        kvibeSlideCarousel(postId, e.key === 'ArrowLeft' ? cur - 1 : cur + 1);
    });
}());

/* ── Master init — runs on page load and after every HTMX swap ──────────── */
function kvibeInitCarousels() {
    // Multi-image carousels
    document.querySelectorAll('.kvibe-image-carousel').forEach(function (c) {
        kvibeInitCarouselSwipe(c);
        kvibeInjectCarouselArrows(c);
        _kvibeSetCarouselAspect(c);
        _kvibeAttachHoverTracking(c);
    });

    // Single-image slides that live directly inside .kvibe-media-container
    document.querySelectorAll('.kvibe-media-container > .kvibe-image-slide').forEach(function (s) {
        _kvibeSetSingleSlideAspect(s);
        _kvibeAttachSingleSlideClickHandler(s);
    });
}


// ===== PANELS & PROFILE =====
function kvibeOpenProfilePanel(username) {
    const panel = document.getElementById('kvibe-profile-panel');
    const content = document.getElementById('kvibe-profile-panel-content');
    if (!panel || !content) return;
    panel.classList.add('active');
    content.innerHTML = '<div class="kvibe-loader-container"><div class="kvibe-loader"></div></div>';
    fetch(`/profile_panel/${username}/`).then(r => r.text()).then(html => content.innerHTML = html);
}

function kvibeClosePanel(panelId) {
    const p = document.getElementById(panelId);
    if (p) p.classList.remove('active');
}


// ===== INITIALIZATION =====
function kvibeInit() {
    kvibeInitCarousels();
    document.querySelectorAll('.kvibe-username').forEach(link => {
        link.addEventListener('click', (e) => {
            if (window.innerWidth > 768) {
                e.preventDefault();
                kvibeOpenProfilePanel(link.dataset.user);
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', kvibeInit);

// htmx:afterSettle fires after every partial swap (infinite scroll, etc.)
document.addEventListener('htmx:afterSettle', kvibeInitCarousels);

// iOS Safari can drop `position: sticky` on an element after a nearby
// AJAX/HTMX swap mutates the DOM, making the filter bar scroll away
// instead of sticking. Nudging it (toggle off/on) forces Safari to
// recompute the sticky layer after every swap.
function kvibeRestickFilterBar() {
    const bar = document.getElementById('mfy-cat-filter-bar');
    if (!bar) return;
    bar.style.position = 'static';
    // Force a reflow so the browser actually registers the change
    // before we switch it back.
    void bar.offsetHeight;
    bar.style.position = '';
}
document.addEventListener('htmx:afterSettle', kvibeRestickFilterBar);
window.kvibeRestickFilterBar = kvibeRestickFilterBar;

// Make available to HTML onclick attributes
window.kvibeTogglePlayPause    = kvibeTogglePlayPause;
window.kvibeSeekVideo          = kvibeSeekVideo;
window.kvibeSlideCarousel      = kvibeSlideCarousel;
window.kvibeSlideCarouselAbs   = kvibeSlideCarousel; // alias for home.html shim
window.kvibeClosePanel         = kvibeClosePanel;
window.kvibeOpenLightbox       = kvibeOpenLightbox;
window.kvibeCloseLightbox      = kvibeCloseLightbox;
window.kvibeLightboxNext       = kvibeLightboxNext;
window.kvibeLightboxPrev       = kvibeLightboxPrev;
window.kvibeInitCarousels      = kvibeInitCarousels;
// Legacy alias — keeps any existing callers working
window.kvibeInitAllCarouselSwipe = kvibeInitCarousels;
