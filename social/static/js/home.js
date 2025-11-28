    // --- Global Media Tracking for Single Playback ---
    let currentlyPlayingMedia = null;

    /**
     * Pauses all video and audio elements except the one currently starting.
     * Enforces the "one media playing at a time" rule.
     * @param {HTMLElement} currentMediaElement - The media element that is about to play.
     */
    function pauseAllOtherMedia(currentMediaElement) {
        if (currentlyPlayingMedia && currentlyPlayingMedia !== currentMediaElement) {
            // 1. Pause the previously playing media
            currentlyPlayingMedia.pause();
            
            // 2. Reset the icon state for the previously playing media if it's a video
            if (currentlyPlayingMedia.tagName === 'VIDEO') {
                const prevContainer = currentlyPlayingMedia.closest('.instagram-video-container');
                const prevPlayIcon = prevContainer ? prevContainer.querySelector('.play-pause-icon') : null;
                
                if (prevContainer) prevContainer.classList.add('paused');
                if (prevPlayIcon) prevPlayIcon.style.opacity = '1';
                
            }
             // 3. Reset the icon state for the previously playing media if it's an audio
            else if (currentlyPlayingMedia.tagName === 'AUDIO') {
                const postId = currentlyPlayingMedia.id.split('-')[1];
                const prevIcon = document.getElementById('audio-icon-' + postId);
                if (prevIcon) {
                    prevIcon.classList.remove('fa-pause');
                    prevIcon.classList.add('fa-play');
                    prevIcon.style.opacity = '1';
                }
            }
        }
        
        // Update the globally tracked media element ONLY if it's playing
        if (currentMediaElement && currentMediaElement.paused === false) {
            currentlyPlayingMedia = currentMediaElement;
        } 
    }


    /** * Video Player Controls 
     */

    /**
     * Toggles play/pause for the video.
     * Prevents restarting if the click originated from an overlay control button.
     * @param {string} videoId - The ID of the video element.
     * @param {Event} e - The click event object.
     */
    function togglePlayPause(videoId, e) {
        // Safety check to prevent video restart if the click target is a control button
        if (e && e.target.closest('.seek-overlay-btn')) {
            // If the click hit a seek button, ignore the main video play/pause toggle.
            return;
        }

        const video = document.getElementById(videoId);

        if (video.paused || video.ended) {
            pauseAllOtherMedia(video); // Enforce single playback
            video.play().catch(error => console.error("Video Play Error:", error));
        } else {
            video.pause();
        }
    }

    
    /** * Seeks the video forward or backward by a specified amount.
     * @param {string} videoId - The ID of the video element.
     * @param {number} seconds - The number of seconds to move (e.g., -10 for backward, 10 for forward).
     */
    function seekVideo(videoId, seconds) {
        const video = document.getElementById(videoId);
        if (video) {
            // Calculate the new time
            let newTime = video.currentTime + seconds;
            
            // Clamp the new slide index between 0 and duration
            newTime = Math.max(0, newTime);
            newTime = Math.min(newTime, video.duration);
            
            // Set the new time
            video.currentTime = newTime;
        }
    }

    /** * Audio Player Controls 
     */
    function toggleAudioPlay(audioId) {
        const audio = document.getElementById(audioId);
        const postId = audioId.split('-')[1]; 
        const icon = document.getElementById('audio-icon-' + postId);
        
        if (audio.paused || audio.ended) {
            pauseAllOtherMedia(audio); // Enforce single playback

            audio.play().catch(e => console.error("Audio Play Error:", e));
            icon.classList.remove('fa-play');
            icon.classList.add('fa-pause');
            icon.style.opacity = '0'; // Hide icon when playing
        } else {
            audio.pause();
            icon.classList.remove('fa-pause');
            icon.classList.add('fa-play');
            icon.style.opacity = '1'; // Show icon when paused
        }
    }

    // ------------------------------------------------------------------
    // Intersection Observer for Auto Pause on Scroll (Instagram-like)
    // ------------------------------------------------------------------

    const mediaObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            const container = entry.target;
            const mediaElement = container.querySelector('.instagram-video, .audio-hidden');

            if (!mediaElement) return;

            if (!entry.isIntersecting) {
                // Media scrolled OUT of the viewport
                if (!mediaElement.paused) {
                    // Pause the element
                    mediaElement.pause();
                    // The pause event listener will handle clearing currentlyPlayingMedia
                }
            }
        });
    }, {
        // Media must be at least 25% visible
        threshold: 0.25 
    });


    // ------------------------------------------------------------------
    // Initialization
    // ------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        // --- 1. Video and Audio Initialization ---
        document.querySelectorAll('.instagram-video-container').forEach(container => {
            const video = container.querySelector('.instagram-video');
            const playIcon = container.querySelector('.play-pause-icon');

            // Add the container to the Intersection Observer
            mediaObserver.observe(container);

            // Initial setup: Handle Autoplay
            if (video.hasAttribute('autoplay')) {
                video.play().then(() => {
                    currentlyPlayingMedia = video;
                    container.classList.remove('paused');
                    playIcon.style.opacity = '0';
                }).catch(() => {
                    video.pause();
                    container.classList.add('paused');
                    playIcon.style.opacity = '1';
                });
            } else {
                container.classList.add('paused');
                playIcon.style.opacity = '1';
            }

            // Event listeners to sync UI state and global tracker
            video.addEventListener('pause', () => {
                container.classList.add('paused');
                playIcon.style.opacity = '1';
                if(currentlyPlayingMedia === video) currentlyPlayingMedia = null;
            });
            video.addEventListener('play', () => {
                container.classList.remove('paused');
                playIcon.style.opacity = '0';
            });
            video.addEventListener('ended', () => {
                container.classList.add('paused');
                playIcon.style.opacity = '1';
                if(currentlyPlayingMedia === video) currentlyPlayingMedia = null;
            });
        });
        
        document.querySelectorAll('.audio-post-container').forEach(container => {
            const audio = container.querySelector('.audio-hidden');
            const icon = container.querySelector('.audio-play-icon');

            // Add the container to the Intersection Observer
            mediaObserver.observe(container);
            
            // Sync icon state with audio state and global tracker
            audio.addEventListener('play', () => {
                icon.classList.remove('fa-play');
                icon.classList.add('fa-pause');
                icon.style.opacity = '0';
            });
            audio.addEventListener('pause', () => {
                icon.classList.remove('fa-pause');
                icon.classList.add('fa-play');
                icon.style.opacity = '1';
                if(currentlyPlayingMedia === audio) currentlyPlayingMedia = null;
            });
            audio.addEventListener('ended', () => {
                icon.classList.remove('fa-pause');
                icon.classList.add('fa-play');
                icon.style.opacity = '1';
                if(currentlyPlayingMedia === audio) currentlyPlayingMedia = null;
            });
            // Ensure initial icon is 'play'
            icon.classList.add('fa-play');
            icon.style.opacity = '1';
        });

        // --- 2. Other Initializations ---
        setupLinks();
        initCarousels();
        setupLink(); 
    });

    /** pop for profile modal code */

  function setupLinks(){
      const isMobile = window.matchMedia("(max-width: 668px)").matches;
    const userLink = document.querySelectorAll(".username-link");
    userLink.forEach(link =>{
        link.addEventListener('click', function(e){
            if(isMobile){
                return;
            }

            e.preventDefault();

            const userId = this.getAttribute("data-id");
            fetch(`/popup/${userId}/`)
            .then(res =>res.text())
            .then(html =>{
                document.getElementById("panelContent").innerHTML = html;

                document.getElementById("sidePanel").style.right=0;
            });
        });
    });
  }
    
    window.matchMedia("(max-width: 668px)").addEventListener('change', setupLinks());
    function closePanel(){
        document.getElementById('sidePanel').style.right='-400px';
    }
     /* Auto close popup when changing to Mobile */
     window.addEventListener('resize', function(){
         setupLinks();
        const isMobile = window.matchMedia("(max-width: 668px)").matches;
        if(isMobile){
            const panel = document.getElementById('sidePanel');
            panel.style.right = '-400px';
            panel.innerHTML='';
        }
     })

     /* pop for comment */

     function setupLink(){
      const isMobile = window.matchMedia("(max-width: 668px)").matches;
    const commentLink = document.querySelectorAll(".action-item");
    commentLink.forEach(link =>{
        link.addEventListener('click', function(e){
            if(isMobile){
                return;
            }

            e.preventDefault();

            const commentId = this.getAttribute("data-id");
            fetch(`/commentpopup/${commentId}/`)
            .then(res =>res.text())
            .then(html =>{
                document.getElementById("panelContent2").innerHTML = html;

                document.getElementById("sidePanel2").style.left=0;
            });
        });
    });
  }
    
     /* Auto close popup when changing to Mobile */
     window.addEventListener('resize', function(){
         setupLink();
        const isMobile = window.matchMedia("(max-width: 668px)").matches;
        if(isMobile){
            const panel2 = document.getElementById('sidePanel2');
            panel2.style.left = '-400px';
            panel2.innerHTML='';
        }
     })
