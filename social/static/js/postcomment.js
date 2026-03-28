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

  // Comment input functionality — grabbed inside DOMContentLoaded (see initInputUI)

  document.addEventListener('DOMContentLoaded', function () {
    /* ── DOM refs ── */
    const textInput        = document.getElementById('textInput');
    const sendBtn          = document.getElementById('sendBtn');
    const audio_file_input = document.getElementById('audio_file');
    const postForm         = document.getElementById('postForm');

    /* ── Send button / mic visibility ── */
    function updateSendButton() {
      const hasText  = textInput && textInput.value.trim().length > 0;
      const imgEl    = document.getElementById('image');
      const hasImage = imgEl && imgEl.files && imgEl.files.length > 0;
      const micBtn   = document.getElementById('kvibeCommentMicBtn');
      if (hasText || hasImage) {
        if (sendBtn) sendBtn.style.display = 'flex';
        if (micBtn)  micBtn.style.display  = 'none';
      } else {
        if (sendBtn) sendBtn.style.display = 'none';
        if (micBtn)  micBtn.style.display  = 'flex';
      }
    }

    /* ── Auto-resize textarea ── */
    function autoResizeTextarea() {
      if (!textInput) return;
      textInput.style.height = 'auto';
      textInput.style.height = Math.min(textInput.scrollHeight, 100) + 'px';
      const wrapper = textInput.closest('.kvibe-comment-input-wrapper');
      if (wrapper) wrapper.style.minHeight = (42 + Math.max(0, Math.min(textInput.scrollHeight, 100) - 24)) + 'px';
    }

    /* ── Reset after submit ── */
    function resetInputUI() {
      if (textInput) { textInput.value = ''; autoResizeTextarea(); }
      if (audio_file_input) audio_file_input.value = '';
      updateSendButton();
    }
    window.resetInputUI = resetInputUI;

    /* ── Wire up textarea ── */
    if (textInput) {
      textInput.addEventListener('input', function () { updateSendButton(); autoResizeTextarea(); });
      textInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (sendBtn && sendBtn.style.display !== 'none')
            postForm.dispatchEvent(new Event('submit', { bubbles: true }));
        }
      });
    }
    const imageInput = document.getElementById('image');
    if (imageInput) imageInput.addEventListener('change', updateSendButton);

    document.body.addEventListener('htmx:afterRequest', function (event) {
      if (event.target.id === 'postForm' && event.detail.successful) resetInputUI();
    });

    updateSendButton();
    autoResizeTextarea();

    /* ── Emoji picker init ── */
    if (typeof initKvibeCommentEmojiPicker === 'function') initKvibeCommentEmojiPicker();

    /* ── Waveform player init ── */
    if (typeof kvibeInitAudioPlayers === 'function') kvibeInitAudioPlayers();

    /* ── Post text collapse ── */
    document.querySelectorAll('.kvibe-post-text').forEach(function (textElement) {
      const textContent = textElement.textContent.trim();
      const lineCount   = (textContent.match(/\n/g) || []).length + 1;
      const charCount   = textContent.length;
      if (charCount > 150 || lineCount > 3) {
        textElement.classList.add('collapsed');
        if (!textElement.nextElementSibling || !textElement.nextElementSibling.classList.contains('kvibe-text-toggle')) {
          const toggleBtn = document.createElement('button');
          toggleBtn.className = 'kvibe-text-toggle';
          toggleBtn.innerHTML = '<span>more</span><i class="fas fa-chevron-down"></i>';
          toggleBtn.onclick = function () { kvibeToggleText(textElement.id.replace('kvibe-text-', '')); };
          textElement.parentNode.insertBefore(toggleBtn, textElement.nextSibling);
        }
      }
    });

    /* ── Desktop logout ── */
    const desktopLogoutIcon = document.getElementById('desktopLogoutIcon');
    if (desktopLogoutIcon) {
      desktopLogoutIcon.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation();
        const logoutModal = document.getElementById('kvibeLogoutModal');
        if (logoutModal) {
          logoutModal.classList.add('active');
          const cancelBtn  = document.getElementById('kvibeCancelLogout');
          const confirmBtn = document.getElementById('kvibeConfirmLogout');
          if (cancelBtn)  cancelBtn.onclick  = function () { logoutModal.classList.remove('active'); };
          if (confirmBtn) confirmBtn.onclick = function () { window.location.href = '/logout/'; };
          logoutModal.addEventListener('click', function (e) {
            if (e.target === logoutModal) logoutModal.classList.remove('active');
          });
        }
      });
    }

    /* ── Repost modal outside-click / ESC ── */
    const repostModal = document.getElementById('kvibe-repost-modal');
    if (repostModal) {
      repostModal.addEventListener('click', function (e) {
        if (e.target === this) kvibeCloseRepostModal();
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        kvibeCloseRepostModal();
        const logoutModal = document.getElementById('kvibeLogoutModal');
        if (logoutModal && logoutModal.classList.contains('active')) logoutModal.classList.remove('active');
      }
    });

    window.addEventListener('resize', function () {
      const modal = document.getElementById('kvibe-repost-modal');
      if (modal && modal.classList.contains('show')) {
        const mc = modal.querySelector('.kvibe-repost-modal-content');
        const vh = window.innerHeight;
        mc.style.maxHeight = mc.offsetHeight > vh * 0.9 ? (vh * 0.9) + 'px' : '';
      }
    });
  }); // end DOMContentLoaded


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


