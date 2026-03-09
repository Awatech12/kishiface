/// ===== GLOBAL MEDIA TRACKING =====
let kvibeCurrentlyPlayingMedia = null;

// ===== IMAGE GRID LIGHTBOX =====

let kvibeLightboxImages = [];   // [{src, alt}]
let kvibeLightboxIndex = 0;
let kvibeLightboxPostData = {}; // {username, avatar, time, caption}

function kvibeOpenLightbox(images, startIndex, postData) {
  kvibeLightboxImages = images;
  kvibeLightboxIndex = startIndex;
  kvibeLightboxPostData = postData || {};

  const lb = document.getElementById('kvibe-lightbox');
  if (!lb) return;

  // Populate details pane
  const detailHeader = lb.querySelector('.kvibe-lightbox-details-header');
  const detailBody   = lb.querySelector('.kvibe-lightbox-details-body');
  const thumbStrip   = lb.querySelector('.kvibe-lightbox-details-thumbs');

  if (detailHeader) {
    detailHeader.innerHTML = `
      <img src="${postData.avatar || ''}" alt="">
      <div>
        <a class="kvibe-lightbox-details-username" href="${postData.profileUrl || '#'}">${postData.username || ''}</a>
        <div class="kvibe-lightbox-details-meta">${postData.time || ''}</div>
      </div>`;
  }

  if (detailBody) {
    detailBody.textContent = postData.caption || '';
  }

  if (thumbStrip) {
    thumbStrip.innerHTML = images.map((img, i) => `
      <div class="kvibe-lightbox-thumb ${i === startIndex ? 'active' : ''}" onclick="kvibeLightboxGoTo(${i})">
        <img src="${img.src}" alt="${img.alt || ''}">
      </div>`).join('');
  }

  kvibeLightboxRender();
  lb.classList.add('open');
  document.body.style.overflow = 'hidden';

  // Keyboard nav
  document.addEventListener('keydown', kvibeLightboxKeyNav);
}

function kvibeLightboxRender() {
  const lb = document.getElementById('kvibe-lightbox');
  if (!lb) return;

  const imgWrap  = lb.querySelector('.kvibe-lightbox-img-wrap');
  const counter  = lb.querySelector('.kvibe-lightbox-counter');
  const prevBtn  = lb.querySelector('.kvibe-lightbox-prev');
  const nextBtn  = lb.querySelector('.kvibe-lightbox-next');
  const thumbs   = lb.querySelectorAll('.kvibe-lightbox-thumb');

  const total = kvibeLightboxImages.length;
  const cur   = kvibeLightboxImages[kvibeLightboxIndex];

  if (imgWrap) {
    imgWrap.innerHTML = `<img src="${cur.src}" alt="${cur.alt || ''}" draggable="false">`;
  }
  if (counter)  counter.textContent = `${kvibeLightboxIndex + 1} / ${total}`;
  if (prevBtn)  prevBtn.classList.toggle('hidden', kvibeLightboxIndex === 0);
  if (nextBtn)  nextBtn.classList.toggle('hidden', kvibeLightboxIndex === total - 1);

  thumbs.forEach((t, i) => t.classList.toggle('active', i === kvibeLightboxIndex));
}

function kvibeLightboxGoTo(index) {
  if (index < 0 || index >= kvibeLightboxImages.length) return;
  kvibeLightboxIndex = index;
  kvibeLightboxRender();
}

function kvibeCloseLightbox() {
  const lb = document.getElementById('kvibe-lightbox');
  if (!lb) return;
  lb.classList.remove('open');
  document.body.style.overflow = '';
  document.removeEventListener('keydown', kvibeLightboxKeyNav);
}

function kvibeLightboxKeyNav(e) {
  if (e.key === 'ArrowRight') kvibeLightboxGoTo(kvibeLightboxIndex + 1);
  else if (e.key === 'ArrowLeft') kvibeLightboxGoTo(kvibeLightboxIndex - 1);
  else if (e.key === 'Escape') kvibeCloseLightbox();
}

