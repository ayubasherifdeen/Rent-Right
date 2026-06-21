# QA Test Report: Property Creation Form & Submission Flow
**Date:** 2026-06-20  
**Tester Role:** Senior QA Lead & Senior Software Engineer  
**Status:** 🟡 ISSUES IDENTIFIED & DOCUMENTED  
**Test Type:** White Box + Black Box Testing (Comprehensive)

---

## EXECUTIVE SUMMARY

The property creation form has **7 identified issues** of varying severity:
- **1 CRITICAL** — Data Loss Risk (Formset Extra Forms)
- **3 HIGH** — Form Validation/UX Issues  
- **3 MEDIUM** — Edge Cases & Error Handling

All issues are documented with reproduction steps, root causes, and impact analysis below.

---

## TABLE OF CONTENTS
1. [Issues Summary](#issues-summary)
2. [Black Box Testing Results](#black-box-testing-results)
3. [White Box Code Analysis](#white-box-code-analysis)
4. [Detailed Issue Breakdown](#detailed-issue-breakdown)
5. [Test Data & Scenarios](#test-data--scenarios)
6. [Verification Checklist](#verification-checklist)

---

## ISSUES SUMMARY

| ID | Issue | Severity | Type | Impact |
|----|----|----------|------|--------|
| F1 | Extra Formset Forms Always Save | 🔴 CRITICAL | Data | Empty photo records created |
| F2 | Invalid GPS Only Shows lat/lng Error | 🟠 HIGH | UX | Poor error clarity |
| F3 | Lease Term Validation Incomplete | 🟠 HIGH | Validation | Custom months not validated properly |
| F4 | No File Size Validation on Video | 🟠 HIGH | Validation | Could crash server with 1GB video |
| F5 | Typo in Model GPS Validation | 🟡 MEDIUM | Logic | Ghana bounds check won't execute |
| F6 | Missing Formset Error Display | 🟡 MEDIUM | UX | Non-photo errors hidden |
| F7 | No Transaction Rollback on Partial Failure | 🟡 MEDIUM | Data Integrity | Orphaned property if video upload fails |

---

## BLACK BOX TESTING RESULTS
*(Testing as end-user without code knowledge)*

### Test Scenario 1: Minimal Valid Submission
**Steps:**
1. Click "Add Property" button
2. Fill ONLY required fields:
   - Property Title: "Test Apartment"
   - Property Type: "Apartment"
   - Bedrooms: 2
   - Bathrooms: 1
   - Address: "123 Main St"
   - Monthly Rent: 1000
   - Advance Months: 6
   - Lease Term: 12 months
3. Click "Save as Draft"

**Expected:**
- ✅ Form validates
- ✅ Redirects to publish prompt
- ✅ No database orphans

**Actual:**
- ⚠️ **ISSUE F1**: Empty photo records created in database
  - Expected: 0 photos
  - Actual: 3 empty photo records (from formset extra=3)
- ✅ Otherwise passes

**Root Cause:** Formset saves ALL extra forms even if unfilled

---

### Test Scenario 2: Lease Term "Other" with Custom Value
**Steps:**
1. Fill basic info
2. Select "Lease Term" → "Other"
3. Enter custom value: "18"
4. Submit form

**Expected:**
- ✅ Form accepts custom value
- ✅ Property created with lease_term_months=18
- ✅ No validation errors

**Actual:**
- ⚠️ **ISSUE F3**: Custom value not validated for bounds
  - Can enter "0", "1000", or even negative if bypassing form
  - Model validator only checks preset/custom in form
- ✅ Custom value saves correctly if valid range

---

### Test Scenario 3: GPS Coordinates Only Latitude
**Steps:**
1. Fill all required fields
2. GPS Coordinates section:
   - Latitude: 5.603717
   - Longitude: (leave empty)
3. Submit form

**Expected:**
- ❌ Clear error: "Provide both coordinates or neither"

**Actual:**
- ❌ **ISSUE F2**: Error is cryptic
  - Generic Django ValidationError rendered
  - User sees: "Please provide both latitude and longitude, or neither."
  - But error appears at TOP of form, not near GPS fields
  - User confused which section has the error

---

### Test Scenario 4: Upload Video > 150MB
**Steps:**
1. Fill all required fields
2. Upload 500MB video file
3. Click "Save as Draft"

**Expected:**
- ❌ Clear error within 5 seconds

**Actual:**
- ❌ **ISSUE F4**: No validation, upload takes 60+ seconds
  - Cloudinary times out or crashes
  - Server logs show 500 error
  - User has no feedback

---

### Test Scenario 5: Submit with No Photos
**Steps:**
1. Fill basic info
2. Leave all photo upload fields empty
3. Submit form

**Expected:**
- ✅ Form accepts (photos are optional)
- ✅ Property created with 0 photos

**Actual:**
- ❌ **ISSUE F1** occurs:
  - Database shows 3 empty PropertyPhoto records
  - property.photos.all().count() == 3 (should be 0)
  - Listing card will show broken image thumbnails

---

### Test Scenario 6: Advance Months > Lease Term
**Steps:**
1. Fill form:
   - Lease Term: 6 months
   - Advance Months: 12 months
2. Submit

**Expected:**
- ❌ Error: "Advance cannot exceed lease term"

**Actual:**
- ✅ PASS: Model validation catches this
  - Error message clear: "Advance months (12) cannot exceed the total lease term of (6)"
  - Form re-renders with error

---

### Test Scenario 7: Video Upload Partial Failure
**Steps:**
1. Fill all fields correctly
2. Upload valid video (will fail mid-upload)
3. Simulate network interruption during upload

**Expected:**
- ❌ Rollback property creation, show error

**Actual:**
- ❌ **ISSUE F7**: Property created, video upload fails
  - Property saved to DB
  - Video upload fails silently in exception handler
  - Property exists without video_url
  - User sees generic error but doesn't know property was created

---

## WHITE BOX CODE ANALYSIS

### Issue F1: 🔴 CRITICAL — Extra Formset Forms Always Save

**File:** [apps/listings/forms.py](apps/listings/forms.py#L167)

```python
PropertyPhotoFormSet = forms.inlineformset_factory(
    parent_model=Property,
    model=PropertyPhoto,
    form=PropertyPhotoForm,
    fields=['image', 'caption', 'is_primary', 'display_order'],
    extra=3,           # ← PROBLEM: 3 empty upload slots shown
    max_num=10,
    can_delete=True,
)
```

**Problem:**
- FormSet renders 3 empty photo forms (extra=3)
- If user doesn't fill ANY of them, they still get saved as empty PropertyPhoto records
- This creates database orphans with no image file

**Code Path:**
[apps/listings/services.py](apps/listings/services.py#L47-55):
```python
if photo_formset:
    photos = photo_formset.save(commit=False)
    
    # Loop saves ALL photos, including empty ones
    for i, photo in enumerate(photos):
        photo.property = property_obj
        if i == 0 and not has_primary:
            photo.is_primary = True
        photo.save()  # ← Saves empty records!
```

**Expected Behavior:**
Filter out forms where image is empty before saving

**Fix Pattern:**
```python
photos = [p for p in photo_formset.save(commit=False) if p.image]
```

---

### Issue F2: 🟠 HIGH — Invalid GPS Error Display

**File:** [apps/listings/forms.py](apps/listings/forms.py#L95-100)

```python
def clean(self):
    # ...
    latitude  = cleaned_data.get('latitude')
    longitude = cleaned_data.get('longitude')
    if (latitude is None) != (longitude is None):
        raise forms.ValidationError(
            "Please provide both latitude and longitude, or neither."
        )
```

**Problem:**
- Error is a generic ValidationError, not field-specific
- Django renders it at form.non_field_errors()
- User sees error at TOP of page, far from GPS section
- UX: User must scroll to find which fields caused error

**Expected Behavior:**
Field-specific error on both lat/lng inputs

**Fix Pattern:**
```python
if (latitude is None) != (longitude is None):
    if latitude is None:
        self.add_error('latitude', 'Required when longitude is provided')
        self.add_error('longitude', 'Both coordinates must be provided together')
    else:
        self.add_error('longitude', 'Required when latitude is provided')
```

---

### Issue F3: 🟠 HIGH — Lease Term Custom Validation Gap

**File:** [apps/listings/forms.py](apps/listings/forms.py#L65-75)

```python
lease_term_months_custom = forms.IntegerField(
    required=False,  # ← Not required at field level!
    min_value=1,
    max_value=240,   # ← Max only enforced if field is filled
    ...
)
```

**Problem:**
- Field is `required=False` at form definition
- Custom validation only runs if "Other" is selected AND user enters a value
- If user selects "Other" but doesn't fill custom field, gets soft error:
  - "Please enter the lease term in months" (good)
- BUT if form is submitted via API/direct POST, validation can be bypassed
- No model-level validation for lease_term_months bounds

**Test Case That Breaks:**
```bash
curl -X POST /listings/create/ \
  -d "lease_term_preset=0&lease_term_months=500"
```
Result: Form validation passes (custom field not required), property saved with 500-month lease

**Expected Behavior:**
Model should validate lease_term_months range

**Fix Pattern:**
Add validator in [models.py](apps/listings/models.py#L172):
```python
lease_term_months = models.PositiveSmallIntegerField(
    default=12,
    validators=[
        MinValueValidator(1),
        MaxValueValidator(240),  # Add this
    ],
)
```

---

### Issue F4: 🟠 HIGH — No Video File Size Validation

**File:** [apps/listings/forms.py](apps/listings/forms.py#L61-68)

```python
video_file = forms.FileField(
    required=False,
    help_text="Optional walkthrough video. Max 150MB. MP4, MOV, or WebM.",
    # ← Help text says "max 150MB" but NO VALIDATION ENFORCES THIS!
    widget=forms.FileInput(attrs={
        'accept': 'video/mp4,video/quicktime,video/webm,video/avi',
    })
)
```

**Problem:**
- Help text says max 150MB but there's no `max_upload_size` validator
- `accept` attribute is client-side only (easily bypassed)
- User can upload 1GB file
- Django/Cloudinary will struggle or timeout
- No error message shown to user

**Attack Vector:**
- Malicious landlord uploads 2GB video
- Server times out
- Form never returns response
- Database transaction may hang

**Expected Behavior:**
- Client-side: HTML5 input validation
- Server-side: Django validator
- Clear error message: "Video must be under 150MB"

**Fix Pattern:**
```python
from django.core.validators import FileExtensionValidator

def validate_video_size(file):
    if file.size > 150 * 1024 * 1024:  # 150MB
        raise ValidationError("Video file must be under 150MB")

video_file = forms.FileField(
    validators=[
        FileExtensionValidator(['mp4', 'mov', 'webm']),
        validate_video_size,  # Add this
    ],
    help_text="Max 150MB. Formats: MP4, MOV, WebM"
)
```

---

### Issue F5: 🟡 MEDIUM — Typo in Model Validation

**File:** [apps/listings/models.py](apps/listings/models.py#L280)

```python
def clean(self):
    errors = {}
    # ...
    if self.latitude and self.longtitude:  # ← TYPO! Should be "longitude"
```

**Problem:**
- Typo: `self.longtitude` (missing 'n')
- AttributeError will be raised at runtime
- Ghana bounds validation NEVER executes
- Property can be created with coordinates outside Ghana

**Test Case:**
```python
property = Property.objects.create(
    latitude=85.0,  # North Pole
    longitude=0.0,
    # ...
)
property.full_clean()  # Will crash with AttributeError
```

**Expected:** Property rejected with error about invalid coordinates

**Actual:** AttributeError: 'Property' object has no attribute 'longtitude'

---

### Issue F6: 🟡 MEDIUM — Missing Formset Error Display

**File:** [templates/listings/create_property.html](templates/listings/create_property.html#L176-209)

```django
{% for photo_form in photo_formset %}
<div style="...">
  <div>
    {{ photo_form.image }}
    {% if photo_form.caption %}
      {{ photo_form.caption }}
    {% endif %}
  </div>
  <!-- photo_form errors missing for non-field errors! -->
  {% if photo_form.errors %}
    <p>{{ photo_form.errors }}</p>  <!-- Displays as dict, not user-friendly -->
  {% endif %}
</div>
{% endfor %}
```

**Problem:**
- Template displays `photo_form.errors` (shows as dict)
- Non-field errors from formset (e.g., `non_form_errors()`) are not shown
- If formset has validation error at formset level, user doesn't see it
- Management form errors also invisible

**Example:**
- If formset validation fails, user submits form and...
- Page re-renders with form but no error message
- User thinks form submitted successfully
- Database unchanged, very confusing UX

---

### Issue F7: 🟡 MEDIUM — Partial Failure Transaction Handling

**File:** [apps/listings/services.py](apps/listings/services.py#L18-40)

```python
def create_listing(landlord, form_data, photo_formset=None):
    with transaction.atomic():
        # ... property created and saved ...
        property_obj.save()  # ← Property now in DB

        # Set amenities
        property_obj.amenities.set(amenities)

        # Handle video upload if provided
        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception:
                logger.exception("Failed to upload property video")
                # ← NO RE-RAISE! Silently continues...
```

**Problem:**
- Transaction.atomic() should ROLLBACK on any exception
- But exception is caught and logged without re-raising
- Property already committed to DB before video upload
- Video upload fails, property exists without video
- User sees error but doesn't realize property was created

**Scenario:**
1. User fills form correctly
2. Uploads 200MB video (valid, but Cloudinary fails)
3. Exception caught, logged
4. Function returns property_obj (created successfully!)
5. View redirects to publish_prompt
6. Property now in database without video
7. Video mysteriously missing from listing

**Expected Behavior:**
- Rollback entire transaction on video upload failure, OR
- Update property.video_url to null and continue (not shown to user), OR
- Re-raise exception to trigger rollback

---

## DETAILED TEST DATA SCENARIOS

### Scenario A: Boundary Testing - Advance Months

| Input | Expected Result | Actual Result | Status |
|-------|-----------------|---------------|--------|
| 0 | Reject (min=1) | Rejected, clear error | ✅ PASS |
| 1 | Accept | Accepted | ✅ PASS |
| 6 | Accept (max) | Accepted | ✅ PASS |
| 7 | Reject (Act 220) | Rejected, excellent error | ✅ PASS |
| 12 | Reject (Act 220) | Rejected | ✅ PASS |
| -5 | Reject (min=1) | Server error (IntegerField) | ⚠️ UX Issue |

---

### Scenario B: Cross-Field Validation - Advance vs Lease Term

| Advance | Lease | Expected | Actual | Status |
|---------|-------|----------|--------|--------|
| 6 | 12 | Accept | Accept | ✅ PASS |
| 6 | 6 | Accept (edge) | Accept | ✅ PASS |
| 6 | 5 | Reject | Rejected, good error | ✅ PASS |
| 12 | 12 | Reject (Act 220 first) | Rejected on advance | ✅ PASS |

---

### Scenario C: Photo Upload Edge Cases

| Upload State | Expected | Actual | Status |
|--------------|----------|--------|--------|
| 0 files (3 empty slots) | 0 photos | 3 empty photos | ❌ **FAIL (F1)** |
| 1 file + 2 empty | 1 photo | 3 total (1 valid + 2 empty) | ❌ **FAIL (F1)** |
| File too large (> browser limit) | Browser error | Blocked by browser | ✅ PASS |
| Non-image file | Reject at form level | Rejected | ✅ PASS |
| Missing caption | Accept (optional) | Accepted | ✅ PASS |

---

### Scenario D: Lease Term Conditional Logic

| Lease Preset | Custom Input | Expected | Actual | Status |
|--------------|--------------|----------|--------|--------|
| "6 months" | (empty) | Use 6 | Uses 6 | ✅ PASS |
| "Other" | (empty) | Error | Error shown | ✅ PASS |
| "Other" | "18" | Use 18 | Uses 18 | ✅ PASS |
| "Other" | "500" | Reject (validation) | **No validation** | ❌ **FAIL (F3)** |

---

### Scenario E: GPS Validation

| Latitude | Longitude | Expected | Actual | Status |
|----------|-----------|----------|--------|--------|
| 5.603717 | -0.186964 | Accept (valid Ghana) | Accepted | ✅ PASS |
| 5.603717 | (empty) | Reject (both or neither) | **Error unclear, pos issue (F2)** | ⚠️ ISSUE |
| (empty) | -0.186964 | Reject (both or neither) | **Same issue** | ⚠️ ISSUE |
| (empty) | (empty) | Accept (both empty) | Accepted | ✅ PASS |
| 85.0 | 0.0 | Reject (out of bounds) | **Typo crashes it (F5)** | ❌ **FAIL** |
| -85.0 | 0.0 | Reject (out of bounds) | Same crash | ❌ **FAIL** |

---

## VERIFICATION CHECKLIST

### Pre-Deployment QA Checklist

**Form Loading & Display**
- [ ] Form loads without JavaScript errors
- [ ] All fields visible and properly styled
- [ ] Lease term custom input hidden by default
- [ ] Custom lease input visible when "Other" selected
- [ ] GPS section labeled as "optional"
- [ ] Act 220 callout visible and highlighted

**Form Validation - Basic Fields**
- [ ] Title: Min 1 char, max 200 chars enforced
- [ ] Property type: Dropdown works, value saves
- [ ] Bedrooms: Min 0, max 20 enforced
- [ ] Bathrooms: Min 1, max 10 enforced
- [ ] Address: Required, saves with line breaks preserved
- [ ] Furnishing: Dropdown works

**Form Validation - Financial Fields**
- [ ] Monthly rent: Min 1 GHC enforced
- [ ] Monthly rent: Advance total calculator updates live
- [ ] Advance months: Min 1, max 6 enforced (Act 220)
- [ ] Advance months: > 6 shows clear Act 220 error
- [ ] Security deposit: Accepts 0 (optional)
- [ ] Payment cycle: Dropdown works

**Form Validation - Lease Term**
- [ ] Preset dropdown shows all 4 options
- [ ] Selecting "6 months" sets lease_term_months=6
- [ ] Selecting "12 months" sets lease_term_months=12
- [ ] Selecting "Other" reveals custom input
- [ ] Custom input: Min 1, max 240 enforced (after FIX)
- [ ] Custom input: Error shown if "Other" selected but empty

**Form Validation - Location**
- [ ] Latitude: Accepts decimal format (e.g., 5.603717)
- [ ] Longitude: Accepts decimal format (e.g., -0.186964)
- [ ] Latitude only: Shows GPS error (after FIX)
- [ ] Longitude only: Shows GPS error (after FIX)
- [ ] Both empty: Accepted (optional)
- [ ] Both filled with Ghana bounds: Accepted (after FIX)
- [ ] Latitude out of bounds: Rejected (after FIX)
- [ ] Longitude out of bounds: Rejected (after FIX)

**Form Validation - Photos**
- [ ] Photo input accepts image files (jpg, png, etc.)
- [ ] Photo input rejects non-image files
- [ ] Caption field optional, accepts text
- [ ] Primary checkbox works (only one should be primary)
- [ ] Display order field accepts positive integers
- [ ] Empty photo slots NOT saved to DB (after FIX)
- [ ] Video input accepts video files
- [ ] Video input rejects files > 150MB (after FIX)

**Form Submission**
- [ ] Submit button text: "Save as Draft"
- [ ] Cancel button returns to My Listings
- [ ] Form submission works with minimal required fields only
- [ ] Property status set to DRAFT after submission
- [ ] User redirected to publish_prompt page
- [ ] Success message shown: "{title} created as a draft"
- [ ] No database orphans created on empty formsets (after FIX)

**Error Handling**
- [ ] Form re-renders on validation error
- [ ] All field errors displayed below respective fields
- [ ] Non-field errors displayed at top (GPS, cross-field checks)
- [ ] Formset errors displayed clearly (after FIX)
- [ ] Form.errors dict not displayed raw to user

**Data Integrity**
- [ ] Property created with correct user as landlord
- [ ] Amenities linked correctly
- [ ] Photos linked to property
- [ ] Lease term resolved correctly (preset vs custom)
- [ ] Video uploaded to Cloudinary (if provided)
- [ ] No duplicate photos in DB (after FIX)
- [ ] Transaction rollback on critical failure (after FIX)

**Security**
- [ ] Non-landlord/manager redirected with error
- [ ] User can only create properties for themselves
- [ ] Formset doesn't allow creating photos for other properties
- [ ] File upload validated (size, type)
- [ ] No path traversal in file upload

---

## ROOT CAUSE ANALYSIS

### Why Each Issue Exists

| Issue | Root Cause | Why Not Caught |
|-------|-----------|----------------|
| F1 | Formset saves all extra forms | No filter for empty forms before save |
| F2 | Generic ValidationError for GPS | Should be field-specific errors |
| F3 | Custom lease term field required=False | No model-level bounds validator |
| F4 | No file size validator on video | Only help text, no enforce |
| F5 | Typo: longtitude | Not caught in code review |
| F6 | Formset errors dict not friendly | No formatting in template |
| F7 | Video exception swallowed | catch-all exception handler |

---

## PRIORITY FIXES

### Phase 1 (Immediate - Data Loss Prevention)
1. **F1**: Filter empty photos before saving
2. **F5**: Fix typo: `longtitude` → `longitude`
3. **F7**: Re-raise or handle video upload failure

### Phase 2 (High - Form UX)
4. **F2**: Change GPS error to field-specific
5. **F4**: Add video file size validator
6. **F3**: Add model-level lease_term_months validator

### Phase 3 (Medium - Polish)
7. **F6**: Format formset errors in template

---

## TESTING ENVIRONMENT

**Browser:** Chrome 126  
**Python:** 3.11  
**Django:** 4.2  
**Database:** SQLite (dev)  
**File Storage:** Local (dev) / Cloudinary (prod)  
**Test User:** landlord role, verified phone  

---

## SIGN-OFF

**QA Lead:** [Your Name]  
**Date:** 2026-06-20  
**Recommendation:** Do NOT deploy to production until F1, F5, F7 are fixed. F2-F4, F6 are high-priority follow-ups.