/* ═══════════════════════════════════════════════════════
   EMOJI PICKER  (message.html style)
   ═══════════════════════════════════════════════════════ */
const kvibeCommentEmojiCategories = [
  { icon:'😀', label:'Smileys', emojis:['😀','😃','😄','😁','😆','😅','🤣','😂','🙂','🙃','😉','😊','😇','🥰','😍','🤩','😘','😗','☺️','😚','😙','🥲','😋','😛','😜','🤪','😝','🤑','🤗','🤭','🤫','🤔','🤐','🤨','😐','😑','😶','😏','😒','🙄','😬','🤥','😌','😔','😪','🤤','😴','😷','🤒','🤕','🤢','🤮','🤧','🥵','🥶','🥴','😵','🤯','🤠','🥳','🥸','😎','🤓','🧐','😕','😟','🙁','☹️','😮','😯','😲','😳','🥺','😦','😧','😨','😰','😥','😢','😭','😱','😖','😣','😞','😓','😩','😫','🥱','😤','😡','😠','🤬','😈','👿','💀','☠️','💩','🤡','👹','👺','👻','👽','👾','🤖'] },
  { icon:'👋', label:'People',  emojis:['👋','🤚','🖐️','✋','🖖','👌','🤌','🤏','✌️','🤞','🤟','🤘','🤙','👈','👉','👆','🖕','👇','☝️','👍','👎','✊','👊','🤛','🤜','👏','🙌','👐','🤲','🤝','🙏','✍️','💅','🤳','💪','🦾','🦵','🦶','👂','🦻','👃','🧠','👀','👁️','👅','👄','💋','👶','🧒','👦','👧','🧑','👱','👨','🧔','👩','🧓','👴','👵','🙍','🙎','🙅','🙆','💁','🙋','🧏','🙇','🤦','🤷','👮','🕵️','💂','🥷','👷','🤴','👸','👳','👲','🧕','🤵','👰','🤰','🤱','👼','🎅','🤶','🦸','🦹','🧙','🧝','🧛','🧟','🧞','🧜','🧚','👫','👬','👭','💏','💑','👪'] },
  { icon:'🐶', label:'Animals', emojis:['🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼','🐨','🐯','🦁','🐮','🐷','🐸','🐵','🙈','🙉','🙊','🐒','🐔','🐧','🐦','🐤','🦆','🦅','🦉','🦇','🐺','🐗','🐴','🦄','🐝','🐛','🦋','🐌','🐞','🐜','🦟','🦗','🕷️','🦂','🐢','🐍','🦎','🐙','🦑','🦐','🦀','🐡','🐠','🐟','🐬','🐳','🦈','🐊','🐅','🐆','🦓','🦍','🦣','🐘','🦛','🦏','🐪','🐫','🦒','🦘','🐃','🐂','🐄','🐎','🐖','🐏','🐑','🦙','🐐','🦌','🐕','🐩','🦮','🐈','🐓','🦃','🦤','🦚','🦜','🦢','🕊️','🐇','🦝','🦨','🦡','🦦','🦥','🐁','🐀','🐿️','🦔'] },
  { icon:'🍕', label:'Food',    emojis:['🍎','🍐','🍊','🍋','🍌','🍉','🍇','🍓','🫐','🍒','🍑','🥭','🍍','🥥','🥝','🍅','🍆','🥑','🥦','🥬','🥒','🌶️','🧄','🧅','🥔','🍠','🥐','🥯','🍞','🥖','🥨','🧀','🥚','🍳','🧈','🥞','🧇','🥓','🥩','🍗','🍖','🌭','🍔','🍟','🍕','🥪','🥙','🌮','🌯','🥗','🥘','🍝','🍜','🍲','🍛','🍣','🍱','🥟','🍤','🍙','🍚','🍘','🍥','🥮','🍢','🧁','🍰','🎂','🍮','🍭','🍬','🍫','🍿','🍩','🍪','🌰','🥜','🍯','🧃','🥤','🧋','🍵','☕','🍺','🍻','🥂','🍷','🥃','🍸','🍹','🧉','🍾'] },
  { icon:'⚽', label:'Sports',  emojis:['⚽','🏀','🏈','⚾','🥎','🎾','🏐','🏉','🥏','🎱','🪀','🏓','🏸','🏒','🥍','🏏','🥅','⛳','🎣','🤿','🎽','🎿','🛷','🥌','🎯','🏹','🛹','🛼','🪂','🏋️','🤼','🤸','⛹️','🤺','🏇','⛷️','🏂','🏄','🚣','🧗','🚵','🚴','🏆','🥇','🥈','🥉','🏅','🎖️','🏵️','🎗️','🎫','🎟️','🎪','🤹','🎭','🩰','🎨','🎬','🎤','🎧','🎼','🎹','🥁','🪘','🎷','🎺','🎸','🪕','🎻','🎲','♟️','🎯','🎳','🎮','🎰','🧩'] },
  { icon:'🚀', label:'Travel',  emojis:['🚗','🚕','🚙','🚌','🚎','🏎️','🚓','🚑','🚒','🚐','🛻','🚚','🚛','🚜','🛵','🏍️','🚲','🛴','🚁','🛸','✈️','🚀','🛩️','🪂','⛵','🚤','🛥️','🛳️','🚢','🚂','🚃','🚄','🚅','🚆','🚇','🚈','🚉','🚊','🚝','🚞','🚋','🌍','🌎','🌏','🗺️','🧭','🏔️','⛰️','🌋','🗻','🏕️','🏖️','🏜️','🏝️','🏞️','🏟️','🏛️','🏗️','🏘️','🏠','🏡','🏢','🏣','🏤','🏥','🏦','🏨','🏩','🏪','🏫','🏬','🏭','🏯','🏰','💒','🗼','🗽','⛪','🕌','🛕','🕍','⛩️','🕋'] },
  { icon:'❤️', label:'Symbols', emojis:['❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','❤️‍🔥','❤️‍🩹','💔','❣️','💕','💞','💓','💗','💖','💘','💝','💟','☮️','✝️','☪️','🕉️','☸️','✡️','🔯','🕎','☯️','☦️','🛐','♻️','⚜️','🔱','📛','🔰','⭕','✅','☑️','✔️','❎','🔲','🔳','▪️','▫️','◾','◽','◼️','◻️','🟥','🟧','🟨','🟩','🟦','🟪','⬛','⬜','🟤','🔴','🟠','🟡','🟢','🔵','🟣','⚫','⚪','🔺','🔻','💠','🔷','🔹','🔶','🔸'] },
  { icon:'🎮', label:'Objects', emojis:['💌','📦','📫','📪','📬','📭','📮','📯','📜','📃','📄','📑','🧾','📊','📈','📉','📓','📔','📒','📕','📗','📘','📙','📚','📖','🔖','🏷️','💰','🪙','💵','💶','💷','💸','💳','💹','✉️','📧','📨','📩','📤','📥','📦','📫','📪','📬','📭','📮','🗳️','✏️','✒️','🖋️','🖊️','📝','🔍','🔎','🔏','🔐','🔒','🔓','🔑','🗝️','🔨','🪓','⛏️','⚒️','🛠️','⚔️','🔧','🔩','⚙️','🗜️','⚖️','🔗','⛓️','🪝','🧲','⚗️','🧪','🧫','🧬','🔬','🔭','📡','💡','🔦','🕯️','🪔','🧯','💊','💉','🩸','🩹','🩺','🩻','🪒','🚿','🛁','🧴','🧷','🧹','🧺','🧻','🧼','🫧','🪣','🧽','🪤','🧰'] }
];
let kvibeCommentCurrentCat = 0;
let kvibeCommentAllEmojis  = [];