window.kvibeOpenLightbox  = kvibeOpenLightbox;
window.kvibeLightboxGoTo  = kvibeLightboxGoTo;
window.kvibeCloseLightbox = kvibeCloseLightbox;

// ===== VIDEO PLAYER CONTROLS =====

/**
 * Pauses all video and audio elements except the one currently starting.
 */
function kvibePauseAllOtherMedia(currentMediaElement) {
    if (kvibeCurrentlyPlayingMedia && kvibeCurrentlyPlayingMedia !== currentMediaElement) {
        // Pause the previously playing media
        kvibeCurrentlyPlayingMedia.pause();
        
        // Reset video UI
        if (kvibeCurrentlyPlayingMedia.tagName === 'VIDEO') {
            const prevContainer = kvibeCurrentlyPlayingMedia.closest('.kvibe-video-container');
            if (prevContainer) {
                prevContainer.classList.add('paused');
                const prevPlayIcon = prevContainer.querySelector('.kvibe-play-pause-icon');
                if (prevPlayIcon) prevPlayIcon.style.opacity = '1';
            }
        }
        // Reset audio UI
        else if (kfCurrentlyPlayingMedia.tagName === 'AUDIO') {
            const postId = kfCurrentlyPlayingMedia.id.replace('kf-audio-element-', '');
            const prevIcon = document.getElementById('kf-audio-icon-' + postId);
            if (prevIcon) {
                prevIcon.classList.remove('fa-pause');
                prevIcon.classList.add('fa-play');
            }
            
            // Stop audio timer
            if (kfAudioTimers[postId]) {
                clearInterval(kfAudioTimers[postId]);
                delete kfAudioTimers[postId];
            }
        }
    }
    
    // Update the globally tracked media element if it's playing
    if (currentMediaElement && !currentMediaElement.paused) {
        kvibeCurrentlyPlayingMedia = currentMediaElement;
    }
}

/**
 * Toggles play/pause for the video.
 */
