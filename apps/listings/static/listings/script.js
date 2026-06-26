

// LEASE TERM: show/hide custom input 
(function () {
  const preset = document.getElementById('id_lease_term_preset');
  const wrap   = document.getElementById('custom-lease-wrap');
  const custom = document.getElementById('id_lease_term_months_custom');

  function toggle() {
    // Sentinel value '0' means "Other — enter below"
    if (preset && preset.value === '0') {
      wrap.style.display = 'block';
      if (custom) custom.required = true;
    } else {
      wrap.style.display = 'none';
      if (custom) {
        custom.required = false;
        custom.value    = '';
      }
    }
  }

  if (preset) {
    preset.addEventListener('change', toggle);
    toggle(); // Run immediately to handle validation re-renders (back-button, failed submit)
  }
})();


// ADVANCE TOTAL: live calculator 
(function () {
  const rentInput    = document.getElementById('id_monthly_rent');
  const monthsInput  = document.getElementById('id_advance_months');
  const totalDisplay = document.getElementById('advance_total');

  function updateTotal() {
    const rent   = parseFloat(rentInput  ? rentInput.value   : 0) || 0;
    const months = parseInt( monthsInput ? monthsInput.value : 0) || 0;
    const total  = rent * months;

    if (totalDisplay) {
      totalDisplay.textContent = total.toLocaleString('en-GH', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
  }

  if (rentInput)   rentInput.addEventListener('input', updateTotal);
  if (monthsInput) monthsInput.addEventListener('input', updateTotal);
  updateTotal(); // Populate on load for pre-filled / re-rendered forms
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

//DYNAMIC PHOTO FORMSET 
(function () {
  const MAX_PHOTOS  = 10;
  const PREFIX      = 'photos'; // must match the prefix in views.py / forms.py

  // The management form field Django uses to count how many rows to expect on POST.
  // Incrementing this is mandatory when adding a row — Django silently ignores
  // any row whose index is >= TOTAL_FORMS.
  const totalFormsInput = document.querySelector('input[name="' + PREFIX + '-TOTAL_FORMS"]');

  const photoRows    = document.getElementById('photo-rows');
  const emptyTpl     = document.getElementById('empty-photo-template');
  const addBtn       = document.getElementById('add-photo-btn');
  const limitMsg     = document.getElementById('photo-limit-msg');
  const countDisplay = document.getElementById('photo-count-display');

  if (!totalFormsInput || !photoRows || !emptyTpl) {
    // Not on the create property page — bail silently
    return;
  }

  // ── How many rows are visible (not soft-deleted) ──────────────
  function visibleCount() {
    return photoRows.querySelectorAll('.photo-row:not([data-deleted="true"])').length;
  }

  // ── Update counter badge and button disabled state ────────────
  function updateUI() {
    var count = visibleCount();
    if (countDisplay) {
      countDisplay.textContent = count > 0 ? '(' + count + ' / ' + MAX_PHOTOS + ')' : '';
    }
    if (addBtn) {
      addBtn.disabled = count >= MAX_PHOTOS;
    }
    if (limitMsg) {
      limitMsg.style.display = count >= MAX_PHOTOS ? 'block' : 'none';
    }
  }

  // ── Add a new blank photo row ─────────────────────────────────
  function addPhotoRow() {
    if (visibleCount() >= MAX_PHOTOS) return;

    // TOTAL_FORMS tells us the next available index.
    // e.g. if 3 rows exist (indices 0, 1, 2), TOTAL_FORMS=3 → new row index is 3.
    var currentTotal = parseInt(totalFormsInput.value, 10);
    var newIndex     = currentTotal;

    // Clone the hidden template and replace every __prefix__ with the real index.
    // We do this on the innerHTML string — faster than walking DOM nodes,
    // and handles both name= and id= attributes in one pass.
    var newHTML = emptyTpl.innerHTML.split('__prefix__').join(String(newIndex));

    var wrapper    = document.createElement('div');
    wrapper.innerHTML = newHTML;
    var newRow     = wrapper.firstElementChild;
    photoRows.appendChild(newRow);

    // Wire the remove button on the new row
    wireRemoveButton(newRow);

    // Tell Django there is one more form
    totalFormsInput.value = currentTotal + 1;

    updateUI();

    // Focus the file input on the new row for a smooth UX
    var fileInput = newRow.querySelector('input[type="file"]');
    if (fileInput) fileInput.focus();
  }

  // ── Remove a photo row ────────────────────────────────────────
  //
  // Two cases require different handling:
  //
  // NEW row (no DB record):
  //   Remove from DOM entirely. Re-index remaining new rows so indices
  //   stay contiguous. Decrement TOTAL_FORMS.
  //
  // EXISTING row (has a DB record, id input has a value):
  //   Can't remove from DOM — Django needs to see the row on POST
  //   to know to delete it. Instead: set the DELETE checkbox to checked,
  //   hide the row visually, mark with data-deleted="true" so our
  //   visibleCount() skips it.
  //
  function removePhotoRow(row) {
    var idInput     = row.querySelector('input[type="hidden"][name$="-id"]');
    var deleteInput = row.querySelector('input[type="hidden"][name$="-DELETE"]');
    var hasDbRecord = idInput && idInput.value && idInput.value !== '';

    if (hasDbRecord) {
      // Existing DB record — soft delete
      if (deleteInput) deleteInput.checked = true;
      row.style.display = 'none';
      row.setAttribute('data-deleted', 'true');
    } else {
      // Brand new row — hard remove from DOM and re-index
      row.remove();
      reindexNewRows();
      totalFormsInput.value = parseInt(totalFormsInput.value, 10) - 1;
    }

    updateUI();
  }

  // ── Re-index new (unsaved) rows after a removal ───────────────
  //
  // Problem: if rows are [0, 1, 2] and we remove row 1, the POST data
  // has photos-0-* and photos-2-* — a gap. Django's formset parser
  // expects contiguous indices and will either error or ignore the gap.
  //
  // Solution: walk remaining rows. Existing DB rows keep their original
  // index (it's tied to their DB record). New rows get renumbered to
  // fill gaps.
  //
  // We track the next index to assign as we walk the list.
  //
  function reindexNewRows() {
    var allRows  = photoRows.querySelectorAll('.photo-row');
    var nextIndex = 0;

    allRows.forEach(function (row) {
      var idInput = row.querySelector('input[type="hidden"][name$="-id"]');

      if (idInput && idInput.value && idInput.value !== '') {
        // Existing DB row — read its current index and advance past it
        var match = idInput.name.match(/photos-(\d+)-id/);
        if (match) nextIndex = parseInt(match[1], 10) + 1;
      } else {
        // New row — rename all its fields to nextIndex
        row.querySelectorAll('input, select, textarea').forEach(function (el) {
          if (el.name) el.name = el.name.replace(/photos-\d+-/, PREFIX + '-' + nextIndex + '-');
          if (el.id)   el.id   = el.id.replace(/photos-\d+-/,   PREFIX + '-' + nextIndex + '-');
        });
        // Also update any labels pointing to these ids
        row.querySelectorAll('label[for]').forEach(function (label) {
          label.htmlFor = label.htmlFor.replace(/photos-\d+-/, PREFIX + '-' + nextIndex + '-');
        });
        nextIndex++;
      }
    });
  }

  // ── Wire the remove button on a given row ─────────────────────
  function wireRemoveButton(row) {
    var btn = row.querySelector('.remove-photo-btn');
    if (btn) {
      btn.addEventListener('click', function () {
        removePhotoRow(row);
      });
    }
  }

  // ── Wire existing rows (rendered server-side by Django) ───────
  photoRows.querySelectorAll('.photo-row').forEach(wireRemoveButton);

  // ── Wire the "Add photo" button ───────────────────────────────
  addBtn.addEventListener('click', addPhotoRow);

  // ── Set initial UI state ──────────────────────────────────────
  updateUI();

})();