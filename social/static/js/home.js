/// ===== GLOBAL MEDIA TRACKING =====
let kvibeCurrentlyPlayingMedia = null;

// ===== IMAGE GRID LIGHTBOX =====
let kvibeLightboxImages = [];   
let kvibeLightboxIndex = 0;
let kvibeLightboxPostData = {}; 

function kvibeOpenLightbox(images, startIndex, postData) {
  kvibeLightboxImages = images;
  kvibeLightboxIndex = startIndex;
  kvibeLightboxPostData = postData || {};

  const lb = document.getElementById('kvibe-lightbox');
  if (!lb) return;

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
  if (detailBody) detailBody.textContent = postData.caption || '';

  if (thumbStrip) {
    thumbStrip.innerHTML = images.map((img, i) => `
      <div class="kvibe-lightbox-thumb ${i === startIndex ? 'active' : ''}" onclick="kvibeLightboxGoTo(${i})">
        <img src="${img.src}" alt="">
      </div>`).join('');
  }

  lb.classList.add('active');
  kvibeLightboxUpdate();
}

function kvibeCloseLightbox() {
  const lb = document.getElementById('kvibe-lightbox');
  if (lb) lb.classList.remove('active');
}

function kvibeLightboxUpdate() {
  const lb = document.getElementById('kvibe-lightbox');
  if (!lb) return;
  const img = lb.querySelector('.kvibe-lightbox-main-img');
  if (img) img.src = kvibeLightboxImages[kvibeLightboxIndex].src;
  lb.querySelectorAll('.kvibe-lightbox-thumb').forEach((t, i) => {
    t.classList.toggle('active', i === kvibeLightboxIndex);
  });
}

function kvibeLightboxGoTo(idx) { kvibeLightboxIndex = idx; kvibeLightboxUpdate(); }
function kvibeLightboxPrev() { kvibeLightboxIndex = (kvibeLightboxIndex - 1 + kvibeLightboxImages.length) % kvibeLightboxImages.length; kvibeLightboxUpdate(); }
function kvibeLightboxNext() { kvibeLightboxIndex = (kvibeLightboxIndex + 1) % kvibeLightboxImages.length; kvibeLightboxUpdate(); }

// ===== VIDEO CONTROLS & SYNC =====
function kvibeTogglePlayPause(videoId, event) {
    if (event) event.stopPropagation();
    const video = document.getElementById(videoId);
    if (!video) return;

    if (video.paused) {
        // Stop all other media
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

// Listen for global play/pause events to update UI classes
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
function kvibeSlideCarousel(postId, index) {
    const carousel = document.getElementById('kvibe-carousel-' + postId);
    if (!carousel) return;
    const track = carousel.querySelector('.kvibe-image-track');
    const total = parseInt(carousel.dataset.total);
    
    let nextIdx = index;
    if (nextIdx < 0) nextIdx = total - 1;
    if (nextIdx >= total) nextIdx = 0;

    carousel.dataset.slide = nextIdx;
    track.style.transform = `translateX(-${nextIdx * 100}%)`;
    carousel.querySelectorAll('.kvibe-indicator').forEach((ind, i) => ind.classList.toggle('active', i === nextIdx));
    const counter = carousel.querySelector('.kvibe-slide-counter');
    if (counter) counter.textContent = `${nextIdx + 1} / ${total}`;
}

function kvibeInitAllCarouselSwipe() {
    document.querySelectorAll('.kvibe-image-carousel').forEach(c => {
        const postId = c.id.replace('kvibe-carousel-', '');
        let startX = 0;
        c.addEventListener('touchstart', (e) => { startX = e.touches[0].clientX; }, {passive: true});
        c.addEventListener('touchend', (e) => {
            const diff = startX - e.changedTouches[0].clientX;
            if (Math.abs(diff) > 50) {
                const cur = parseInt(c.dataset.slide);
                kvibeSlideCarousel(postId, diff > 0 ? cur + 1 : cur - 1);
            }
        }, {passive: true});
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
    kvibeInitAllCarouselSwipe();
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
document.addEventListener('htmx:afterOnLoad', kvibeInit);

// Make available to HTML onclick attributes
window.kvibeTogglePlayPause = kvibeTogglePlayPause;
window.kvibeSeekVideo = kvibeSeekVideo;
window.kvibeSlideCarousel = kvibeSlideCarousel;
window.kvibeClosePanel = kvibeClosePanel;
window.kvibeOpenLightbox = kvibeOpenLightbox;
window.kvibeCloseLightbox = kvibeCloseLightbox;
window.kvibeLightboxNext = kvibeLightboxNext;
window.kvibeLightboxPrev = kvibeLightboxPrev;