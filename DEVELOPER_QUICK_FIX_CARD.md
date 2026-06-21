# QUICK FIX REFERENCE CARD
**Developer Copy-Paste Guide** — All 7 Issues in One Place

---

## 🔴 CRITICAL - Fix NOW (15 min)

### F1: Empty Photos Saved
**File:** `apps/listings/services.py` line 49  
**Change:** Add 1 line filter
```python
# BEFORE
if photo_formset:
    photos = photo_formset.save(commit=False)
    has_primary = any(p.is_primary for p in photos)

# AFTER  
if photo_formset:
    photos = photo_formset.save(commit=False)
    photos = [p for p in photos if p.image]  # ← ADD THIS
    has_primary = any(p.is_primary for p in photos)
```

---

### F5: GPS Typo
**File:** `apps/listings/models.py` line 280  
**Change:** Fix one word
```python
# BEFORE
if self.latitude and self.longtitude:  # TYPO

# AFTER
if self.latitude and self.longitude:   # FIXED
```

---

### F7: Video Silently Fails
**File:** `apps/listings/services.py` line 37  
**Change:** Add 1 line (re-raise exception)
```python
# BEFORE
except Exception:
    logger.exception("Failed to upload property video")
    # ← NO RETURN/RAISE

# AFTER
except Exception:
    logger.exception("Failed to upload property video")
    raise  # ← ADD THIS
```

---

## 🟠 HIGH - Fix This Week (40 min)

### F4: Video Size Not Validated
**File:** `apps/listings/forms.py` — Replace video_file field
```python
# Add at top of file
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError as DjangoValidationError

MAX_VIDEO_SIZE = 150 * 1024 * 1024

def validate_video_size(file):
    if file.size > MAX_VIDEO_SIZE:
        mb = file.size / (1024 * 1024)
        raise DjangoValidationError(f"Video is {mb:.1f}MB. Max: 150MB.")

# REPLACE THIS:
video_file = forms.FileField(
    required=False,
    help_text="Optional walkthrough video. Max 150MB. MP4, MOV, or WebM.",
    widget=forms.FileInput(attrs={
        'accept': 'video/mp4,video/quicktime,video/webm,video/avi',
    })
)

# WITH THIS:
video_file = forms.FileField(
    required=False,
    validators=[
        FileExtensionValidator(['mp4', 'mov', 'webm', 'avi']),
        validate_video_size,
    ],
    help_text="Optional. Max 150MB. MP4, MOV, WebM, AVI.",
    widget=forms.FileInput(attrs={
        'accept': 'video/mp4,video/quicktime,video/webm,video/avi',
    })
)
```

---

### F3: Lease Term Not Bounded
**File:** `apps/listings/models.py` line 172  
**Change:** Add max validator
```python
# BEFORE
lease_term_months = models.PositiveSmallIntegerField(
    default=12,
    validators=[MinValueValidator(0)],
    ...
)

# AFTER
lease_term_months = models.PositiveSmallIntegerField(
    default=12,
    validators=[
        MinValueValidator(1),
        MaxValueValidator(240),  # ← ADD THIS
    ],
    ...
)
```

---

### F2: GPS Error Not Field-Specific
**File:** `apps/listings/forms.py` line 95-100  
**Change:** Update clean() method
```python
# BEFORE
if (latitude is None) != (longitude is None):
    raise forms.ValidationError(
        "Please provide both latitude and longitude, or neither."
    )

# AFTER
if (latitude is None) != (longitude is None):
    if latitude is None and longitude is not None:
        self.add_error('latitude', 'Latitude required when longitude provided.')
        self.add_error('longitude', 'Provide both or neither.')
    else:
        self.add_error('longitude', 'Longitude required when latitude provided.')
        self.add_error('latitude', 'Provide both or neither.')
```

---

## 🟡 MEDIUM - Fix Next Sprint (15 min)

### F6: Formset Errors Hidden
**File:** `templates/listings/create_property.html` line 176-209  
**Change:** Update photo form loop in template
```django
{# ADD THIS after the photo form div #}
{% if photo_form.image.errors %}
  <p style="color:#DC2626; font-size:0.8rem;">
    {{ photo_form.image.errors.0 }}
  </p>
{% endif %}

{% if photo_form.non_field_errors %}
  <div style="background:#FEF2F2; border-left:3px solid #DC2626; padding:8px;">
    {% for error in photo_form.non_field_errors %}
      <p style="color:#991B1B;">{{ error }}</p>
    {% endfor %}
  </div>
{% endif %}
```

---

## TESTING CHECKLIST

```bash
# F1: Empty photos
# Expected: 0 photos. Actual: should be 0 after fix
curl -X POST /listings/create/ \
  -d "title=Test&property_type=apartment&..." \
  -H "Authorization: Bearer token" 
# Check: Property.objects.last().photos.count() == 0

# F5: GPS typo
# Expected: reject coordinates (85, 0) outside Ghana
python manage.py shell
>>> from apps.listings.models import Property
>>> p = Property(latitude=85.0, longitude=0.0, ...)
>>> p.full_clean()  # Should raise ValidationError, not AttributeError

# F7: Video failure
# Expected: error shown to user, property NOT created
# Mock upload_property_video to raise Exception
# Re-run form submission, verify transaction rolled back

# F4: Video size
# Expected: reject 200MB file
# Form should show: "Video is 200.0MB. Max: 150MB."

# F3: Lease term bounds
# Expected: reject lease_term_months > 240
>>> p = Property(lease_term_months=500, ...)
>>> p.full_clean()  # Should raise ValidationError

# F2: GPS error display
# Expected: errors appear on lat/lng fields, not top
# Fill latitude, leave longitude empty
# Check: form.errors['latitude'] and form.errors['longitude'] not empty

# F6: Formset errors
# Expected: photo validation errors display clearly
# Try upload 500 items to formset
# Check: error messages visible, not dict format
```

---

## QUICK VALIDATION

Run this after each fix:

```bash
# Test suite
python manage.py test apps.listings

# Linting
flake8 apps/listings/forms.py apps/listings/models.py apps/listings/services.py

# Form validation directly
python manage.py shell
from apps.listings.forms import PropertyForm
f = PropertyForm(data={...})
print(f.is_valid())  # Should be True/False as expected
```

---

## FILES TO MODIFY

| Priority | File | Lines | Change |
|----------|------|-------|--------|
| CRIT | services.py | 49 | Add filter |
| CRIT | models.py | 280 | Fix typo |
| CRIT | services.py | 37 | Add raise |
| HIGH | forms.py | 61-68 | Add validators |
| HIGH | forms.py | 172 | Add MaxValidator |
| HIGH | forms.py | 95-100 | Update clean() |
| MED | models.py | 172 | Add MaxValidator (duplicate?) |
| MED | template | 176-209 | Add error display |

---

## DEPLOYMENT ORDER

1. Fix F1 + F5 (model + service, no dependencies)
2. Test thoroughly
3. Deploy to staging
4. Test in staging with real data
5. Fix F2, F3, F4 (high priority, form changes)
6. Deploy to production
7. Schedule F6 for next sprint

---

**Total Dev Time:** ~1 hour  
**Total QA Time:** ~45 min  
**Risk Level:** LOW (mostly form/validation changes)  
**Rollback Plan:** Revert commits if issues arise

Generated: 2026-06-20 | QA Lead: Senior QA