function initKvibeCommentEmojiPicker() {
  kvibeCommentAllEmojis = kvibeCommentEmojiCategories.flatMap(function(c) { return c.emojis.map(function(e) { return { emoji: e, cat: c.label }; }); });
  const tabs = document.getElementById('kvibeCommentEmojiTabs');
  if (!tabs) return;
  tabs.innerHTML = '';
  kvibeCommentEmojiCategories.forEach(function(cat, i) {
    const t = document.createElement('div');
    t.className = 'kvibe-comment-emoji-tab' + (i === 0 ? ' active' : '');
    t.textContent = cat.icon;
    t.title = cat.label;
    t.onclick = function() { kvibeCommentSelectCat(i); };
    tabs.appendChild(t);
  });
  kvibeCommentRenderCat(0);
}

function kvibeCommentSelectCat(index) {
  kvibeCommentCurrentCat = index;
  const searchEl = document.getElementById('kvibeCommentEmojiSearch');
  if (searchEl) searchEl.value = '';
  document.querySelectorAll('.kvibe-comment-emoji-tab').forEach(function(t, i) { t.classList.toggle('active', i === index); });
  kvibeCommentRenderCat(index);
}

function kvibeCommentRenderCat(index) {
  const grid = document.getElementById('kvibeCommentEmojiGrid');
  if (!grid) return;
  grid.innerHTML = '';
  kvibeCommentEmojiCategories[index].emojis.forEach(function(emoji) {
    const el = document.createElement('div');
    el.className = 'kvibe-comment-emoji-item';
    el.textContent = emoji;
    el.onclick = function() { kvibeInsertCommentEmoji(emoji); };
    grid.appendChild(el);
  });
}

