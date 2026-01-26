
  let currentRepostPostId = null;
  let currentRepostButton = null;
  
  function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = 'kf-toast';
    toast.innerHTML = `
      <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
      <span>${message}</span>
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
      toast.style.animation = 'kfSlideOut 0.3s ease';
      setTimeout(() => {
        document.body.removeChild(toast);
      }, 300);
    }, 3000);
  }
  
  function kfToggleRepost(postId, button) {
    currentRepostPostId = postId;
    currentRepostButton = button;
    
    const isReposted = button.getAttribute('data-reposted') === 'true';
    
    if (isReposted) {
      kfPerformRepost(postId, '', true);
    } else {
      kfOpenRepostModal();
    }
  }
  
  function kfOpenRepostModal() {
    const modal = document.getElementById('kf-repost-modal');
    const textarea = document.getElementById('kf-repost-caption');
    const charCount = document.getElementById('kf-repost-char-count');
    
    textarea.value = '';
    charCount.textContent = '0';
    
    modal.classList.add('show');
    
    setTimeout(() => {
      textarea.focus();
    }, 100);
    
    textarea.addEventListener('input', function() {
      charCount.textContent = this.value.length;
    });
    
    const confirmBtn = document.getElementById('kf-repost-confirm-btn');
    confirmBtn.onclick = function() {
      kfPerformRepost(currentRepostPostId, textarea.value, false);
      kfCloseRepostModal();
    };
    
    textarea.addEventListener('input', function() {
      this.style.overflowX = 'hidden';
      this.style.width = '100%';
    });
    
    setTimeout(() => {
      const modalContent = modal.querySelector('.kf-repost-modal-content');
      const viewportHeight = window.innerHeight;
      const modalHeight = modalContent.offsetHeight;
      
      if (modalHeight > viewportHeight * 0.9) {
        modalContent.style.maxHeight = (viewportHeight * 0.9) + 'px';
      }
    }, 10);
  }
  
  function kfCloseRepostModal() {
    const modal = document.getElementById('kf-repost-modal');
    modal.classList.remove('show');
    currentRepostPostId = null;
    currentRepostButton = null;
  }
  
  function kfPerformRepost(postId, caption, undo = false) {
    const button = currentRepostButton;
    const icon = button.querySelector('i');
    const countSpan = button.querySelector('.kf-repost-count');
    
    const csrftoken = getCookie('csrftoken');
    
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    button.disabled = true;
    
    fetch(`/repost/${postId}/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrftoken,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        caption: caption,
        undo: undo
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        if (data.reposted) {
          showToast(data.message || 'Post reposted successfully!', 'success');
          button.setAttribute('data-reposted', 'true');
          icon.classList.add('reposted');
          
          if (data.repost_count > 0) {
            countSpan.textContent = data.repost_count;
            countSpan.classList.add('show');
          }
          
          setTimeout(() => {
            location.reload();
          }, 800);
        } else {
          showToast(data.message || 'Repost removed', 'info');
          button.setAttribute('data-reposted', 'false');
          icon.classList.remove('reposted');
          
          if (data.repost_count > 0) {
            countSpan.textContent = data.repost_count;
          } else {
            countSpan.classList.remove('show');
          }
          
          setTimeout(() => {
            location.reload();
          }, 800);
        }
      } else {
        showToast('Error: ' + data.error, 'error');
        button.innerHTML = originalText;
        button.disabled = false;
      }
    })
    .catch(error => {
      console.error('Error:', error);
      showToast('Something went wrong. Please try again.', 'error');
      button.innerHTML = originalText;
      button.disabled = false;
    });
  }
  
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }
  
  function kfToggleText(postId) {
    const textElement = document.getElementById(`kf-text-${postId}`);
    const button = textElement.nextElementSibling;
    if (!button || !button.classList.contains('kf-text-toggle')) return;
    
    const span = button.querySelector('span');
    const icon = button.querySelector('i');
    
    if (textElement.classList.contains('collapsed')) {
      textElement.classList.remove('collapsed');
      textElement.classList.add('expanded');
      span.textContent = 'less';
      icon.classList.remove('fa-chevron-down');
      icon.classList.add('fa-chevron-up');
    } else {
      textElement.classList.remove('expanded');
      textElement.classList.add('collapsed');
      span.textContent = 'more';
      icon.classList.remove('fa-chevron-up');
      icon.classList.add('fa-chevron-down');
    }
  }

  function kfDownloadAudio(postId, url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `kishiface_post_${postId}_audio.webm`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  
  function kfDownloadVideo(postId, url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `kishiface_post_${postId}_video.mp4`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  
  function kfDownloadImage(postId, url, filename) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `kishiface_post_${postId}_${filename}.jpg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  
  function kfToggleAudio(postId) {
    const audio = document.getElementById(`kf-audio-element-${postId}`);
    const icon = document.getElementById(`kf-audio-icon-${postId}`);
    
    if (audio.paused) {
      audio.play();
      icon.className = 'fas fa-pause';
    } else {
      audio.pause();
      icon.className = 'fas fa-play';
    }
    
    audio.addEventListener('timeupdate', function() {
      const progress = (audio.currentTime / audio.duration) * 100;
      document.getElementById(`kf-audio-progress-${postId}`).style.width = progress + '%';
      
      const minutes = Math.floor(audio.currentTime / 60);
      const seconds = Math.floor(audio.currentTime % 60);
      document.getElementById(`kf-audio-time-${postId}`).textContent = 
        minutes + ':' + (seconds < 10 ? '0' : '') + seconds;
    });
  }
  
  function kfSeekAudio(event, postId) {
    const audio = document.getElementById(`kf-audio-element-${postId}`);
    const progressBar = event.currentTarget;
    const rect = progressBar.getBoundingClientRect();
    const pos = (event.clientX - rect.left) / progressBar.offsetWidth;
    audio.currentTime = pos * audio.duration;
  }
  
  function kfSeekAudioBy(postId, seconds) {
    const audio = document.getElementById(`kf-audio-element-${postId}`);
    audio.currentTime = Math.max(0, audio.currentTime + seconds);
  }
  
  function kfTogglePlayPause(videoId, event) {
    event.stopPropagation();
    const video = document.getElementById(videoId);
    
    if (video.paused) {
      video.play();
      video.parentElement.classList.remove('paused');
    } else {
      video.pause();
      video.parentElement.classList.add('paused');
    }
  }
  
  function kfSeekVideo(videoId, seconds) {
    const video = document.getElementById(videoId);
    video.currentTime = Math.max(0, video.currentTime + seconds);
  }
  
  function kfSlideCarousel(postId, direction) {
    const carousel = document.getElementById(`kf-carousel-${postId}`);
    const track = document.getElementById(`kf-track-${postId}`);
    const totalSlides = parseInt(carousel.getAttribute('data-total'));
    let currentSlide = parseInt(carousel.getAttribute('data-slide'));
    
    currentSlide += direction;
    
    if (currentSlide < 0) currentSlide = totalSlides - 1;
    if (currentSlide >= totalSlides) currentSlide = 0;
    
    track.style.transform = `translateX(-${currentSlide * 100}%)`;
    carousel.setAttribute('data-slide', currentSlide);
    
    const indicators = carousel.querySelectorAll('.kf-indicator');
    indicators.forEach((indicator, index) => {
      if (index === currentSlide) {
        indicator.classList.add('active');
      } else {
        indicator.classList.remove('active');
      }
    });
  }

  // Comment input functionality
  const textInput = document.getElementById('textInput');
  const sendBtn = document.getElementById('sendBtn');
  const startBtn = document.getElementById('startBtn');
  const audioPreviewContainer = document.getElementById('audioPreviewContainer');
  const previewAudio = document.getElementById('previewAudio');
  const recordingStatus = document.getElementById('recordingStatus');
  const deleteAudioBtn = document.getElementById('deleteAudioBtn');
  const stopRecordingBtn = document.getElementById('stopRecordingBtn');
  const audio_file_input = document.getElementById('audio_file');
  const postForm = document.getElementById('postForm');
  
  let mediaRecorder;
  let audioChunks = [];
  let mediaStream;
  
  function switchToRecordingUI() {
    textInput.classList.add('record-mode-hidden');
    audioPreviewContainer.classList.remove('record-mode-hidden');
    startBtn.classList.add('record-mode-hidden');
    sendBtn.style.display = 'none';
    deleteAudioBtn.style.display = 'none';
    stopRecordingBtn.style.display = 'flex';
    deleteAudio(false);
    recordingStatus.innerHTML = `<i class="fa-solid fa-circle recording"></i> Recording...`;
  }
  
  function switchToPlaybackUI(audioURL) {
    startBtn.classList.add('record-mode-hidden');
    sendBtn.style.display = 'flex';
    deleteAudioBtn.style.display = 'flex';
    stopRecordingBtn.style.display = 'none';
    previewAudio.src = audioURL;
    previewAudio.load();
    previewAudio.controls = true; 
    recordingStatus.innerHTML = ``; 
  }

  function switchToTextInputUI() {
    textInput.classList.remove('record-mode-hidden');
    audioPreviewContainer.classList.add('record-mode-hidden');
    startBtn.classList.remove('record-mode-hidden');
    deleteAudioBtn.style.display = 'flex';
    stopRecordingBtn.style.display = 'none';
    updateSendButton();
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      
      if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
      }
    }
  }

  function deleteAudio(resetUI = true) {
      audio_file_input.files = null;
      previewAudio.src = '';
      previewAudio.controls = false; 
      previewAudio.load();
      if (resetUI) {
          switchToTextInputUI();
      }
  }

  function resetInputUI() {
    textInput.value = '';
    autoResizeTextarea();
    updateSendButton();
    deleteAudio(true);
  }

  function updateSendButton() {
    const hasText = textInput.value.trim().length > 0;
    const hasAudio = audio_file_input.files && audio_file_input.files.length > 0;
    const hasImage = document.getElementById('image').files && document.getElementById('image').files.length > 0;
    
    if (hasText || hasAudio || hasImage) {
      sendBtn.style.display = 'flex';
      startBtn.classList.add('record-mode-hidden');
    } else {
      sendBtn.style.display = 'none';
      startBtn.classList.remove('record-mode-hidden');
    }
  }

  function autoResizeTextarea() {
    const textarea = textInput;
    textarea.style.height = 'auto';
    const maxHeight = 100;
    const newHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = newHeight + 'px';
    
    const wrapper = textarea.closest('.kf-comment-input-wrapper');
    if (wrapper) {
      wrapper.style.minHeight = (42 + Math.max(0, newHeight - 24)) + 'px';
    }
  }

  startBtn.addEventListener('click', async function(){
    if(textInput.value.trim() !== '') {
        alert('Please clear your text caption or send it before recording a voice note.');
        return;
    }
    
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(mediaStream);
      audioChunks = [];
      
      mediaRecorder.ondataavailable = event => {
        audioChunks.push(event.data);
      };
      
      mediaRecorder.onstop = () => {
        mediaStream.getTracks().forEach(track => track.stop());
        
        const blob = new Blob(audioChunks, {
          type: 'audio/webm'
        });
        const file = new File([blob], 'recorded_audio.webm', {
          type: 'audio/webm'
        });
        
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        audio_file_input.files = dataTransfer.files;

        const audioURL = URL.createObjectURL(blob);
        switchToPlaybackUI(audioURL);
        updateSendButton();
      };
      
      mediaRecorder.start();
      switchToRecordingUI();
      
    } catch(err) {
      console.error('Microphone access denied:', err);
      alert('Microphone access was denied. Please allow access in your browser settings to record voice notes.');
      switchToTextInputUI();
    }
  });

  stopRecordingBtn.addEventListener('click', function() {
    stopRecording();
  });

  deleteAudioBtn.onclick = () => deleteAudio(true); 

  function initInputUI() {
    updateSendButton();
    autoResizeTextarea();
    
    textInput.addEventListener('input', function() {
      updateSendButton();
      autoResizeTextarea();
    });
    
    textInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (sendBtn.style.display !== 'none') {
          postForm.submit();
        }
      }
    });
    
    textInput.addEventListener('input', autoResizeTextarea);
    
    document.getElementById('image').addEventListener('change', function() {
      updateSendButton();
    });
    
    postForm.addEventListener('submit', function() {
      setTimeout(() => {}, 100);
    });
    
    document.body.addEventListener('htmx:afterRequest', function(event) {
      if (event.target.id === 'postForm' && event.detail.successful) {
        resetInputUI();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', initInputUI);

  function initAudioWave(container, audioId) {
    const wave = container.querySelector('.audio-wave');
    if (!wave) return;
    
    const bars = wave.querySelectorAll('.wave-bar');
    const audio = container.querySelector('.hidden-audio');
    
    if (audio && bars.length > 0) {
      bars.forEach((bar, index) => {
        const baseHeight = [4, 6, 8, 6, 4][index] || 4;
        bar.style.height = baseHeight + 'px';
      });
      
      audio.addEventListener('play', function() {
        container.classList.add('playing');
        bars.forEach((bar, index) => {
          const baseHeight = [4, 6, 8, 6, 4][index] || 4;
          bar.style.height = baseHeight + 'px';
        });
      });
      
      audio.addEventListener('pause', function() {
        container.classList.remove('playing');
        bars.forEach((bar, index) => {
          const baseHeight = [4, 6, 8, 6, 4][index] || 4;
          bar.style.height = baseHeight + 'px';
        });
      });
      
      audio.addEventListener('ended', function() {
        container.classList.remove('playing');
        bars.forEach((bar, index) => {
          const baseHeight = [4, 6, 8, 6, 4][index] || 4;
          bar.style.height = baseHeight + 'px';
        });
      });
    }
  }

  function kfDownloadCommentAudio(id, url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `voice_message_${id}.webm`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const audioContainers = document.querySelectorAll('.audio-container');
    const allAudioElements = document.querySelectorAll('.hidden-audio');

    const formatTime = (seconds) => {
        if (isNaN(seconds)) return '0:00';
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
    };

    const pauseOthers = (currentAudio) => {
        allAudioElements.forEach(audio => {
            if (audio !== currentAudio && !audio.paused) {
                audio.pause();
                const container = audio.closest('.audio-container');
                if (container) {
                    container.classList.remove('playing');
                    const btn = container.querySelector('.play-pause-btn');
                    const icon = btn.querySelector('i');
                    icon.className = 'fas fa-play';
                    btn.setAttribute('data-state', 'paused');
                }
            }
        });
    };

    audioContainers.forEach(container => {
        const audio = container.querySelector('.hidden-audio');
        const playPauseBtn = container.querySelector('.play-pause-btn');
        const icon = playPauseBtn.querySelector('i');
        const progressBar = container.querySelector('.progress-bar');
        const progressFilled = container.querySelector('.progress-filled');
        const timeDisplay = container.querySelector('.time-display');
        const audioId = container.dataset.src ? container.dataset.src.split('/').pop().split('.')[0] : '';

        if (audioId) {
            initAudioWave(container, audioId);
        }

        audio.onloadedmetadata = () => {
            if (audio.duration && !isNaN(audio.duration)) {
                timeDisplay.textContent = formatTime(audio.duration);
            }
        };

        playPauseBtn.addEventListener('click', () => {
            if (audio.paused || audio.ended) {
                pauseOthers(audio); 
                audio.play();
                container.classList.add('playing');
                icon.className = 'fas fa-pause';
                playPauseBtn.setAttribute('data-state', 'playing');
            } else {
                audio.pause();
                container.classList.remove('playing');
                icon.className = 'fas fa-play';
                playPauseBtn.setAttribute('data-state', 'paused');
            }
        });

        audio.addEventListener('timeupdate', () => {
            const progress = (audio.currentTime / audio.duration) * 100;
            progressFilled.style.width = `${progress}%`;
            timeDisplay.textContent = formatTime(audio.currentTime); 
        });

        audio.addEventListener('ended', () => {
            audio.currentTime = 0;
            container.classList.remove('playing');
            icon.className = 'fas fa-play';
            playPauseBtn.setAttribute('data-state', 'paused');
            progressFilled.style.width = '0%';
            if (audio.duration && !isNaN(audio.duration)) {
                timeDisplay.textContent = formatTime(audio.duration);
            }
        });

        progressBar.addEventListener('click', (e) => {
            const rect = progressBar.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const percentage = clickX / rect.width;
            
            audio.currentTime = audio.duration * percentage;
            
            if (audio.paused) {
                 pauseOthers(audio);
                 container.classList.add('playing');
                 audio.play();
                 icon.className = 'fas fa-pause';
                 playPauseBtn.setAttribute('data-state', 'playing');
            }
        });
    });
    
    // Auto-detect long text and add toggle buttons
    document.querySelectorAll('.kf-post-text').forEach(textElement => {
      const textContent = textElement.textContent.trim();
      const lineCount = (textContent.match(/\n/g) || []).length + 1;
      const charCount = textContent.length;
      
      if (charCount > 150 || lineCount > 3) {
        textElement.classList.add('collapsed');
        if (!textElement.nextElementSibling || !textElement.nextElementSibling.classList.contains('kf-text-toggle')) {
          const toggleBtn = document.createElement('button');
          toggleBtn.className = 'kf-text-toggle';
          toggleBtn.innerHTML = '<span>more</span><i class="fas fa-chevron-down"></i>';
          toggleBtn.onclick = function() {
            kfToggleText(textElement.id.replace('kf-text-', ''));
          };
          textElement.parentNode.insertBefore(toggleBtn, textElement.nextSibling);
        }
      }
    });
    
    // Desktop logout functionality
    const desktopLogoutIcon = document.getElementById('desktopLogoutIcon');
    if (desktopLogoutIcon) {
      desktopLogoutIcon.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        const logoutModal = document.getElementById('logoutModal');
        if (logoutModal) {
          logoutModal.classList.add('active');
          
          const cancelLogout = document.getElementById('cancelLogout');
          const confirmLogout = document.getElementById('confirmLogout');
          
          if (cancelLogout) {
            cancelLogout.onclick = function() {
              logoutModal.classList.remove('active');
            };
          }
          
          if (confirmLogout) {
            confirmLogout.onclick = function() {
              window.location.href = "{% url 'logout' %}";
            };
          }
          
          logoutModal.addEventListener('click', function(e) {
            if (e.target === logoutModal) {
              logoutModal.classList.remove('active');
            }
          });
        }
      });
    }
    
    document.getElementById('kf-repost-modal').addEventListener('click', function(e) {
      if (e.target === this) {
        kfCloseRepostModal();
      }
    });
    
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        kfCloseRepostModal();
        const logoutModal = document.getElementById('logoutModal');
        if (logoutModal && logoutModal.classList.contains('active')) {
          logoutModal.classList.remove('active');
        }
      }
    });
    
    window.addEventListener('resize', function() {
      const modal = document.getElementById('kf-repost-modal');
      if (modal.classList.contains('show')) {
        const modalContent = modal.querySelector('.kf-repost-modal-content');
        const viewportHeight = window.innerHeight;
        const modalHeight = modalContent.offsetHeight;
        
        if (modalHeight > viewportHeight * 0.9) {
          modalContent.style.maxHeight = (viewportHeight * 0.9) + 'px';
        } else {
          modalContent.style.maxHeight = '';
        }
      }
    });
});

function kfLazyLoad() {
  const lazyImages = document.querySelectorAll('img[loading="lazy"]');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const img = entry.target;
        img.classList.add('loaded');
      }
    });
  }, { rootMargin: '100px' });
  
  lazyImages.forEach(img => observer.observe(img));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', kfLazyLoad);
} else {
  kfLazyLoad();
}
