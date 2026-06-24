// Lease term: show/hide custom input
(function() {
  const preset = document.getElementById('id_lease_term_preset');
  const wrap   = document.getElementById('custom-lease-wrap');
  const custom = document.getElementById('id_lease_term_months_custom');

  function toggle() {
    // The sentinel value '0' means "Other — enter below"
    if (preset && preset.value === '0') {
      wrap.style.display  = 'block';
      custom.required     = true;
    } else {
      wrap.style.display  = 'none';
      custom.required     = false;
      if (custom) custom.value = '';
    }
  }

  preset?.addEventListener('change', toggle);
  toggle(); // run on load to handle back-button / validation re-render
})();

// Live advance total calculator
(function() {
  const rentInput    = document.getElementById('id_monthly_rent');
  const monthsInput  = document.getElementById('id_advance_months');
  const totalDisplay = document.getElementById('advance_total');

  function updateTotal() {
    const rent   = parseFloat(rentInput?.value)   || 0;
    const months = parseInt(monthsInput?.value)   || 0;
    const total  = rent * months;
    if (totalDisplay) {
      totalDisplay.textContent = total.toLocaleString('en-GH', {
        minimumFractionDigits: 2, maximumFractionDigits: 2
      });
    }
  }

  rentInput?.addEventListener('input', updateTotal);
  monthsInput?.addEventListener('input', updateTotal);
  updateTotal(); // Run on load for pre-filled values
})();


(function() {
  const videoInput = document.querySelector('input[name="video_file"]');
  if (videoInput) {
    videoInput.addEventListener('change', function() {
      const file = this.files[0];
      if (!file) return;
      
      const MAX_SIZE = 150 * 1024 * 1024;  // 150MB
      if (file.size > MAX_SIZE) {
        const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
        alert(`Video file is ${sizeMB}MB. Maximum size is 150MB.`);
        this.value = '';  // Clear input
      }
    });
  }
})();