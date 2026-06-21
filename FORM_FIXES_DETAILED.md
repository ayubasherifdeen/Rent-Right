# Form Submission Issues - Detailed Fixes & Code Changes

**QA Lead Analysis:** Senior QA, QA Lead, Senior Software Engineer  
**Date:** 2026-06-20

---

## CRITICAL ISSUES - MUST FIX BEFORE DEPLOYMENT

### FIX #1: 🔴 CRITICAL — Filter Out Empty Photos Before Saving

**Issue:** F1 - Formset creates empty photo records  
**Impact:** Database orphans, broken image thumbnails  
**Affected Files:** [apps/listings/services.py](apps/listings/services.py#L47-55)

**Current Code:**
```python
def create_listing(landlord, form_data, photo_formset=None):
    with transaction.atomic():
        # ... property setup ...
        property_obj.save()
        property_obj.amenities.set(amenities)

        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception:
                logger.exception("Failed to upload property video")

        # PROBLEM SECTION ↓
        if photo_formset:
            photos = photo_formset.save(commit=False)

            # Ensure at least the first photo is marked primary
            has_primary = any(p.is_primary for p in photos)
            for i, photo in enumerate(photos):
                photo.property = property_obj
                if i == 0 and not has_primary:
                    photo.is_primary = True
                photo.save()  # ← SAVES EMPTY PHOTOS!

            # Handle deletions
            for photo in photo_formset.deleted_objects:
                photo.delete()
```

**Fixed Code:**
```python
def create_listing(landlord, form_data, photo_formset=None):
    with transaction.atomic():
        # ... property setup ...
        property_obj.save()
        property_obj.amenities.set(amenities)

        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception:
                logger.exception("Failed to upload property video")

        # FIXED SECTION ↓
        if photo_formset:
            photos = photo_formset.save(commit=False)

            # FILTER OUT EMPTY FORMS
            photos = [p for p in photos if p.image]

            # Ensure at least the first photo is marked primary
            has_primary = any(p.is_primary for p in photos)
            for i, photo in enumerate(photos):
                photo.property = property_obj
                if i == 0 and not has_primary:
                    photo.is_primary = True
                photo.save()

            # Handle deletions
            for photo in photo_formset.deleted_objects:
                photo.delete()
```

**Test Verification:**
```python
# Before fix
def test_empty_photo_formset_creates_orphans():
    form_data = {...minimal required fields...}
    photo_formset = PropertyPhotoFormSet(form_data, request.FILES)  # 3 empty forms
    property_obj = create_listing(user, form_data, photo_formset)
    assert property_obj.photos.count() == 3  # WRONG: Should be 0
    
# After fix
def test_empty_photo_formset_not_saved():
    form_data = {...minimal required fields...}
    photo_formset = PropertyPhotoFormSet(form_data, request.FILES)
    property_obj = create_listing(user, form_data, photo_formset)
    assert property_obj.photos.count() == 0  # CORRECT
```

---

### FIX #2: 🔴 CRITICAL — Fix Typo in Model Validation

**Issue:** F5 - Typo: `longtitude` instead of `longitude`  
**Impact:** Ghana bounds validation never runs, invalid coordinates accepted  
**Affected Files:** [apps/listings/models.py](apps/listings/models.py#L280)

**Current Code:**
```python
def clean(self):
    """
    Model-level validation — the second layer of Act 220 enforcement.
    """
    errors = {}

    if self.advance_months and self.advance_months > ACT_220_MAX_ADVANCE_MONTHS:
        errors['advance_months'] = (...)

    if self.latitude and self.longtitude:  # ← TYPO!
        # Ghana bounding box — rough sanity check on coordinates
        if not (-3.5 <= float(self.latitude) <= 11.5):
            errors['latitude'] = "Latitude must be within Ghana (roughly -3.5° to 11.5°)."
        if not (-3.5 <= float(self.longitude) <= 1.5):
            errors['longitude'] = "Longitude must be within Ghana (roughly -3.5° to 1.5°)."

    if self.advance_months and self.lease_term_months:
        if self.advance_months > self.lease_term_months:
            errors['advance_months'] = (...)
    
    if errors:
        raise ValidationError(errors)
```

**Fixed Code:**
```python
def clean(self):
    """
    Model-level validation — the second layer of Act 220 enforcement.
    """
    errors = {}

    if self.advance_months and self.advance_months > ACT_220_MAX_ADVANCE_MONTHS:
        errors['advance_months'] = (...)

    if self.latitude and self.longitude:  # ← FIXED: was longtitude
        # Ghana bounding box — rough sanity check on coordinates
        if not (-3.5 <= float(self.latitude) <= 11.5):
            errors['latitude'] = "Latitude must be within Ghana (roughly -3.5° to 11.5°)."
        if not (-3.5 <= float(self.longitude) <= 1.5):
            errors['longitude'] = "Longitude must be within Ghana (roughly -3.5° to 1.5°)."

    if self.advance_months and self.lease_term_months:
        if self.advance_months > self.lease_term_months:
            errors['advance_months'] = (...)
    
    if errors:
        raise ValidationError(errors)
```

**Test Verification:**
```python
def test_invalid_gps_rejected():
    """Ghana bounds check should catch out-of-country coordinates"""
    prop = Property(
        landlord=user,
        title="Test",
        latitude=85.0,  # North Pole
        longitude=0.0,
        # ... other fields
    )
    with pytest.raises(ValidationError) as exc:
        prop.full_clean()
    assert 'latitude' in exc.value.error_dict
    assert "within Ghana" in str(exc.value)
```

---

### FIX #3: 🟡 MEDIUM — Handle Video Upload Failure Properly

**Issue:** F7 - Video exception caught without re-raise, property orphaned  
**Impact:** Property created without video, user confused  
**Affected Files:** [apps/listings/services.py](apps/listings/services.py#L32-39)

**Current Code:**
```python
def create_listing(landlord, form_data, photo_formset=None):
    with transaction.atomic():
        # ... property setup ...
        property_obj.save()

        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception:
                logger.exception("Failed to upload property video")
                # ← PROBLEM: Doesn't re-raise, property still saved!
```

**Fixed Code (Option A - Strict: Rollback on any failure):**
```python
def create_listing(landlord, form_data, photo_formset=None):
    with transaction.atomic():
        # ... property setup ...
        property_obj.save()

        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception as e:
                logger.exception("Failed to upload property video")
                raise  # ← RE-RAISE to trigger transaction rollback
```

**Fixed Code (Option B - Lenient: Clear what happened to user):**
```python
def create_listing(landlord, form_data, photo_formset=None):
    with transaction.atomic():
        # ... property setup ...
        property_obj.save()

        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception as e:
                # Video optional - log but don't fail creation
                logger.exception(f"Video upload failed for property {property_obj.pk}")
                # Continue: property created without video
                # View will need to handle this case
```

**View Changes (for Option B):**
```python
@login_required
def create_property(request):
    # ... existing code ...
    if request.method == 'POST':
        form = PropertyForm(request.POST)
        photo_formset = PropertyPhotoFormSet(request.POST, request.FILES)

        if form.is_valid() and photo_formset.is_valid():
            try:
                property_obj = create_listing(
                    landlord=request.user,
                    form_data=form.cleaned_data.copy(),
                    photo_formset=photo_formset,
                )
                messages.success(request, f"'{property_obj.title}' created as a draft.")
                
                # NEW: Check if video upload failed
                if request.POST.get('video_file') and not property_obj.video_url:
                    messages.warning(
                        request,
                        "Video upload failed. You can add it later."
                    )
                
                return redirect('listings:publish_prompt', pk=property_obj.pk)
            except Exception as e:
                messages.error(request, f"Error creating listing: {e}")
```

**Recommendation:** Use **Option A (strict)** because:
- Video is core feature for listings
- User expects video to be uploaded or clear error
- Option B leads to silent failures

---

## HIGH-PRIORITY ISSUES

### FIX #4: 🟠 HIGH — GPS Coordinate Field-Specific Errors

**Issue:** F2 - GPS validation error is generic, not field-specific  
**Impact:** Poor UX, users confused which field caused error  
**Affected Files:** [apps/listings/forms.py](apps/listings/forms.py#L95-100)

**Current Code:**
```python
def clean(self):
    cleaned_data = super().clean()
    
    # ... lease term handling ...
    
    # GPS must be both or neither
    latitude  = cleaned_data.get('latitude')
    longitude = cleaned_data.get('longitude')
    if (latitude is None) != (longitude is None):
        raise forms.ValidationError(
            "Please provide both latitude and longitude, or neither."
        )
    
    return cleaned_data
```

**Fixed Code:**
```python
def clean(self):
    cleaned_data = super().clean()
    
    # ... lease term handling ...
    
    # GPS must be both or neither
    latitude  = cleaned_data.get('latitude')
    longitude = cleaned_data.get('longitude')
    if (latitude is None) != (longitude is None):
        # Field-specific errors instead of non-field error
        if latitude is None and longitude is not None:
            self.add_error('latitude', 
                'Latitude is required when longitude is provided.')
            self.add_error('longitude', 
                'Both coordinates must be provided together.')
        else:
            self.add_error('longitude', 
                'Longitude is required when latitude is provided.')
            self.add_error('latitude', 
                'Both coordinates must be provided together.')
    
    return cleaned_data
```

**Template - Already correct:**
```django
{# _form_field.html already displays field-specific errors #}
{% if field.errors %}
  {% for error in field.errors %}
    <p style="color:#DC2626; font-size:0.8rem; margin:4px 0 0;">
      {{ error }}
    </p>
  {% endfor %}
{% endif %}
```

**Test Verification:**
```python
def test_gps_latitude_only_shows_field_error():
    form = PropertyForm({
        'title': 'Test',
        'latitude': 5.603717,
        'longitude': '',  # Empty
        # ... other required fields ...
    })
    assert not form.is_valid()
    assert 'latitude' in form.errors
    assert 'longitude' in form.errors
    assert "both coordinates" in form.errors['latitude'][0].lower()
```

---

### FIX #5: 🟠 HIGH — Add Video File Size Validation

**Issue:** F4 - No validation for video file size (says max 150MB but doesn't enforce)  
**Impact:** Can upload 1GB files, server crashes/timeout  
**Affected Files:** [apps/listings/forms.py](apps/listings/forms.py#L61-68)

**Current Code:**
```python
video_file = forms.FileField(
    required=False,
    help_text="Optional walkthrough video. Max 150MB. MP4, MOV, or WebM.",
    widget=forms.FileInput(attrs={
        'accept': 'video/mp4,video/quicktime,video/webm,video/avi',
    })
)
```

**Fixed Code:**
```python
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError as DjangoValidationError

MAX_VIDEO_SIZE_BYTES = 150 * 1024 * 1024  # 150MB

def validate_video_file_size(file):
    """Validate video file doesn't exceed 150MB"""
    if file.size > MAX_VIDEO_SIZE_BYTES:
        size_mb = file.size / (1024 * 1024)
        raise DjangoValidationError(
            f"Video file is {size_mb:.1f}MB. Maximum size is 150MB."
        )

video_file = forms.FileField(
    required=False,
    validators=[
        FileExtensionValidator(
            allowed_extensions=['mp4', 'mov', 'webm', 'avi'],
            message="Video format must be MP4, MOV, WebM, or AVI."
        ),
        validate_video_file_size,
    ],
    help_text="Optional walkthrough video. Max 150MB. Formats: MP4, MOV, WebM, AVI.",
    widget=forms.FileInput(attrs={
        'accept': 'video/mp4,video/quicktime,video/webm,video/avi',
    })
)
```

**Template - Add Client-Side Validation:**
```html
<!-- In create_property.html, update video input -->
{{ form.video_file }}

<!-- Add JavaScript for client-side validation -->
<script>
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
</script>
```

**Test Verification:**
```python
def test_video_file_size_validation():
    # Test over-size file rejection
    fake_video = SimpleUploadedFile(
        "test.mp4",
        b"x" * (200 * 1024 * 1024),  # 200MB
        content_type="video/mp4"
    )
    form = PropertyForm({
        'title': 'Test',
        # ... other fields ...
        'video_file': fake_video,
    })
    assert not form.is_valid()
    assert 'video_file' in form.errors
    assert "150MB" in form.errors['video_file'][0]

def test_video_file_extension_validation():
    # Test invalid file type
    fake_video = SimpleUploadedFile(
        "test.exe",
        b"malware",
        content_type="application/octet-stream"
    )
    form = PropertyForm({
        'title': 'Test',
        # ... other fields ...
        'video_file': fake_video,
    })
    assert not form.is_valid()
    assert 'video_file' in form.errors
```

---

### FIX #6: 🟠 HIGH — Add Lease Term Months Model Validator

**Issue:** F3 - Custom lease term not validated for bounds (can be 0 or 500)  
**Impact:** Invalid data in database, payment schedules break  
**Affected Files:** [apps/listings/models.py](apps/listings/models.py#L171-178)

**Current Code:**
```python
lease_term_months = models.PositiveSmallIntegerField(
    default=12,
    validators=[MinValueValidator(0)],
    help_text="Total duration of tenancy in months. "
)
```

**Fixed Code:**
```python
lease_term_months = models.PositiveSmallIntegerField(
    default=12,
    validators=[
        MinValueValidator(1),          # ← Changed from 0
        MaxValueValidator(240),        # ← Add max: 20 years
    ],
    help_text="Total duration of tenancy in months (1-240)."
)
```

**Also Update Form Field:**
```python
# In forms.py, the custom lease term field already has this:
lease_term_months_custom = forms.IntegerField(
    required=False,
    min_value=1,        # Already good
    max_value=240,      # Already good
    ...
)
```

**Test Verification:**
```python
def test_lease_term_bounds_enforced():
    """Model validates lease_term_months is between 1-240"""
    # Valid: 1 month
    prop = Property(lease_term_months=1, ...)
    prop.full_clean()  # Should pass
    
    # Invalid: 0 months
    prop = Property(lease_term_months=0, ...)
    with pytest.raises(ValidationError):
        prop.full_clean()
    
    # Invalid: 500 months (over 20 years)
    prop = Property(lease_term_months=500, ...)
    with pytest.raises(ValidationError):
        prop.full_clean()
```

---

## MEDIUM-PRIORITY ISSUES

### FIX #7: 🟡 MEDIUM — Improve Formset Error Display

**Issue:** F6 - Formset errors displayed as dict, not user-friendly  
**Impact:** Validation errors not visible to user  
**Affected Files:** [templates/listings/create_property.html](templates/listings/create_property.html#L176-209)

**Current Code:**
```django
{% for photo_form in photo_formset %}
<div style="background:#F7F3EC; border-radius:10px; padding:16px; margin-bottom:12px;">
  <div style="display:grid; grid-template-columns:1fr auto; gap:12px; align-items:start;">
    <div>
      {{ photo_form.image }}
      {% if photo_form.caption %}
      <div style="margin-top:8px;">
        {{ photo_form.caption }}
      </div>
      {% endif %}
    </div>
    <!-- ... primary and display_order fields ... -->
  </div>
  {% if photo_form.errors %}
    <p style="color:#DC2626; font-size:0.8rem; margin:8px 0 0;">{{ photo_form.errors }}</p>
  {% endif %}
</div>
{% endfor %}
```

**Fixed Code:**
```django
{% for photo_form in photo_formset %}
<div style="background:#F7F3EC; border-radius:10px; padding:16px; margin-bottom:12px;">
  <div style="display:grid; grid-template-columns:1fr auto; gap:12px; align-items:start;">
    <div>
      {{ photo_form.image }}
      {% if photo_form.image.errors %}
        <p style="color:#DC2626; font-size:0.8rem; margin:4px 0 0;">
          {{ photo_form.image.errors.0 }}
        </p>
      {% endif %}
      
      {% if photo_form.caption %}
      <div style="margin-top:8px;">
        {{ photo_form.caption }}
        {% if photo_form.caption.errors %}
          <p style="color:#DC2626; font-size:0.8rem; margin:4px 0 0;">
            {{ photo_form.caption.errors.0 }}
          </p>
        {% endif %}
      </div>
      {% endif %}
    </div>
    <!-- ... primary and display_order fields ... -->
  </div>
  
  {# Display any non-field errors #}
  {% if photo_form.non_field_errors %}
    <div style="background:#FEF2F2; border-left:3px solid #DC2626; padding:8px 12px; margin-top:8px; border-radius:4px;">
      {% for error in photo_form.non_field_errors %}
        <p style="color:#991B1B; font-size:0.8rem; margin:4px 0;">{{ error }}</p>
      {% endfor %}
    </div>
  {% endif %}
</div>
{% endfor %}

{# Display formset-level errors #}
{% if photo_formset.non_form_errors %}
<div style="background:#FEF2F2; border:1px solid #FECACA; border-radius:8px; padding:12px; margin-top:12px;">
  <p style="font-weight:600; color:#991B1B; font-size:0.875rem; margin-bottom:8px;">
    Photo upload errors:
  </p>
  {% for error in photo_formset.non_form_errors %}
    <p style="color:#991B1B; font-size:0.8rem; margin:4px 0;">{{ error }}</p>
  {% endfor %}
</div>
{% endif %}
```

**Test Verification:**
```python
def test_photo_form_errors_display():
    """Photo form errors should display per-field, not as dict"""
    # This is primarily a template test
    # Verify template rendering shows:
    # - Image field error under image input
    # - Caption field error under caption input
    # - Non-field errors in alert box
```

---

## DEPLOYMENT CHECKLIST

### Before Deployment

**Code Changes**
- [ ] FIX #1: Apply filter for empty photos in services.py
- [ ] FIX #2: Fix typo longtitude → longitude in models.py
- [ ] FIX #3: Re-raise video upload exceptions in services.py
- [ ] FIX #4: Update GPS validation to use field-specific errors in forms.py
- [ ] FIX #5: Add video file size validator in forms.py + JavaScript
- [ ] FIX #6: Add MaxValueValidator(240) to lease_term_months in models.py
- [ ] FIX #7: Update photo error display in template

**Testing**
- [ ] Run test suite for forms.py
- [ ] Run test suite for models.py (especially clean() method)
- [ ] Run test suite for services.py
- [ ] Manual black box testing on all form fields
- [ ] Manual GPS validation testing
- [ ] Manual photo upload testing
- [ ] Manual video upload testing (with valid & over-size files)

**Migrations**
- [ ] No migrations needed (only form/service logic changes for Fixes 1-5, 7)
- [ ] Verify lease_term_months model validator doesn't require migration

**Documentation**
- [ ] Update API docs if video endpoint exists
- [ ] Update admin panel help text for video_file field
- [ ] Update user-facing help text on form

---

## SUMMARY

| Fix | File | Change | Type | Risk |
|-----|------|--------|------|------|
| F1 | services.py | Filter empty photos | Logic | Low |
| F2 | forms.py | GPS field-specific errors | Form | Low |
| F3 | models.py | Add lease_term_months max validator | Validation | Low |
| F4 | forms.py + template | Video file size validation | Validation | Low |
| F5 | models.py | Fix typo longtitude | Bug | Low |
| F6 | template | Improve formset error display | UX | Low |
| F7 | services.py | Re-raise video exceptions | Exception | Medium* |

*Medium risk because changing exception behavior could affect error flow. Test thoroughly.
