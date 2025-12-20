let currentlyPlayingMedia = null;

/**
 * Ensures only one audio/video plays at a time.
 */
function pauseAllOtherMedia(currentMedia) {
    if (currentlyPlayingMedia && currentlyPlayingMedia !== currentMedia) {
        currentlyPlayingMedia.pause();
        
        if (currentlyPlayingMedia.tagName === 'VIDEO') {
            currentlyPlayingMedia.closest('.instagram-video-container')?.classList.add('paused');
        } else if (currentlyPlayingMedia.tagName === 'AUDIO') {
            const id = currentlyPlayingMedia.id.split('-')[1];
            const icon = document.getElementById('audio-icon-' + id);
            const wave = document.getElementById('audio-wave-' + id);
            if (icon) icon.classList.replace('fa-pause', 'fa-play'), icon.style.opacity = '1';
            if (wave) wave.classList.remove('playing');
        }
    }
    currentlyPlayingMedia = currentMedia;
}

/**
 * Audio Controls with Visualizer Trigger
 */
function toggleAudioPlay(audioId) {
    const audio = document.getElementById(audioId);
    const id = audioId.split('-')[1];
    const icon = document.getElementById('audio-icon-' + id);
    const wave = document.getElementById('audio-wave-' + id);

    if (audio.paused) {
        pauseAllOtherMedia(audio);
        audio.play().catch(e => console.log("Play blocked"));
        icon.classList.replace('fa-play', 'fa-pause');
        icon.style.opacity = '0';
        wave?.classList.add('playing');
    } else {
        audio.pause();
        icon.classList.replace('fa-pause', 'fa-play');
        icon.style.opacity = '1';
        wave?.classList.remove('playing');
    }
}

/**
 * Video Controls
 */
function togglePlayPause(videoId, e) {
    if (e && e.target.closest('.seek-overlay-btn')) return;
    const video = document.getElementById(videoId);
    video.paused ? (pauseAllOtherMedia(video), video.play()) : video.pause();
}

function seekVideo(videoId, seconds) {
    const video = document.getElementById(videoId);
    if (video) video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
}

/**
 * Carousel Controls
 */
function slidePost(postId, direction) {
    const carousel = document.getElementById(`carousel-${postId}`);
    const track = document.getElementById(`track-${postId}`);
    let current = parseInt(carousel.getAttribute('data-current-slide') || '0');
    const total = parseInt(carousel.getAttribute('data-total-slides') || '1');
    let next = Math.max(0, Math.min(total - 1, current + direction));

    track.style.transform = `translateX(-${next * 100}%)`;
    carousel.setAttribute('data-current-slide', next);
    
    document.getElementById(`prev-${postId}`)?.classList.toggle('hidden', next === 0);
    document.getElementById(`next-${postId}`)?.classList.toggle('hidden', next === total - 1);
}

/**
 * PERFORMANCE: Smart Intersection Observer
 * Automatically pauses media when it scrolls out of view.
 */
const mediaObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        const media = entry.target.querySelector('video, audio');
        if (!entry.isIntersecting && media && !media.paused) {
            media.pause();
        }
    });
}, { threshold: 0.1 });

document.addEventListener('DOMContentLoaded', () => {
    // Observe all media containers
    document.querySelectorAll('.instagram-video-container, .audio-post-container').forEach(el => mediaObserver.observe(el));

    // Sync video UI with play/pause events
    document.querySelectorAll('.instagram-video').forEach(video => {
        const container = video.closest('.instagram-video-container');
        video.addEventListener('play', () => container.classList.remove('paused'));
        video.addEventListener('pause', () => container.classList.add('paused'));
        video.addEventListener('ended', () => container.classList.add('paused'));
    });
});

