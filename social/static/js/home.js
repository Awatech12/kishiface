// ===== GLOBAL MEDIA TRACKING =====
let kfCurrentlyPlayingMedia = null;
const kfAudioTimers = {};

// ===== DOWNLOAD FUNCTIONS =====

/**
 * Download a file from a URL
 */
function kfDownloadFile(url, filename) {
    // Create a temporary anchor element
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'download';
    link.target = '_blank';
    
    // Append to the document
    document.body.appendChild(link);
    
    // Trigger the download
    link.click();
    
    // Clean up
    document.body.removeChild(link);
}

/**
 * Download video file
 */
function kfDownloadVideo(postId, videoUrl) {
    event.stopPropagation(); // Prevent video play/pause
    const filename = `kishiface_video_${postId}_${Date.now()}.mp4`;
    kfDownloadFile(videoUrl, filename);
}

/**
 * Download audio file
 */
function kfDownloadAudio(postId, audioUrl) {
    event.stopPropagation(); // Prevent audio play/pause
    const filename = `kishiface_audio_${postId}_${Date.now()}.webm`;
    kfDownloadFile(audioUrl, filename);
}

/**
 * Download image file
 */
function kfDownloadImage(postId, imageUrl, imageNumber) {
    event.stopPropagation(); // Prevent carousel slide
    const filename = `kishiface_image_${postId}_${imageNumber}_${Date.now()}.jpg`;
    kfDownloadFile(imageUrl, filename);
}

/**
 * Smart download for post media - handles multiple media types
 */
function kfDownloadPostMedia(postId, downloadIcon) {
    const hasVideo = downloadIcon.dataset.hasVideo === 'true';
    const hasAudio = downloadIcon.dataset.hasAudio === 'true';
    const hasImages = downloadIcon.dataset.hasImages === 'true';
    
    // If post has multiple media types, show download options
    if ((hasVideo && hasAudio) || (hasVideo && hasImages) || (hasAudio && hasImages)) {
        kfShowDownloadOptions(postId, hasVideo, hasAudio, hasImages);
        return;
    }
    
    // Single media type - download directly
    if (hasVideo) {
        const videoContainer = document.getElementById(`kf-container-${postId}`);
        const video = videoContainer?.querySelector('.kf-video source');
        if (video && video.src) {
            kfDownloadVideo(postId, video.src);
        }
    } else if (hasAudio) {
        const audioPlayer = document.getElementById(`kf-audio-${postId}`);
        const audio = audioPlayer?.querySelector('.kf-audio-hidden source');
        if (audio && audio.src) {
            kfDownloadAudio(postId, audio.src);
        }
    } else if (hasImages) {
        // Download first image
        const carousel = document.getElementById(`kf-carousel-${postId}`);
        const firstImage = carousel?.querySelector('.kf-image-slide img');
        if (firstImage && firstImage.src) {
            kfDownloadImage(postId, firstImage.src, 1);
        }
    }
}

/**
 * Show download options modal for posts with multiple media types
 */
