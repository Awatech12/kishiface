// Handle splash screen and skeleton transition
    window.addEventListener("load", function () {
      // Hide splash screen faster (1 second)
      setTimeout(() => {
        const splash = document.getElementById("splash");
        splash.classList.add("hidden");
        
        // Hide skeleton after splash
        setTimeout(() => {
          const skeleton = document.getElementById("skeleton");
          const content = document.getElementById("content");
          
          skeleton.style.display = "none";
          content.classList.add("show");
          
          // Auto-focus on username input
          const usernameInput = document.querySelector('input[name="user_check"]');
          if (usernameInput) {
            usernameInput.focus();
          }
        }, 150);
      }, 1000);
    });
    
    // Form submission feedback
    document.addEventListener('DOMContentLoaded', function() {
      const form = document.querySelector('form');
      const inputs = document.querySelectorAll('.kf-input');
      const loginBtn = document.querySelector('.kf-login-btn');
      
      // Add input focus effects
      inputs.forEach(input => {
        input.addEventListener('focus', function() {
          this.style.background = '#f0f0f0';
        });
        
        input.addEventListener('blur', function() {
          this.style.background = '#f8f8f8';
        });
      });
      
      // Form submission
      form.addEventListener('submit', function(e) {
        // Basic validation before submit
        const username = document.querySelector('input[name="user_check"]').value.trim();
        const password = document.querySelector('input[name="password"]').value.trim();
        
        if (!username || !password) {
          e.preventDefault();
          
          // Add shake animation
          form.style.animation = 'shake 0.4s';
          setTimeout(() => {
            form.style.animation = '';
          }, 400);
          
          return false;
        }
        
        // Change button to loading state
        loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Logging in...';
        loginBtn.disabled = true;
        
        // Add CSS for shake animation
        const style = document.createElement('style');
        style.textContent = `
          @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-4px); }
            75% { transform: translateX(4px); }
          }
        `;
        document.head.appendChild(style);
      });
    });