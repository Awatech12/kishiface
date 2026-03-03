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
  const indicators = carousel?.querySelectorAll('.kvibe-indicator');
  
  if (!carousel || !track) return;
  
  let current = parseInt(carousel.dataset.slide || 0);
  const total = parseInt(carousel.dataset.total || 1);
  
  if (total <= 1) return;
  
  current = (current + direction + total) % total;
  
  track.style.transform = `translateX(-${current * 100}%)`;
  carousel.dataset.slide = current;
  
  indicators?.forEach((indicator, index) => {
    indicator.classList.toggle('active', index === current);
  });
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

// ===== START WHEN READY =====
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', kvibeInit);
} else {
    kvibeInit();
}

// ===== MAKE FUNCTIONS GLOBALLY AVAILABLE =====
window.kvibeTogglePlayPause = kvibeTogglePlayPause;
window.kvibeSeekVideo = kvibeSeekVideo;
window.kvibeClosePanel = (panelId) => kvibeClosePanel(panelId || 'kvibe-profile-panel');
window.kvibeClosePanel2 = () => kvibeClosePanel('kvibe-comments-panel');
window.kvibeSlideCarousel = kvibeSlideCarousel;