function kvibeTogglePlayPause(videoId, e) {
    // Prevent restarting if the click target is a seek button or download button
    if (e && (e.target.closest('.kvibe-seek-overlay-btn') || false)) {
        return;
    }

    const video = document.getElementById(videoId);
    if (!video) return;

    if (video.paused || video.ended) {
        kvibePauseAllOtherMedia(video);
        video.play().then(() => {
            // Video started playing
            const container = video.closest('.kvibe-video-container');
            if (container) {
                container.classList.remove('paused');
                const playIcon = container.querySelector('.kvibe-play-pause-icon');
                if (playIcon) playIcon.style.opacity = '0';
            }
        }).catch(error => {
            console.error("Video Play Error:", error);
        });
    } else {
        video.pause();
        const container = video.closest('.kvibe-video-container');
        if (container) {
            container.classList.add('paused');
            const playIcon = container.querySelector('.kvibe-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '1';
        }
    }
}

/**
 * Seeks the video forward or backward by a specified amount.
 */
function kvibeSeekVideo(videoId, seconds) {
    const video = document.getElementById(videoId);
    if (video) {
        let newTime = video.currentTime + seconds;
        newTime = Math.max(0, newTime);
        if (video.duration) {
            newTime = Math.min(newTime, video.duration);
        }
        video.currentTime = newTime;
    }
}

// ===== CAROUSEL CONTROLS =====
function kvibeSlideCarousel(postId, direction) {
  const carousel = document.getElementById(`kvibe-carousel-${postId}`);
  const track = document.getElementById(`kvibe-track-${postId}`);

  if (!carousel || !track) return;

  let current = parseInt(carousel.dataset.slide || 0);
  const total = parseInt(carousel.dataset.total || 1);

  if (total <= 1) return;

  current = Math.max(0, Math.min(current + direction, total - 1));

  track.style.transition = 'transform 0.30s cubic-bezier(0.25,0.46,0.45,0.94)';
  track.style.transform = `translateX(-${current * 100}%)`;
  carousel.dataset.slide = current;

  carousel.querySelectorAll('.kvibe-indicator').forEach((dot, i) => {
    dot.classList.toggle('active', i === current);
  });

  const counter = carousel.querySelector('.kvibe-slide-counter');
  if (counter) counter.textContent = `${current + 1} / ${total}`;
}

// ===== SWIPE SUPPORT FOR CAROUSELS =====
/**
 * Attaches touch and mouse swipe handlers to a carousel element.
 * Works for both kvibe-image-carousel and kvibe-mixed-media-carousel.
 */
function kvibeAttachSwipeHandlers(carousel) {
  if (!carousel || carousel.dataset.swipeAttached) return;
  carousel.dataset.swipeAttached = 'true';

  let startX = 0;
  let startY = 0;
  let isDragging = false;
  let dragOffset = 0;
  const SWIPE_THRESHOLD = 40;   // px needed to trigger slide change
  const DRAG_THRESHOLD  = 5;    // px of horizontal movement before locking axis

  const isMixed = carousel.classList.contains('kvibe-mixed-media-carousel');
  const postId  = carousel.id.replace(isMixed ? 'kvibe-mixed-carousel-' : 'kvibe-carousel-', '');
  const trackId = isMixed ? `kvibe-mixed-track-${postId}` : `kvibe-track-${postId}`;
  const track   = document.getElementById(trackId);
  if (!track) return;

  function getTotal()   { return parseInt(carousel.dataset.total || 1); }
  function getCurrent() { return parseInt(carousel.dataset.slide || 0); }

  function kvibeSlideTo(index) {
    const total = getTotal();
    if (total <= 1) return;
    const clamped = Math.max(0, Math.min(index, total - 1));
    track.style.transition = 'transform 0.30s cubic-bezier(0.25,0.46,0.45,0.94)';
    track.style.transform  = `translateX(-${clamped * 100}%)`;
    carousel.dataset.slide = clamped;

    // Update dot indicators
    const dotClass = isMixed ? '.kvibe-mixed-indicator' : '.kvibe-indicator';
    carousel.querySelectorAll(dotClass).forEach((dot, i) => {
      dot.classList.toggle('active', i === clamped);
    });

    // Update counter badge if present
    const counter = carousel.querySelector('.kvibe-slide-counter');
    if (counter) counter.textContent = `${clamped + 1} / ${total}`;
  }

  // ── Touch events ──────────────────────────────────────────
  carousel.addEventListener('touchstart', function(e) {
    const touch = e.touches[0];
    startX    = touch.clientX;
    startY    = touch.clientY;
    isDragging = false;
    dragOffset = 0;
    track.style.transition = 'none';
  }, { passive: true });

  carousel.addEventListener('touchmove', function(e) {
    if (!e.touches.length) return;
    const touch = e.touches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;

    // Lock to horizontal swipe only after enough horizontal movement
    if (!isDragging && Math.abs(dx) < DRAG_THRESHOLD) return;
    if (!isDragging && Math.abs(dy) > Math.abs(dx)) return; // vertical scroll wins

    isDragging = true;
    e.preventDefault(); // prevent page scroll while swiping

    dragOffset = dx;
    const current = getCurrent();
    const baseOffset = -(current * 100);
    const percentOffset = (dx / carousel.offsetWidth) * 100;
    track.style.transform = `translateX(calc(${baseOffset}% + ${dx}px))`;
  }, { passive: false });

  carousel.addEventListener('touchend', function(e) {
    if (!isDragging) return;
    isDragging = false;

    const current = getCurrent();
    const total   = getTotal();

    if (dragOffset < -SWIPE_THRESHOLD && current < total - 1) {
      kvibeSlideTo(current + 1);
    } else if (dragOffset > SWIPE_THRESHOLD && current > 0) {
      kvibeSlideTo(current - 1);
    } else {
      // Snap back
      kvibeSlideTo(current);
    }
    dragOffset = 0;
  }, { passive: true });

  // ── Mouse drag events (desktop) ───────────────────────────
  carousel.addEventListener('mousedown', function(e) {
    // Ignore clicks on buttons/controls
    if (e.target.closest('button, .kvibe-seek-overlay-btn, video')) return;
    startX     = e.clientX;
    startY     = e.clientY;
    isDragging = false;
    dragOffset = 0;
    track.style.transition = 'none';
    carousel.style.cursor  = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mousemove', function(e) {
    if (startX === 0 && !isDragging) return;
    // Only active when mouse is held (button 0)
    if (e.buttons !== 1) return;

    const dx = e.clientX - startX;
    if (!isDragging && Math.abs(dx) < DRAG_THRESHOLD) return;

    isDragging = true;
    dragOffset = dx;
    const current = getCurrent();
    track.style.transform = `translateX(calc(${-(current * 100)}% + ${dx}px))`;
  });

  window.addEventListener('mouseup', function(e) {
    if (!isDragging) {
      startX = 0;
      return;
    }
    isDragging = false;
    carousel.style.cursor = '';
    const current = getCurrent();
    const total   = getTotal();

    if (dragOffset < -SWIPE_THRESHOLD && current < total - 1) {
      kvibeSlideTo(current + 1);
    } else if (dragOffset > SWIPE_THRESHOLD && current > 0) {
      kvibeSlideTo(current - 1);
    } else {
      kvibeSlideTo(current);
    }
    dragOffset = 0;
    startX     = 0;
  });
}

/**
 * Initializes swipe on all carousels currently in the DOM,
 * then watches for new ones added dynamically (infinite scroll).
 */
function kvibeInitAllCarouselSwipe() {
  // Attach to existing carousels
  document.querySelectorAll('.kvibe-image-carousel, .kvibe-mixed-media-carousel').forEach(kvibeAttachSwipeHandlers);

  // Watch for dynamically added carousels
  if ('MutationObserver' in window) {
    const feedEl = document.getElementById('kvibe-real-feed');
    if (!feedEl) return;
    const obs = new MutationObserver(mutations => {
      mutations.forEach(m => {
        m.addedNodes.forEach(node => {
          if (node.nodeType !== 1) return;
          node.querySelectorAll && node.querySelectorAll('.kvibe-image-carousel, .kvibe-mixed-media-carousel')
            .forEach(kvibeAttachSwipeHandlers);
          if (node.classList &&
              (node.classList.contains('kvibe-image-carousel') ||
               node.classList.contains('kvibe-mixed-media-carousel'))) {
            kvibeAttachSwipeHandlers(node);
          }
        });
      });
    });
    obs.observe(feedEl, { childList: true, subtree: true });
  }
}

// ===== INTERSECTION OBSERVER =====
let kvibeMediaObserver = null;

function kvibeInitMediaObserver() {
    kvibeMediaObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) {
                const container = entry.target;
                const video = container.querySelector('.kvibe-video');
                
                // Pause video if playing
                if (video && !video.paused) {
                    video.pause();
                    container.classList.add('paused');
                    const playIcon = container.querySelector('.kvibe-play-pause-icon');
                    if (playIcon) playIcon.style.opacity = '1';
                    // Clear global tracker if this was the active media
                    if (kvibeCurrentlyPlayingMedia === video) {
                        kvibeCurrentlyPlayingMedia = null;
                    }
                }
            }
        });
    }, {
        threshold: 0.25
    });
}

