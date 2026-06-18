import logging
from django.db import transaction
from .models import Property, PropertyPhoto, ListingStatus

import cloudinary.uploader

logger = logging.getLogger(__name__)


def create_listing(landlord, form_data, photo_formset=None):
    """
    Create a property listing with photos in a single atomic transaction.

    PATTERN: Everything in services.py, nothing in views.py.
    The view's job is: validate forms → call this → redirect.
    This function's job is: persist the data correctly.

    Why atomic?
    If the property saves but the photos fail, we'd have a listing with no photos.
    atomic() wraps both operations — either both succeed or neither do.

    Args:
        landlord:      User instance (role: landlord or property_manager)
        form_data:     cleaned_data dict from PropertyForm
        photo_formset: validated PropertyPhotoFormSet or None

    Returns:
        Property instance

    Raises:
        ValidationError if business rules are violated
        IntegrityError if DB constraints are violated (bubbles up)
    """
    with transaction.atomic():
        # Pull amenities out before saving (ManyToMany can't be set until PK exists)
        amenities = form_data.pop('amenities', [])

        property_obj = Property(landlord=landlord, **form_data)
        property_obj.full_clean()   # triggers model-level clean() — belt and suspenders
        property_obj.save()

        # Set amenities now that the object has a PK
        property_obj.amenities.set(amenities)
        # Handle video upload if provided
        video_file = form_data.pop('video_file', None)
        if video_file:
            url = upload_property_video(video_file, property_obj.pk)
            property_obj.video_url = url
            property_obj.save(update_fields=['video_url'])

        # Handle photos
        if photo_formset:
            photos = photo_formset.save(commit=False)

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

    logger.debug(f"[LISTINGS] Created property '{property_obj.title}' (id={property_obj.pk}) for {landlord.email}")
    return property_obj


def update_listing(property_obj, form_data, photo_formset=None):
    """Update an existing listing. Same atomic pattern as create."""
    with transaction.atomic():
        amenities = form_data.pop('amenities', [])

        for field, value in form_data.items():
            setattr(property_obj, field, value)

        property_obj.full_clean()
        property_obj.save()
        property_obj.amenities.set(amenities)

        if photo_formset:
            photos = photo_formset.save(commit=False)
            for photo in photos:
                photo.property = property_obj
                photo.save()
            for photo in photo_formset.deleted_objects:
                photo.delete()

    logger.debug(f"[LISTINGS] Updated property '{property_obj.title}' (id={property_obj.pk})")
    return property_obj


def publish_listing(property_obj):
    """Move a listing from DRAFT → ACTIVE. Simple state transition."""
    if property_obj.status != ListingStatus.DRAFT:
        raise ValueError(f"Cannot publish a listing with status '{property_obj.status}'.")
    property_obj.status = ListingStatus.ACTIVE
    property_obj.save(update_fields=['status', 'updated_at'])
    logger.debug(f"[LISTINGS] Published '{property_obj.title}'")
    return property_obj


def increment_view_count(property_obj):
    """
    Use update() not save() — avoids race condition where two simultaneous
    page views both read `views_count = 5`, both add 1, both write 6.
    update() sends a single SQL: UPDATE ... SET views_count = views_count + 1
    which the database handles atomically.
    """
    Property.objects.filter(pk=property_obj.pk).update(
        views_count=property_obj.views_count.__class__.F('views_count') + 1
        if False else None
    )
    # Simpler version using F expressions:
    from django.db.models import F
    Property.objects.filter(pk=property_obj.pk).update(views_count=F('views_count') + 1)




def upload_property_video(video_file, property_id):
    """
    Upload a video file to Cloudinary and return the secure URL.
    """
    result = cloudinary.uploader.upload(
        video_file,
        resource_type='video',          # tells Cloudinary this is video, not image
        folder=f'listings/{property_id}/videos',
        allowed_formats=['mp4', 'mov', 'avi', 'webm'],
        max_bytes=150 * 1024 * 1024,    # 150MB hard cap
    )
    return result['secure_url']