function kvibeCommentSearchEmoji(query) {
  const grid = document.getElementById('kvibeCommentEmojiGrid');
  if (!grid) return;
  grid.innerHTML = '';
  const q = query.trim().toLowerCase();
  const results = q
    ? kvibeCommentAllEmojis.filter(function(e) { return e.cat.toLowerCase().includes(q) || e.emoji.includes(q); }).map(function(e) { return e.emoji; })
    : kvibeCommentEmojiCategories[kvibeCommentCurrentCat].emojis;
  document.querySelectorAll('.kvibe-comment-emoji-tab').forEach(function(t) { t.classList.toggle('active', !q); });
  results.forEach(function(emoji) {
    const el = document.createElement('div');
    el.className = 'kvibe-comment-emoji-item';
    el.textContent = emoji;
    el.onclick = function() { kvibeInsertCommentEmoji(emoji); };
    grid.appendChild(el);
  });
}

function toggleKvibeCommentEmojiPicker(event) {
  event.stopPropagation();
  const picker   = document.getElementById('kvibeCommentEmojiPicker');
  const btn      = document.getElementById('kvibeCommentEmojiBtn');
  const inputArea = document.getElementById('myForm');
  if (!picker || !btn) return;

  const isOpen = picker.classList.contains('open');

  if (isOpen) {
    picker.classList.remove('open');
    btn.classList.remove('active');
    return;
  }

  // Position picker just above the input bar using fixed coords
  const ref = (inputArea || btn).getBoundingClientRect();
  picker.style.bottom = (window.innerHeight - ref.top) + 'px';

  picker.classList.add('open');
  btn.classList.add('active');

  const searchEl = document.getElementById('kvibeCommentEmojiSearch');
  if (searchEl) searchEl.value = '';
  kvibeCommentRenderCat(kvibeCommentCurrentCat);
}