// ===== PROFILE PANEL =====
function kvibeOpenProfilePanel(username) {
  if (window.innerWidth <= 768) return;
  
  fetch(`/popup/${username}/`)
    .then(res => res.text())
    .then(html => {
      document.getElementById('kvibe-profile-content').innerHTML = html;
      document.getElementById('kvibe-profile-panel').classList.add('open');
    });
}

function kvibeClosePanel(panelId) {
  document.getElementById(panelId)?.classList.remove('open');
}

// ===== INITIALIZATION =====
function kvibeInit() {
    // Initialize media observer
    kvibeInitMediaObserver();
    
    // --- Video Setup ---
    document.querySelectorAll('.kvibe-video-container').forEach(container => {
        const video = container.querySelector('.kvibe-video');
        if (!video) return;
        
        // Add to Intersection Observer
        if (kvibeMediaObserver) kvibeMediaObserver.observe(container);
        
        // Initial state - show play icon (paused by default)
        container.classList.add('paused');
        
        // Event listeners
        video.addEventListener('play', () => {
            container.classList.remove('paused');
            const playIcon = container.querySelector('.kvibe-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '0';
            kvibeCurrentlyPlayingMedia = video;
        });
        
        video.addEventListener('pause', () => {
            container.classList.add('paused');
            const playIcon = container.querySelector('.kvibe-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '1';
            if (kvibeCurrentlyPlayingMedia === video) kvibeCurrentlyPlayingMedia = null;
        });
        
        video.addEventListener('ended', () => {
            container.classList.add('paused');
            const playIcon = container.querySelector('.kvibe-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '1';
            if (kvibeCurrentlyPlayingMedia === video) kvibeCurrentlyPlayingMedia = null;
        });
    });
    
    
    // --- Carousel Swipe Support ---
    kvibeInitAllCarouselSwipe();

    // --- Profile Links ---
    document.querySelectorAll('.kvibe-username').forEach(link => {
        link.addEventListener('click', (e) => {
            if (window.innerWidth > 768) {
                e.preventDefault();
                const username = link.dataset.user;
                kvibeOpenProfilePanel(username);
            }
        });
    });
    
    // --- Resize Handler ---
    window.addEventListener('resize', () => {
        if (window.innerWidth <= 768) {
            kvibeClosePanel('kvibe-profile-panel');
            kvibeClosePanel('kvibe-comments-panel');
        }
    });
}

// ===== FEED CAROUSEL KEYBOARD NAVIGATION =====
/**
 * Tracks which feed carousel the user is hovering over / has focused,
 * so arrow keys can navigate slides without affecting the page scroll.
 */
(function kvibeInitFeedCarouselKeyboard() {
  let activeCarousel = null;

  function setActive(el) {
    activeCarousel = el;
  }
  function clearActive(el) {
    if (activeCarousel === el) activeCarousel = null;
  }

  function attachHoverListeners(carousel) {
    if (carousel.dataset.kbAttached) return;
    carousel.dataset.kbAttached = 'true';
    carousel.addEventListener('mouseenter', () => setActive(carousel));
    carousel.addEventListener('mouseleave', () => clearActive(carousel));
    carousel.addEventListener('focusin',    () => setActive(carousel));
    carousel.addEventListener('focusout',   () => clearActive(carousel));
  }

  function attachToAll() {
    document.querySelectorAll('.kvibe-image-carousel, .kvibe-mixed-media-carousel')
      .forEach(attachHoverListeners);
  }

  document.addEventListener('keydown', function(e) {
    if (!activeCarousel) return;
    const isMixed = activeCarousel.classList.contains('kvibe-mixed-media-carousel');
    const total   = parseInt(activeCarousel.dataset.total || 1);
    if (total <= 1) return;

    let current = parseInt(activeCarousel.dataset.slide || 0);

    if (e.key === 'ArrowLeft'  && current > 0)           { e.preventDefault(); current--; }
    else if (e.key === 'ArrowRight' && current < total-1) { e.preventDefault(); current++; }
    else return;

    // Get the right track id
    const postId  = activeCarousel.id.replace(isMixed ? 'kvibe-mixed-carousel-' : 'kvibe-carousel-', '');
    const trackId = isMixed ? `kvibe-mixed-track-${postId}` : `kvibe-track-${postId}`;
    const track   = document.getElementById(trackId);
    if (!track) return;

    track.style.transition = 'transform 0.30s cubic-bezier(0.25,0.46,0.45,0.94)';
    track.style.transform  = `translateX(-${current * 100}%)`;
    activeCarousel.dataset.slide = current;

    const dotClass = isMixed ? '.kvibe-mixed-indicator' : '.kvibe-indicator';
    activeCarousel.querySelectorAll(dotClass).forEach((d, i) => {
      d.classList.toggle('active', i === current);
    });

    const counter = activeCarousel.querySelector('.kvibe-slide-counter');
    if (counter) counter.textContent = `${current + 1} / ${total}`;
  });

  // Attach to existing carousels and watch for dynamically added ones
  attachToAll();
  if ('MutationObserver' in window) {
    const feedEl = document.getElementById('kvibe-real-feed');
    if (feedEl) {
      new MutationObserver(() => attachToAll()).observe(feedEl, { childList: true, subtree: true });
    }
  }
})();


// ===== SWIPE-MODE INNER CAROUSEL: TOUCH + KEYBOARD =====
/**
 * Attaches horizontal touch/mouse swipe and keyboard nav to a
 * .kvibe-swipe-carousel element inside the vertical swipe view.
 */
function kvibeAttachSwipeCarouselHandlers(car) {
  if (!car || car.dataset.scAttached) return;
  car.dataset.scAttached = 'true';

  const postId  = car.id.replace('kvibe-swipe-car-', '');
  const track   = document.getElementById('kvibe-swipe-car-track-' + postId);
  const dotsEl  = document.getElementById('kvibe-swipe-car-dots-'  + postId);
  if (!track) return;

  const SWIPE_THRESHOLD = 40;
  const DRAG_THRESHOLD  = 5;
  let startX = 0, dragOffset = 0, isDragging = false;

  function getTotal()   { return track.querySelectorAll('.kvibe-swipe-carousel-slide').length; }
  function getCurrent() { return parseInt(track.dataset.current || '0'); }

  function slideTo(index) {
    const total = getTotal();
    const clamped = Math.max(0, Math.min(index, total - 1));
    track.style.transition = 'transform 0.28s cubic-bezier(0.25,0.46,0.45,0.94)';
    track.style.transform  = `translateX(-${clamped * 100}%)`;
    track.dataset.current  = clamped;

    if (dotsEl) {
      dotsEl.querySelectorAll('.kvibe-swipe-carousel-dot').forEach((d, i) => {
        d.classList.toggle('active', i === clamped);
      });
    }
    const counter = car.querySelector('.kvibe-swipe-carousel-counter');
    if (counter) counter.textContent = `${clamped + 1} / ${total}`;
  }

  // Touch
  car.addEventListener('touchstart', e => {
    startX = e.touches[0].clientX;
    isDragging = false; dragOffset = 0;
    track.style.transition = 'none';
  }, { passive: true });

  car.addEventListener('touchmove', e => {
    const dx = e.touches[0].clientX - startX;
    const dy = e.touches[0].clientY - (e.touches[0].clientY); // placeholder
    if (!isDragging && Math.abs(dx) < DRAG_THRESHOLD) return;
    isDragging = true;
    dragOffset = dx;
    e.stopPropagation(); // don't let vertical swipe handler steal this
    const base = -(getCurrent() * 100);
    track.style.transform = `translateX(calc(${base}% + ${dx}px))`;
  }, { passive: true });

  car.addEventListener('touchend', () => {
    if (!isDragging) return;
    isDragging = false;
    const cur = getCurrent(), total = getTotal();
    if      (dragOffset < -SWIPE_THRESHOLD && cur < total - 1) slideTo(cur + 1);
    else if (dragOffset >  SWIPE_THRESHOLD && cur > 0)         slideTo(cur - 1);
    else                                                        slideTo(cur);
    dragOffset = 0;
  }, { passive: true });

  // Mouse drag
  car.addEventListener('mousedown', e => {
    startX = e.clientX; isDragging = false; dragOffset = 0;
    track.style.transition = 'none';
    car.style.cursor = 'grabbing';
    e.preventDefault();
  });
  window.addEventListener('mousemove', e => {
    if (!car.style.cursor || e.buttons !== 1) return;
    const dx = e.clientX - startX;
    if (!isDragging && Math.abs(dx) < DRAG_THRESHOLD) return;
    isDragging = true; dragOffset = dx;
    track.style.transform = `translateX(calc(${-(getCurrent()*100)}% + ${dx}px))`;
  });
  window.addEventListener('mouseup', () => {
    if (!car.style.cursor) return;
    car.style.cursor = '';
    if (!isDragging) { startX = 0; return; }
    isDragging = false;
    const cur = getCurrent(), total = getTotal();
    if      (dragOffset < -SWIPE_THRESHOLD && cur < total - 1) slideTo(cur + 1);
    else if (dragOffset >  SWIPE_THRESHOLD && cur > 0)         slideTo(cur - 1);
    else                                                        slideTo(cur);
    dragOffset = 0; startX = 0;
  });

  // Keyboard (when this carousel is active)
  car.setAttribute('tabindex', '0');
  car.addEventListener('keydown', e => {
    if (e.key === 'ArrowLeft')  { e.preventDefault(); e.stopPropagation(); slideTo(getCurrent() - 1); }
    if (e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); slideTo(getCurrent() + 1); }
  });
}

/**
 * Expose updated kvibeSwipeCarousel so it also updates the counter.
 * Overrides the inline definition inside the swipe IIFE if called after load.
 */
window.kvibeSwipeCarousel = function(postId, dir, evt) {
  if (evt) evt.stopPropagation();
  const track  = document.getElementById('kvibe-swipe-car-track-' + postId);
  const dotsEl = document.getElementById('kvibe-swipe-car-dots-'  + postId);
  if (!track) return;
  const slides  = track.querySelectorAll('.kvibe-swipe-carousel-slide');
  const dots    = dotsEl ? dotsEl.querySelectorAll('.kvibe-swipe-carousel-dot') : [];
  const current = parseInt(track.dataset.current || '0');
  const next    = Math.max(0, Math.min(slides.length - 1, current + dir));
  track.dataset.current = next;
  track.style.transition = 'transform 0.28s cubic-bezier(0.25,0.46,0.45,0.94)';
  track.style.transform  = `translateX(-${next * 100}%)`;
  dots.forEach((d, i) => d.classList.toggle('active', i === next));
  const car     = document.getElementById('kvibe-swipe-car-' + postId);
  const counter = car ? car.querySelector('.kvibe-swipe-carousel-counter') : null;
  if (counter) counter.textContent = `${next + 1} / ${slides.length}`;
};

// Watch for swipe carousels added to the DOM and attach handlers
(function kvibeWatchSwipeCarousels() {
  function attachAll() {
    document.querySelectorAll('.kvibe-swipe-carousel').forEach(kvibeAttachSwipeCarouselHandlers);
  }
  attachAll();
  if ('MutationObserver' in window) {
    const body = document.body;
    new MutationObserver(mutations => {
      mutations.forEach(m => m.addedNodes.forEach(node => {
        if (node.nodeType !== 1) return;
        if (node.classList && node.classList.contains('kvibe-swipe-carousel')) {
          kvibeAttachSwipeCarouselHandlers(node);
        }
        node.querySelectorAll && node.querySelectorAll('.kvibe-swipe-carousel')
          .forEach(kvibeAttachSwipeCarouselHandlers);
      }));
    }).observe(body, { childList: true, subtree: true });
  }
})();


// ===== START WHEN READY =====
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', kvibeInit);
} else {
    kvibeInit();
}

// ===== MAKE FUNCTIONS GLOBALLY AVAILABLE =====
window.kfTogglePlayPause = kfTogglePlayPause;
window.kfSeekVideo = kfSeekVideo;
window.kfToggleAudio = kfToggleAudio;
window.kfSeekAudio = kfSeekAudio;
window.kfSeekAudioBy = kfSeekAudioBy;
window.kfDownloadVideo = kfDownloadVideo;
window.kfDownloadAudio = kfDownloadAudio;
window.kfDownloadImage = kfDownloadImage;
window.kfDownloadPostMedia = kfDownloadPostMedia;
window.kfClosePanel = (panelId) => kfClosePanel(panelId || 'kf-profile-panel');
window.kfClosePanel2 = () => kfClosePanel('kf-comments-panel');
window.kfSlideCarousel = kfSlideCarousel;