function closePanel2(){
        document.getElementById('sidePanel2').style.left='-400px';
    }
    
  /**
   * Handles sliding of a post's image carousel.
   * @param {string} postId - The unique ID of the post.
   * @param {number} direction - -1 for previous, 1 for next.
   */
  function slidePost(postId, direction) {
    const carousel = document.getElementById(`carousel-${postId}`);
    const track = document.getElementById(`track-${postId}`);
    const indicatorsContainer = document.getElementById(`indicators-${postId}`);
    const prevButton = document.getElementById(`prev-${postId}`);
    const nextButton = document.getElementById(`next-${postId}`);

    if (!carousel || !track) return;

    let currentSlide = parseInt(carousel.getAttribute('data-current-slide') || '0');
    const totalSlides = parseInt(carousel.getAttribute('data-total-slides') || '1');

    if (totalSlides <= 1) return;

    let newSlide = currentSlide;

    if (direction !== 0) { // Only update slide index if direction is provided
        newSlide = currentSlide + direction;
    }

    // Clamp the new slide index
    if (newSlide < 0) {
      newSlide = 0;
    } else if (newSlide >= totalSlides) {
      newSlide = totalSlides - 1;
    }

    // 1. Update the slider position using CSS transform
    const slideWidth = carousel.clientWidth;
    const offset = newSlide * slideWidth;
    track.style.transform = `translateX(-${offset}px)`;

    // 2. Update the state attribute
    carousel.setAttribute('data-current-slide', newSlide);

    // 3. Update indicators
    if (indicatorsContainer) {
      indicatorsContainer.querySelectorAll('.indicator-dot').forEach((dot, index) => {
        dot.classList.toggle('active', index === newSlide);
      });
    }

    // 4. Update navigation buttons visibility
    if (prevButton) {
      prevButton.classList.toggle('hidden', newSlide === 0);
    }
    if (nextButton) {
      nextButton.classList.toggle('hidden', newSlide === totalSlides - 1);
    }
  }

  /**
   * Initializes all carousels on the page.
   */
  function initCarousels() {
    // Select all carousels that have more than one slide (checked by total-slides attribute)
    document.querySelectorAll('.post-image-carousel[data-total-slides]:not([data-total-slides="1"])').forEach(carousel => {
        const postId = carousel.id.split('-')[1];
        // Call slidePost with 0 direction to initialize current position and button visibility
        slidePost(postId, 0);
    });
  }

  // Ensure carousels are initialized and responsive on load and resize
  window.addEventListener('resize', initCarousels);
  // Re-run setupLinks and setupLink on window load for initial attachment
  window.addEventListener('load', () => {
    initCarousels();
    setupLinks();
    setupLink();
  });

  // Fallback for immediate execution if the document is already ready
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
      initCarousels();
      setupLinks();
      setupLink();
  }