function kvibeInsertCommentEmoji(emoji) {
  const ta = document.getElementById('textInput');
  if (!ta) return;
  const start = ta.selectionStart, end = ta.selectionEnd;
  ta.value = ta.value.slice(0, start) + emoji + ta.value.slice(end);
  ta.selectionStart = ta.selectionEnd = start + emoji.length;
  ta.focus();
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

document.addEventListener('click', function(e) {
  const picker = document.getElementById('kvibeCommentEmojiPicker');
  const btn    = document.getElementById('kvibeCommentEmojiBtn');
  if (!picker || !btn) return;
  if (!picker.contains(e.target) && !btn.contains(e.target)) {
    picker.classList.remove('open');
    btn.classList.remove('active');
  }
});

// Reposition picker on resize/scroll so it stays above the input bar
function _kvcmtRepositionPicker() {
  const picker    = document.getElementById('kvibeCommentEmojiPicker');
  const inputArea = document.getElementById('myForm');
  if (!picker || !picker.classList.contains('open') || !inputArea) return;
  const ref = inputArea.getBoundingClientRect();
  picker.style.bottom = (window.innerHeight - ref.top) + 'px';
}
window.addEventListener('resize', _kvcmtRepositionPicker);
window.addEventListener('scroll', _kvcmtRepositionPicker, true);


/* ═══════════════════════════════════════════════════════
   AUDIO RECORDING  (message.html hold-to-record style)
   ═══════════════════════════════════════════════════════ */
var _kvCmtStream    = null, _kvCmtRecorder  = null, _kvCmtChunks   = [];
var _kvCmtRecording = false, _kvCmtTimer    = null, _kvCmtStartTime = 0;
var _kvCmtAudioCtx  = null, _kvCmtAnalyser  = null;

async function kvibeCommentStartRecording(event) {
  event.preventDefault();
  const micBtn = document.getElementById('kvibeCommentMicBtn');
  if (micBtn) micBtn.classList.add('kvibe-comment-mic-pulse');
  try {
    _kvCmtStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 44100 } });
    const opts = { mimeType: 'audio/webm' };
    if (!MediaRecorder.isTypeSupported('audio/webm')) opts.mimeType = 'audio/mp4';
    if (!MediaRecorder.isTypeSupported(opts.mimeType)) delete opts.mimeType;
    _kvCmtRecorder = new MediaRecorder(_kvCmtStream, opts);
    _kvCmtChunks   = [];
    _kvCmtRecorder.ondataavailable = function(e) { if (e.data.size > 0) _kvCmtChunks.push(e.data); };
    _kvCmtRecorder.onstop = async function() {
      if (_kvCmtChunks.length === 0) { _kvCmtCleanup(); return; }
      const mimeType = _kvCmtRecorder.mimeType || 'audio/webm';
      const blob = new Blob(_kvCmtChunks, { type: mimeType });
      const ext  = mimeType.includes('webm') ? 'webm' : 'mp4';
      const file = new File([blob], 'voice_comment_' + Date.now() + '.' + ext, { type: mimeType });
      const dt   = new DataTransfer();
      dt.items.add(file);
      const audioInput = document.getElementById('audio_file');
      if (audioInput) audioInput.files = dt.files;
      const form = document.getElementById('postForm');
      if (form) {
        if (typeof htmx !== 'undefined') htmx.trigger(form, 'submit');
        else form.submit();
      }
      _kvCmtCleanup();
    };
    _kvCmtRecorder.onerror = function() { _kvCmtCleanup(); };
    _kvCmtRecorder.start(100);
    _kvCmtStartTime = Date.now();
    _kvCmtRecording = true;
    const overlay = document.getElementById('kvibeCommentRecordingOverlay');
    if (overlay) overlay.classList.add('active');
    _kvCmtStartTimer();
    _kvCmtStartVisualizer(_kvCmtStream);
  } catch (err) {
    console.error('Mic error:', err);
    alert('Unable to access microphone. Please check permissions.');
    if (micBtn) micBtn.classList.remove('kvibe-comment-mic-pulse');
  }
}

function kvibeCommentStopRecording() {
  if (_kvCmtRecorder && _kvCmtRecording) {
    try { _kvCmtRecorder.requestData(); } catch(e) {}
    _kvCmtRecorder.stop();
  }
}

function kvibeCommentTouchStart(e) { e.preventDefault(); kvibeCommentStartRecording(e); }
function kvibeCommentTouchEnd(e)   { e.preventDefault(); kvibeCommentStopRecording(); }

function _kvCmtCleanup() {
  if (_kvCmtStream) { _kvCmtStream.getTracks().forEach(function(t) { t.stop(); t.enabled = false; }); _kvCmtStream = null; }
  if (_kvCmtTimer)  { clearInterval(_kvCmtTimer); _kvCmtTimer = null; }
  if (_kvCmtAudioCtx && _kvCmtAudioCtx.state !== 'closed') { _kvCmtAudioCtx.close(); _kvCmtAudioCtx = null; }
  _kvCmtChunks = []; _kvCmtRecording = false; _kvCmtRecorder = null;
  const overlay = document.getElementById('kvibeCommentRecordingOverlay');
  if (overlay) overlay.classList.remove('active');
  const timerEl = document.getElementById('kvibeCommentRecordingTimer');
  if (timerEl) timerEl.textContent = '0:00';
  const micBtn = document.getElementById('kvibeCommentMicBtn');
  if (micBtn) micBtn.classList.remove('kvibe-comment-mic-pulse');
}