function kfShowDownloadOptions(postId, hasVideo, hasAudio, hasImages) {
    // Create modal
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 2000;
    `;
    
    const modalContent = document.createElement('div');
    modalContent.style.cssText = `
        background: white;
        padding: 24px;
        border-radius: 12px;
        max-width: 300px;
        width: 90%;
        text-align: center;
    `;
    
    modalContent.innerHTML = `
        <h3 style="margin: 0 0 16px 0; color: var(--kf-text);">Download Options</h3>
        <p style="color: var(--kf-text-light); margin-bottom: 20px; font-size: 14px;">
            Select what you want to download:
        </p>
        <div style="display: flex; flex-direction: column; gap: 12px;">
            ${hasVideo ? '<button class="kf-download-option-btn" data-type="video" style="padding: 12px; background: var(--kf-primary); color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 500;">Download Video</button>' : ''}
            ${hasAudio ? '<button class="kf-download-option-btn" data-type="audio" style="padding: 12px; background: var(--kf-primary); color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 500;">Download Audio</button>' : ''}
            ${hasImages ? '<button class="kf-download-option-btn" data-type="images" style="padding: 12px; background: var(--kf-primary); color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 500;">Download Images</button>' : ''}
            <button class="kf-cancel-btn" style="padding: 12px; background: #f3f4f6; color: var(--kf-text); border: none; border-radius: 8px; cursor: pointer; font-weight: 500; margin-top: 8px;">Cancel</button>
        </div>
    `;
    
    modal.appendChild(modalContent);
    document.body.appendChild(modal);
    
    // Add event listeners
    modal.addEventListener('click', (e) => {
        if (e.target === modal || e.target.classList.contains('kf-cancel-btn')) {
            document.body.removeChild(modal);
        } else if (e.target.classList.contains('kf-download-option-btn')) {
            const type = e.target.dataset.type;
            kfHandleDownloadOption(postId, type);
            document.body.removeChild(modal);
        }
    });
}

/**
 * Handle download option selection
 */
function kfHandleDownloadOption(postId, type) {
    switch(type) {
        case 'video':
            const videoContainer = document.getElementById(`kf-container-${postId}`);
            const video = videoContainer?.querySelector('.kf-video source');
            if (video && video.src) {
                kfDownloadVideo(postId, video.src);
            }
            break;
            
        case 'audio':
            const audioPlayer = document.getElementById(`kf-audio-${postId}`);
            const audio = audioPlayer?.querySelector('.kf-audio-hidden source');
            if (audio && audio.src) {
                kfDownloadAudio(postId, audio.src);
            }
            break;
            
        case 'images':
            const carousel = document.getElementById(`kf-carousel-${postId}`);
            const images = carousel?.querySelectorAll('.kf-image-slide img');
            if (images && images.length > 0) {
                // Download all images
                images.forEach((img, index) => {
                    if (img.src && !img.src.includes('placeholder.jpg')) {
                        setTimeout(() => {
                            kfDownloadImage(postId, img.src, index + 1);
                        }, index * 500); // Stagger downloads
                    }
                });
            }
            break;
    }
}

// ===== VIDEO PLAYER CONTROLS =====

/**
 * Pauses all video and audio elements except the one currently starting.
 */
function kfPauseAllOtherMedia(currentMediaElement) {
    if (kfCurrentlyPlayingMedia && kfCurrentlyPlayingMedia !== currentMediaElement) {
        // Pause the previously playing media
        kfCurrentlyPlayingMedia.pause();
        
        // Reset video UI
        if (kfCurrentlyPlayingMedia.tagName === 'VIDEO') {
            const prevContainer = kfCurrentlyPlayingMedia.closest('.kf-video-container');
            if (prevContainer) {
                prevContainer.classList.add('paused');
                const prevPlayIcon = prevContainer.querySelector('.kf-play-pause-icon');
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
        kfCurrentlyPlayingMedia = currentMediaElement;
    }
}

/**
 * Toggles play/pause for the video.
 */
function kfTogglePlayPause(videoId, e) {
    // Prevent restarting if the click target is a seek button or download button
    if (e && (e.target.closest('.kf-seek-overlay-btn') || e.target.closest('.kf-video-download-btn'))) {
        return;
    }

    const video = document.getElementById(videoId);
    if (!video) return;

    if (video.paused || video.ended) {
        kfPauseAllOtherMedia(video);
        video.play().then(() => {
            // Video started playing
            const container = video.closest('.kf-video-container');
            if (container) {
                container.classList.remove('paused');
                const playIcon = container.querySelector('.kf-play-pause-icon');
                if (playIcon) playIcon.style.opacity = '0';
            }
        }).catch(error => {
            console.error("Video Play Error:", error);
        });
    } else {
        video.pause();
        const container = video.closest('.kf-video-container');
        if (container) {
            container.classList.add('paused');
            const playIcon = container.querySelector('.kf-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '1';
        }
    }
}

/**
 * Seeks the video forward or backward by a specified amount.
 */
function kfSeekVideo(videoId, seconds) {
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

// ===== AUDIO CONTROLS =====

// Format time as MM:SS
function kfFormatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

function kfToggleAudio(postId) {
  const audio = document.getElementById(`kf-audio-element-${postId}`);
  const icon = document.getElementById(`kf-audio-icon-${postId}`);
  
  if (!audio || !icon) return;
  
  if (audio.paused || audio.ended) {
    kfPauseAllOtherMedia(audio);
    
    audio.play().then(() => {
      icon.classList.remove('fa-play');
      icon.classList.add('fa-pause');
      
      // Update progress
      kfUpdateAudioProgress(postId);
      kfAudioTimers[postId] = setInterval(() => kfUpdateAudioProgress(postId), 250);
    }).catch(e => {
      console.error("Audio Play Error:", e);
    });
  } else {
    audio.pause();
    icon.classList.remove('fa-pause');
    icon.classList.add('fa-play');
    
    if (kfAudioTimers[postId]) {
      clearInterval(kfAudioTimers[postId]);
      delete kfAudioTimers[postId];
    }
  }
}

function kfUpdateAudioProgress(postId) {
  const audio = document.getElementById(`kf-audio-element-${postId}`);
  const progress = document.getElementById(`kf-audio-progress-${postId}`);
  const time = document.getElementById(`kf-audio-time-${postId}`);
  
  if (!audio || !audio.duration) return;
  
  const percent = (audio.currentTime / audio.duration) * 100;
  if (progress) progress.style.width = `${percent}%`;
  if (time) time.textContent = kfFormatTime(audio.currentTime);
}

function kfSeekAudio(event, postId) {
  const audio = document.getElementById(`kf-audio-element-${postId}`);
  const progressBar = event.currentTarget;
  const rect = progressBar.getBoundingClientRect();
  const percent = (event.clientX - rect.left) / rect.width;
  
  if (audio && audio.duration) {
    audio.currentTime = percent * audio.duration;
    kfUpdateAudioProgress(postId);
  }
}

function kfSeekAudioBy(postId, seconds) {
  const audio = document.getElementById(`kf-audio-element-${postId}`);
  if (audio) {
    audio.currentTime = Math.max(0, Math.min(audio.currentTime + seconds, audio.duration || Infinity));
    kfUpdateAudioProgress(postId);
  }
}

// ===== CAROUSEL CONTROLS =====
function kfSlideCarousel(postId, direction) {
  const carousel = document.getElementById(`kf-carousel-${postId}`);
  const track = document.getElementById(`kf-track-${postId}`);
  const indicators = carousel?.querySelectorAll('.kf-indicator');
  
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
let kfMediaObserver = null;

function kfInitMediaObserver() {
    kfMediaObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) {
                const container = entry.target;
                const video = container.querySelector('.kf-video');
                const audio = container.querySelector('.kf-audio-hidden');
                
                // Pause video if playing
                if (video && !video.paused) {
                    video.pause();
                    container.classList.add('paused');
                    const playIcon = container.querySelector('.kf-play-pause-icon');
                    if (playIcon) playIcon.style.opacity = '1';
                }
                
                // Pause audio if playing
                if (audio && !audio.paused) {
                    audio.pause();
                    const postId = audio.id.replace('kf-audio-element-', '');
                    const icon = document.getElementById(`kf-audio-icon-${postId}`);
                    if (icon) {
                        icon.classList.remove('fa-pause');
                        icon.classList.add('fa-play');
                    }
                    
                    // Stop audio timer
                    if (kfAudioTimers[postId]) {
                        clearInterval(kfAudioTimers[postId]);
                        delete kfAudioTimers[postId];
                    }
                }
            }
        });
    }, {
        threshold: 0.25
    });
}

// ===== PROFILE PANEL =====
function kfOpenProfilePanel(username) {
  if (window.innerWidth <= 768) return;
  
  fetch(`/popup/${username}/`)
    .then(res => res.text())
    .then(html => {
      document.getElementById('kf-profile-content').innerHTML = html;
      document.getElementById('kf-profile-panel').classList.add('open');
    });
}

function kfClosePanel(panelId) {
  document.getElementById(panelId)?.classList.remove('open');
}

// ===== INITIALIZATION =====
function kfInit() {
    // Initialize media observer
    kfInitMediaObserver();
    
    // --- Video Setup ---
    document.querySelectorAll('.kf-video-container').forEach(container => {
        const video = container.querySelector('.kf-video');
        if (!video) return;
        
        // Add to Intersection Observer
        if (kfMediaObserver) kfMediaObserver.observe(container);
        
        // Initial state - show play icon (paused by default)
        container.classList.add('paused');
        
        // Event listeners
        video.addEventListener('play', () => {
            container.classList.remove('paused');
            const playIcon = container.querySelector('.kf-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '0';
            kfCurrentlyPlayingMedia = video;
        });
        
        video.addEventListener('pause', () => {
            container.classList.add('paused');
            const playIcon = container.querySelector('.kf-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '1';
            if (kfCurrentlyPlayingMedia === video) kfCurrentlyPlayingMedia = null;
        });
        
        video.addEventListener('ended', () => {
            container.classList.add('paused');
            const playIcon = container.querySelector('.kf-play-pause-icon');
            if (playIcon) playIcon.style.opacity = '1';
            if (kfCurrentlyPlayingMedia === video) kfCurrentlyPlayingMedia = null;
        });
    });
    
    // --- Audio Setup ---
    document.querySelectorAll('.kf-audio-player').forEach(container => {
        const audio = container.querySelector('.kf-audio-hidden');
        if (!audio) return;
        
        const postId = audio.id.replace('kf-audio-element-', '');
        
        // Add to Intersection Observer
        if (kfMediaObserver) kfMediaObserver.observe(container);
        
        // Audio metadata
        audio.addEventListener('loadedmetadata', () => {
            kfUpdateAudioProgress(postId);
        });
        
        audio.addEventListener('play', () => {
            const icon = document.getElementById(`kf-audio-icon-${postId}`);
            if (icon) {
                icon.classList.remove('fa-play');
                icon.classList.add('fa-pause');
            }
            kfCurrentlyPlayingMedia = audio;
        });
        
        audio.addEventListener('pause', () => {
            const icon = document.getElementById(`kf-audio-icon-${postId}`);
            if (icon) {
                icon.classList.remove('fa-pause');
                icon.classList.add('fa-play');
            }
            
            if (kfAudioTimers[postId]) {
                clearInterval(kfAudioTimers[postId]);
                delete kfAudioTimers[postId];
            }
            
            if (kfCurrentlyPlayingMedia === audio) kfCurrentlyPlayingMedia = null;
        });
        
        audio.addEventListener('ended', () => {
            const icon = document.getElementById(`kf-audio-icon-${postId}`);
            if (icon) {
                icon.classList.remove('fa-pause');
                icon.classList.add('fa-play');
            }
            
            if (kfAudioTimers[postId]) {
                clearInterval(kfAudioTimers[postId]);
                delete kfAudioTimers[postId];
            }
            
            if (kfCurrentlyPlayingMedia === audio) kfCurrentlyPlayingMedia = null;
            
            // Reset progress
            kfUpdateAudioProgress(postId);
        });
    });
    
    // --- Profile Links ---
    document.querySelectorAll('.kf-username').forEach(link => {
        link.addEventListener('click', (e) => {
            if (window.innerWidth > 768) {
                e.preventDefault();
                const username = link.dataset.user;
                kfOpenProfilePanel(username);
            }
        });
    });
    
    // --- Resize Handler ---
    window.addEventListener('resize', () => {
        if (window.innerWidth <= 768) {
            kfClosePanel('kf-profile-panel');
            kfClosePanel('kf-comments-panel');
        }
    });
    
    // --- Cleanup ---
    window.addEventListener('beforeunload', () => {
        Object.values(kfAudioTimers).forEach(timer => clearInterval(timer));
    });
}

// ===== START WHEN READY =====
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', kfInit);
} else {
    kfInit();
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
