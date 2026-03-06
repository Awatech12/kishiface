 function getCsrfFromMeta(){
    return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
   }
  let currentRepostPostId = null;
  let currentRepostButton = null;
  
  function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = 'kvibe-toast';
    toast.innerHTML = `
      <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
      <span>${message}</span>
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
      toast.style.animation = 'kvibeSlideOut 0.3s ease';
      setTimeout(() => {
        document.body.removeChild(toast);
      }, 300);
    }, 3000);
  }
  
  function kvibeToggleRepost(postId, button) {
    currentRepostPostId = postId;
    currentRepostButton = button;
    
    const isReposted = button.getAttribute('data-reposted') === 'true';
    
    if (isReposted) {
      kvibePerformRepost(postId, '', true);
    } else {
      kvibeOpenRepostModal();
    }
  }
  
  function kvibeOpenRepostModal() {
    const modal = document.getElementById('kvibe-repost-modal');
    const textarea = document.getElementById('kvibe-repost-caption');
    const charCount = document.getElementById('kvibe-repost-char-count');
    
    textarea.value = '';
    charCount.textContent = '0';
    
    modal.classList.add('show');
    
    setTimeout(() => {
      textarea.focus();
    }, 100);
    
    textarea.addEventListener('input', function() {
      charCount.textContent = this.value.length;
    });
    
    const confirmBtn = document.getElementById('kvibe-repost-confirm-btn');
    confirmBtn.onclick = function() {
      kvibePerformRepost(currentRepostPostId, textarea.value, false);
      kvibeCloseRepostModal();
    };
    
    textarea.addEventListener('input', function() {
      this.style.overflowX = 'hidden';
      this.style.width = '100%';
    });
    
    setTimeout(() => {
      const modalContent = modal.querySelector('.kvibe-repost-modal-content');
      const viewportHeight = window.innerHeight;
      const modalHeight = modalContent.offsetHeight;
      
      if (modalHeight > viewportHeight * 0.9) {
        modalContent.style.maxHeight = (viewportHeight * 0.9) + 'px';
      }
    }, 10);
  }
  
  function kvibeCloseRepostModal() {
    const modal = document.getElementById('kvibe-repost-modal');
    modal.classList.remove('show');
    currentRepostPostId = null;
    currentRepostButton = null;
  }
  
  function kvibePerformRepost(postId, caption, undo = false) {
    const button = currentRepostButton;
    const icon = button.querySelector('i');
    const countSpan = button.querySelector('.kvibe-repost-count');

    const originalHTML = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    button.disabled = true;

    fetch(`/repost/${postId}/`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfFromMeta(),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ caption: caption, undo: undo })
    })
    .then(response => response.json())
    .then(data => {
      button.disabled = false;
      if (data.success) {
        if (data.reposted) {
          showToast(data.message || 'Post reposted successfully!', 'success');
          button.setAttribute('data-reposted', 'true');
          // Restore button with updated reposted state
          button.innerHTML = originalHTML;
          const freshIcon = button.querySelector('i');
          if (freshIcon) freshIcon.classList.add('reposted');
          if (countSpan) {
            countSpan.textContent = data.repost_count > 0 ? data.repost_count : '';
            if (data.repost_count > 0) countSpan.classList.add('show');
          }
        } else {
          showToast(data.message || 'Repost removed', 'info');
          button.setAttribute('data-reposted', 'false');
          button.innerHTML = originalHTML;
          const freshIcon = button.querySelector('i');
          if (freshIcon) freshIcon.classList.remove('reposted');
          if (countSpan) {
            if (data.repost_count > 0) {
              countSpan.textContent = data.repost_count;
            } else {
              countSpan.textContent = '';
              countSpan.classList.remove('show');
            }
          }
        }
      } else {
        showToast('Error: ' + data.error, 'error');
        button.innerHTML = originalHTML;
      }
    })
    .catch(error => {
      console.error('Error:', error);
      showToast('Something went wrong. Please try again.', 'error');
      button.innerHTML = originalHTML;
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
  
  function kvibeToggleText(postId) {
    const textElement = document.getElementById(`kvibe-text-${postId}`);
    const button = textElement.nextElementSibling;
    if (!button || !button.classList.contains('kvibe-text-toggle')) return;
    
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

  function kvibeDownloadVideo(postId, url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `kishiface_post_${postId}_video.mp4`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  
  function kvibeDownloadImage(postId, url, filename) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `kishiface_post_${postId}_${filename}.jpg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }
  
  function kvibeTogglePlayPause(videoId, event) {
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
  
  function kvibeSeekVideo(videoId, seconds) {
    const video = document.getElementById(videoId);
    video.currentTime = Math.max(0, video.currentTime + seconds);
  }
  
  function kvibeSlideCarousel(postId, direction) {
    const carousel = document.getElementById(`kvibe-carousel-${postId}`);
    const track = document.getElementById(`kvibe-track-${postId}`);
    const totalSlides = parseInt(carousel.getAttribute('data-total'));
    let currentSlide = parseInt(carousel.getAttribute('data-slide'));
    
    currentSlide += direction;
    
    if (currentSlide < 0) currentSlide = totalSlides - 1;
    if (currentSlide >= totalSlides) currentSlide = 0;
    
    track.style.transform = `translateX(-${currentSlide * 100}%)`;
    carousel.setAttribute('data-slide', currentSlide);
    
    const indicators = carousel.querySelectorAll('.kvibe-indicator');
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
    
    const wrapper = textarea.closest('.kvibe-comment-input-wrapper');
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
    const wave = container.querySelector('.kvibe-audio-wave');
    if (!wave) return;
    
    const bars = wave.querySelectorAll('.kvibe-wave-bar');
    const audio = container.querySelector('.kvibe-hidden-audio');
    
    if (audio && bars.length > 0) {
      const baseHeights = [4, 7, 10, 7, 4];
      bars.forEach((bar, index) => {
        bar.style.height = (baseHeights[index] || 4) + 'px';
      });
      
      let waveInterval;

      audio.addEventListener('play', function() {
        container.classList.add('playing');
        waveInterval = setInterval(() => {
          bars.forEach((bar, index) => {
            bar.style.height = (baseHeights[index] + Math.random() * 5) + 'px';
          });
        }, 150);
      });
      
      audio.addEventListener('pause', function() {
        container.classList.remove('playing');
        clearInterval(waveInterval);
        bars.forEach((bar, index) => {
          bar.style.height = (baseHeights[index] || 4) + 'px';
        });
      });
      
      audio.addEventListener('ended', function() {
        container.classList.remove('playing');
        clearInterval(waveInterval);
        bars.forEach((bar, index) => {
          bar.style.height = (baseHeights[index] || 4) + 'px';
        });
      });
    }
  }

  function kvibeDownloadCommentAudio(id, url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = `voice_message_${id}.webm`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const audioContainers = document.querySelectorAll('.kvibe-audio-container');
    const allAudioElements = document.querySelectorAll('.kvibe-hidden-audio');

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
                const container = audio.closest('.kvibe-audio-container');
                if (container) {
                    container.classList.remove('playing');
                    const btn = container.querySelector('.kvibe-play-pause-btn');
                    if (btn) {
                        const icon = btn.querySelector('i');
                        if (icon) icon.className = 'fas fa-play';
                        btn.setAttribute('data-state', 'paused');
                    }
                }
            }
        });
    };

    audioContainers.forEach(container => {
        const audio = container.querySelector('.kvibe-hidden-audio');
        const playPauseBtn = container.querySelector('.kvibe-play-pause-btn');
        if (!audio || !playPauseBtn) return;

        const icon = playPauseBtn.querySelector('i');
        const progressBar = container.querySelector('.kvibe-progress-bar');
        const progressFilled = container.querySelector('.kvibe-progress-filled');
        const timeDisplay = container.querySelector('.kvibe-time-display');
        const audioId = container.dataset.src ? container.dataset.src.split('/').pop().split('.')[0] : '';

        if (audioId) initAudioWave(container, audioId);

        audio.onloadedmetadata = () => {
            if (audio.duration && !isNaN(audio.duration) && timeDisplay) {
                timeDisplay.textContent = formatTime(audio.duration);
            }
        };

        playPauseBtn.addEventListener('click', () => {
            if (audio.paused || audio.ended) {
                pauseOthers(audio);
                audio.play();
                container.classList.add('playing');
                if (icon) icon.className = 'fas fa-pause';
                playPauseBtn.setAttribute('data-state', 'playing');
            } else {
                audio.pause();
                container.classList.remove('playing');
                if (icon) icon.className = 'fas fa-play';
                playPauseBtn.setAttribute('data-state', 'paused');
            }
        });

        audio.addEventListener('timeupdate', () => {
            if (!audio.duration) return;
            const progress = (audio.currentTime / audio.duration) * 100;
            if (progressFilled) progressFilled.style.width = `${progress}%`;
            if (timeDisplay) timeDisplay.textContent = formatTime(audio.currentTime);
        });

        audio.addEventListener('ended', () => {
            audio.currentTime = 0;
            container.classList.remove('playing');
            if (icon) icon.className = 'fas fa-play';
            playPauseBtn.setAttribute('data-state', 'paused');
            if (progressFilled) progressFilled.style.width = '0%';
            if (audio.duration && !isNaN(audio.duration) && timeDisplay) {
                timeDisplay.textContent = formatTime(audio.duration);
            }
        });

        if (progressBar) {
            progressBar.addEventListener('click', (e) => {
                const rect = progressBar.getBoundingClientRect();
                const percentage = (e.clientX - rect.left) / rect.width;
                audio.currentTime = audio.duration * percentage;
                if (audio.paused) {
                    pauseOthers(audio);
                    container.classList.add('playing');
                    audio.play();
                    if (icon) icon.className = 'fas fa-pause';
                    playPauseBtn.setAttribute('data-state', 'playing');
                }
            });
        }
    });
    
    // Re-init audio players when HTMX injects new comments
    if (typeof htmx !== 'undefined') {
      htmx.onLoad(function(el) {
        const newContainers = el.querySelectorAll ? el.querySelectorAll('.kvibe-audio-container') : [];
        const allAudios = document.querySelectorAll('.kvibe-hidden-audio');

        const fmt = (s) => {
          if (isNaN(s)) return '0:00';
          return `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
        };

        newContainers.forEach(container => {
          if (container._kvibeAudioInited) return;
          container._kvibeAudioInited = true;

          const audio = container.querySelector('.kvibe-hidden-audio');
          const playPauseBtn = container.querySelector('.kvibe-play-pause-btn');
          if (!audio || !playPauseBtn) return;

          const icon = playPauseBtn.querySelector('i');
          const progressBar = container.querySelector('.kvibe-progress-bar');
          const progressFilled = container.querySelector('.kvibe-progress-filled');
          const timeDisplay = container.querySelector('.kvibe-time-display');
          const audioId = container.dataset.src ? container.dataset.src.split('/').pop().split('.')[0] : '';
          if (audioId) initAudioWave(container, audioId);

          audio.onloadedmetadata = () => {
            if (!isNaN(audio.duration) && timeDisplay) timeDisplay.textContent = fmt(audio.duration);
          };

          playPauseBtn.addEventListener('click', () => {
            if (audio.paused || audio.ended) {
              allAudios.forEach(a => {
                if (a !== audio && !a.paused) {
                  a.pause();
                  const c = a.closest('.kvibe-audio-container');
                  if (c) {
                    c.classList.remove('playing');
                    const b = c.querySelector('.kvibe-play-pause-btn i');
                    if (b) b.className = 'fas fa-play';
                  }
                }
              });
              audio.play();
              container.classList.add('playing');
              if (icon) icon.className = 'fas fa-pause';
            } else {
              audio.pause();
              container.classList.remove('playing');
              if (icon) icon.className = 'fas fa-play';
            }
          });

          audio.addEventListener('timeupdate', () => {
            if (!audio.duration) return;
            if (progressFilled) progressFilled.style.width = `${(audio.currentTime/audio.duration)*100}%`;
            if (timeDisplay) timeDisplay.textContent = fmt(audio.currentTime);
          });

          audio.addEventListener('ended', () => {
            container.classList.remove('playing');
            if (icon) icon.className = 'fas fa-play';
            if (progressFilled) progressFilled.style.width = '0%';
            if (!isNaN(audio.duration) && timeDisplay) timeDisplay.textContent = fmt(audio.duration);
          });

          if (progressBar) {
            progressBar.addEventListener('click', (e) => {
              const pct = (e.clientX - progressBar.getBoundingClientRect().left) / progressBar.offsetWidth;
              audio.currentTime = audio.duration * pct;
              if (audio.paused) { audio.play(); container.classList.add('playing'); if (icon) icon.className = 'fas fa-pause'; }
            });
          }
        });
      });
    }
    document.querySelectorAll('.kvibe-post-text').forEach(textElement => {
      const textContent = textElement.textContent.trim();
      const lineCount = (textContent.match(/\n/g) || []).length + 1;
      const charCount = textContent.length;
      
      if (charCount > 150 || lineCount > 3) {
        textElement.classList.add('collapsed');
        if (!textElement.nextElementSibling || !textElement.nextElementSibling.classList.contains('kvibe-text-toggle')) {
          const toggleBtn = document.createElement('button');
          toggleBtn.className = 'kvibe-text-toggle';
          toggleBtn.innerHTML = '<span>more</span><i class="fas fa-chevron-down"></i>';
          toggleBtn.onclick = function() {
            kvibeToggleText(textElement.id.replace('kvibe-text-', ''));
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
        
        const logoutModal = document.getElementById('kvibeLogoutModal');
        if (logoutModal) {
          logoutModal.classList.add('active');
          
          const cancelLogout = document.getElementById('kvibeCancelLogout');
          const confirmLogout = document.getElementById('kvibeConfirmLogout');
          
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
    
    document.getElementById('kvibe-repost-modal').addEventListener('click', function(e) {
      if (e.target === this) {
        kvibeCloseRepostModal();
      }
    });
    
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        kvibeCloseRepostModal();
        const logoutModal = document.getElementById('kvibeLogoutModal');
        if (logoutModal && logoutModal.classList.contains('active')) {
          logoutModal.classList.remove('active');
        }
      }
    });
    
    window.addEventListener('resize', function() {
      const modal = document.getElementById('kvibe-repost-modal');
      if (modal.classList.contains('show')) {
        const modalContent = modal.querySelector('.kvibe-repost-modal-content');
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

function kvibeLazyLoad() {
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
  document.addEventListener('DOMContentLoaded', kvibeLazyLoad);
} else {
  kvibeLazyLoad();
}

  // ── Mixed media carousel ──
  function kvibeSlideMixedCarousel(postId, direction) {
    const carousel = document.getElementById(`kvibe-mixed-carousel-${postId}`);
    const track = document.getElementById(`kvibe-mixed-track-${postId}`);
    const total = parseInt(carousel.dataset.total);
    let current = (parseInt(carousel.dataset.slide) + direction + total) % total;
    track.style.transform = `translateX(-${current * 100}%)`;
    carousel.dataset.slide = current;
    carousel.querySelectorAll('.kvibe-mixed-indicator').forEach((ind, i) => {
      ind.classList.toggle('active', i === current);
    });
  }

  function kvibeGoToMixedSlide(postId, index) {
    const carousel = document.getElementById(`kvibe-mixed-carousel-${postId}`);
    const track = document.getElementById(`kvibe-mixed-track-${postId}`);
    track.style.transform = `translateX(-${index * 100}%)`;
    carousel.dataset.slide = index;
    carousel.querySelectorAll('.kvibe-mixed-indicator').forEach((ind, i) => {
      ind.classList.toggle('active', i === index);
    });
  }

  // ── Follow / Unfollow ──
  function kvibeToggleFollow(btn) {
    const userId = btn.dataset.userId;
    const username = btn.dataset.username;
    const isFollowing = btn.classList.contains('kvibe-follow-btn--following');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    fetch(`/follow/${userId}/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrfFromMeta(), 'Content-Type': 'application/json' }
    })
    .then(r => r.json())
    .then(data => {
      btn.disabled = false;
      if (data.success) {
        if (data.followed) {
          btn.classList.add('kvibe-follow-btn--following');
          btn.title = `Unfollow ${username}`;
          btn.innerHTML = '<i class="fas fa-user-check"></i><span>Following</span>';
          showToast(`Following @${username}`, 'success');
        } else {
          btn.classList.remove('kvibe-follow-btn--following');
          btn.title = `Follow ${username}`;
          btn.innerHTML = '<i class="fas fa-user-plus"></i><span>Follow</span>';
          showToast(`Unfollowed @${username}`, 'info');
        }
      } else {
        btn.innerHTML = isFollowing
          ? '<i class="fas fa-user-check"></i><span>Following</span>'
          : '<i class="fas fa-user-plus"></i><span>Follow</span>';
      }
    })
    .catch(() => {
      btn.disabled = false;
      btn.innerHTML = isFollowing
        ? '<i class="fas fa-user-check"></i><span>Following</span>'
        : '<i class="fas fa-user-plus"></i><span>Follow</span>';
    });
  }

  // ── Lazy-load videos (data-src) ──
  function kvibeVideoLazyLoad() {
    document.querySelectorAll('video[data-src]').forEach(video => {
      new IntersectionObserver((entries, obs) => {
        entries.forEach(e => {
          if (e.isIntersecting) {
            const source = e.target.querySelector('source[data-src]');
            if (source) {
              source.src = source.dataset.src;
              e.target.load();
              e.target.removeAttribute('data-src');
            }
            obs.unobserve(e.target);
          }
        });
      }, { rootMargin: '300px' }).observe(video);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', kvibeVideoLazyLoad);
  } else {
    kvibeVideoLazyLoad();
  }


/* ═══════════════════════════════════════════════════════
   LIVE COMMENT POLLING
   Polls /comments/poll/<post_id>/?after=<last_id> every 3s
   and injects only new comments — no page reload needed.
   ═══════════════════════════════════════════════════════ */
(function kvibeStartLiveComments() {
  document.addEventListener('DOMContentLoaded', function () {
    const list = document.getElementById('comment_list');
    if (!list) return;

    // Post UUID is in the comments form action: /comments/<uuid>/
    const form = document.getElementById('postForm');
    if (!form) return;
    const match = form.getAttribute('action').match(/\/comments\/([0-9a-f-]{36})\/?/i);
    if (!match) return;
    const postId = match[1];

    // Track the newest created_at timestamp we've seen (ISO string)
    // Seeded from the data-created attribute on the first rendered comment
    function getLatestTimestamp() {
      const comments = list.querySelectorAll('[id^="kvibe-comment-"]');
      let latest = null;
      comments.forEach(el => {
        const ts = el.dataset.created;
        if (ts && (!latest || ts > latest)) latest = ts;
      });
      return latest || '';
    }

    // Remove empty state if comments appear
    function removeEmptyState() {
      const empty = list.querySelector('.kvibe-no-comments');
      if (empty) empty.remove();
    }

    // Avoid injecting a comment the current user just submitted via HTMX
    // (it's already in the DOM — the server would return it again in the poll)
    function alreadyInDOM(html) {
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      const ids = [...tmp.querySelectorAll('[id^="kvibe-comment-"]')].map(el => el.id);
      return ids.every(id => !!document.getElementById(id));
    }

    let polling = true;

    async function poll() {
      if (!polling) return;
      try {
        const after = encodeURIComponent(getLatestTimestamp());
        const res = await fetch(`/comments/poll/${postId}/?after=${after}`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });

        // 204 = nothing new
        if (res.status === 204) return;
        if (!res.ok) return;

        const html = await res.text();
        if (!html || !html.trim()) return;

        // Skip if every comment in the response is already rendered
        if (alreadyInDOM(html)) return;

        removeEmptyState();
        list.insertAdjacentHTML('afterbegin', html);

        // Re-init interactive features on newly injected nodes
        if (typeof kvibeInitAudioPlayers === 'function') kvibeInitAudioPlayers(list);
        if (typeof kvibeAttachReplyLikes  === 'function') kvibeAttachReplyLikes(list);

      } catch (e) {
        // Silently swallow network errors — retries on next tick
      } finally {
        if (polling) setTimeout(poll, 3000);
      }
    }

    // Pause polling while user is actively typing (avoids jarring DOM shifts)
    const textarea = document.getElementById('textInput');
    if (textarea) {
      textarea.addEventListener('focus', () => { polling = false; });
      textarea.addEventListener('blur',  () => { polling = true; setTimeout(poll, 1500); });
    }

    // Kick off polling 3 seconds after page load
    setTimeout(poll, 3000);
  });
})();