function _kvCmtStartTimer() {
  _kvCmtTimer = setInterval(function() {
    var elapsed = Math.floor((Date.now() - _kvCmtStartTime) / 1000);
    var m = Math.floor(elapsed / 60), s = elapsed % 60;
    var el = document.getElementById('kvibeCommentRecordingTimer');
    if (el) el.textContent = m + ':' + (s < 10 ? '0' : '') + s;
  }, 1000);
}

function _kvCmtStartVisualizer(stream) {
  try {
    _kvCmtAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    _kvCmtAnalyser = _kvCmtAudioCtx.createAnalyser();
    var src = _kvCmtAudioCtx.createMediaStreamSource(stream);
    src.connect(_kvCmtAnalyser);
    _kvCmtAnalyser.fftSize = 256;
    var bufLen = _kvCmtAnalyser.frequencyBinCount;
    var dataArr = new Uint8Array(bufLen);
    var canvas  = document.getElementById('kvibeCommentRecordingWave');
    if (!canvas) return;
    var ctx2d = canvas.getContext('2d');
    function draw() {
      if (!_kvCmtRecording || !_kvCmtAnalyser) return;
      requestAnimationFrame(draw);
      _kvCmtAnalyser.getByteFrequencyData(dataArr);
      ctx2d.clearRect(0, 0, canvas.width, canvas.height);
      var barW = (canvas.width / bufLen) * 2.5, x = 0;
      for (var i = 0; i < bufLen; i++) {
        var barH = dataArr[i] / 2;
        var grad = ctx2d.createLinearGradient(0, 0, 0, canvas.height);
        grad.addColorStop(0, '#0095f6'); grad.addColorStop(1, '#1877f2');
        ctx2d.fillStyle = grad;
        ctx2d.fillRect(x, canvas.height - barH, barW, barH);
        x += barW + 1;
      }
    }
    draw();
  } catch(e) { console.error('Visualizer error:', e); }
}


/* ═══════════════════════════════════════════════════════
   WAVEFORM AUDIO PLAYER  (message.html style)
   ═══════════════════════════════════════════════════════ */
var _kvCmtCurrentAudio = null;
var _kvCmtWaveRAF      = {};

function kvCmtGenerateWaveform(audioId) {
  var wc = document.getElementById('kvibe-wave-container-' + audioId);
  if (!wc) return;
  wc.innerHTML = '';
  var BAR_COUNT = 40;
  for (var i = 0; i < BAR_COUNT; i++) {
    var bar  = document.createElement('div');
    bar.className = 'kvibe-wave-bar';
    var dist = Math.abs(i - BAR_COUNT / 2) / (BAR_COUNT / 2);
    var h    = Math.max(3, (1 - dist * 0.6) * 18 + (Math.random() * 10 - 5));
    bar.style.height = h + 'px';
    wc.appendChild(bar);
  }
}

function kvCmtUpdateWaveform(audioId, isPlaying) {
  if (_kvCmtWaveRAF[audioId]) { cancelAnimationFrame(_kvCmtWaveRAF[audioId]); delete _kvCmtWaveRAF[audioId]; }
  var wc = document.getElementById('kvibe-wave-container-' + audioId);
  if (!wc) return;
  var bars = wc.querySelectorAll('.kvibe-wave-bar');
  if (!isPlaying) { bars.forEach(function(b) { b.classList.remove('played', 'current'); }); return; }
  var audio = document.getElementById('audio-' + audioId);
  if (!audio) return;
  function tick() {
    if (audio.paused || audio.ended) return;
    var progress = audio.duration ? audio.currentTime / audio.duration : 0;
    var playedCount = Math.floor(progress * bars.length);
    bars.forEach(function(b, i) {
      if      (i < playedCount)  { b.classList.add('played'); b.classList.remove('current'); }
      else if (i === playedCount){ b.classList.remove('played'); b.classList.add('current'); }
      else                       { b.classList.remove('played', 'current'); }
    });
    _kvCmtWaveRAF[audioId] = requestAnimationFrame(tick);
  }
  _kvCmtWaveRAF[audioId] = requestAnimationFrame(tick);
}

function kvCmtToggleAudio(button, audioId) {
  var audio = document.getElementById('audio-' + audioId);
  if (!audio) return;
  var wc = document.getElementById('kvibe-wave-container-' + audioId);
  if (wc && !wc.querySelector('.kvibe-wave-bar')) kvCmtGenerateWaveform(audioId);
  var durEl = document.getElementById('kvibe-cmt-duration-' + audioId);
  var fmt = function(s) { return isNaN(s) ? '0:00' : Math.floor(s/60) + ':' + (Math.floor(s%60) < 10 ? '0' : '') + Math.floor(s%60); };
  if (audio.paused) {
    if (_kvCmtCurrentAudio && _kvCmtCurrentAudio !== audio) {
      _kvCmtCurrentAudio.pause();
      var otherId  = _kvCmtCurrentAudio.id.replace('audio-', '');
      kvCmtUpdateWaveform(otherId, false);
      var otherBtn = document.querySelector('[onclick*="kvCmtToggleAudio"][onclick*="\'' + otherId + '\'"]');
      if (otherBtn) otherBtn.innerHTML = '<i class="fas fa-play"></i>';
      var otherDur = document.getElementById('kvibe-cmt-duration-' + otherId);
      if (otherDur && _kvCmtCurrentAudio.duration) otherDur.textContent = fmt(_kvCmtCurrentAudio.duration);
    }
    audio.play().then(function() {
      _kvCmtCurrentAudio = audio;
      button.innerHTML   = '<i class="fas fa-pause"></i>';
      kvCmtUpdateWaveform(audioId, true);
      var setDur = function() { if (durEl && audio.duration) durEl.textContent = fmt(audio.duration); };
      if (audio.duration) setDur(); else audio.addEventListener('loadedmetadata', setDur, { once: true });
      function timeTick() {
        if (audio.paused || audio.ended) return;
        if (durEl) durEl.textContent = fmt(audio.currentTime);
        requestAnimationFrame(timeTick);
      }
      requestAnimationFrame(timeTick);
      function onStop() {
        button.innerHTML = '<i class="fas fa-play"></i>';
        kvCmtUpdateWaveform(audioId, false);
        if (durEl && audio.duration) durEl.textContent = fmt(audio.duration);
        if (_kvCmtCurrentAudio === audio) _kvCmtCurrentAudio = null;
      }
      audio.addEventListener('pause', onStop, { once: true });
      audio.addEventListener('ended', onStop, { once: true });
    }).catch(function(e) { console.error('Audio play error:', e); });
  } else {
    audio.pause();
    button.innerHTML = '<i class="fas fa-play"></i>';
    kvCmtUpdateWaveform(audioId, false);
    if (durEl && audio.duration) durEl.textContent = fmt(audio.duration);
    if (_kvCmtCurrentAudio === audio) _kvCmtCurrentAudio = null;
  }
}

function kvCmtWaveformClick(e, audioId) {
  e.stopPropagation();
  var audio = document.getElementById('audio-' + audioId);
  var wc    = document.getElementById('kvibe-wave-container-' + audioId);
  if (!audio || !wc || !audio.duration) return;
  var rect  = wc.getBoundingClientRect();
  audio.currentTime = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)) * audio.duration;
}

function kvibeInitAudioPlayers(root) {
  (root || document).querySelectorAll('.kvibe-audio-container[data-audio-id]').forEach(function(container) {
    if (container._kvWaveInited) return;
    container._kvWaveInited = true;
    var audioId = container.dataset.audioId;
    kvCmtGenerateWaveform(audioId);
    var audio = document.getElementById('audio-' + audioId);
    if (audio) {
      audio.addEventListener('loadedmetadata', function() {
        var el = document.getElementById('kvibe-cmt-duration-' + audioId);
        if (el && !isNaN(audio.duration)) {
          var m = Math.floor(audio.duration / 60), s = Math.floor(audio.duration % 60);
          el.textContent = m + ':' + (s < 10 ? '0' : '') + s;
        }
      });
    }
  });
}

if (typeof htmx !== 'undefined') {
  htmx.onLoad(function(el) { kvibeInitAudioPlayers(el); });
}
