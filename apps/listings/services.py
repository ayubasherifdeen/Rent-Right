import logging
from django.db import transaction
from .models import Property, PropertyPhoto, ListingStatus



logger = logging.getLogger(__name__)





def create_listing(landlord, form_data, photo_formset=None):
    """
    Create a property listing with photos and video in a single atomic transaction.
    """
    with transaction.atomic():
        # Pull amenities out before saving (ManyToMany can't be set until PK exists)
        amenities = form_data.pop('amenities', [])

        # Extract and remove non-model/UI-only keys that appear in form.cleaned_data
        # (these would cause unexpected keyword arg errors on Property())
        video_file = form_data.pop('video_file', None)
        form_data.pop('lease_term_preset', None)
        form_data.pop('lease_term_months_custom', None)

        property_obj = Property(landlord=landlord, **form_data)
        property_obj.full_clean()   # triggers model-level clean() — belt and suspenders
        property_obj.save()

        # Set amenities now that the object has a PK
        property_obj.amenities.set(amenities)

        # Handle video upload if provided
        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception:
                logger.exception("Failed to upload property video")
                raise ValueError("Failed to upload property video. Please try again later.")

        # Handle photos
        if photo_formset:
            photos = photo_formset.save(commit=False)
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
    """Move a listing from DRAFT to ACTIVE"""
    if property_obj.status != ListingStatus.DRAFT:
        raise ValueError(f"Cannot publish a listing with status '{property_obj.status}'.")
    property_obj.status = ListingStatus.ACTIVE
    property_obj.save(update_fields=['status', 'updated_at'])
    logger.debug(f"[LISTINGS] Published '{property_obj.title}'")
    return property_obj


def increment_view_count(property_obj):
    """
    Use update() not save() — avoids race condition where two
    simultaneous requests read the same views_count and overwrite each other.
    """
    from django.db.models import F
    Property.objects.filter(pk=property_obj.pk).update(views_count=F('views_count') + 1)


def upload_property_video(video_file, property_id):
    """
    Upload a video file to Cloudinary and return the secure URL.
    """
    import cloudinary.uploader
    result = cloudinary.uploader.upload(
        video_file,
        resource_type='video',          # video
        folder=f'listings/{property_id}/videos',
        allowed_formats=['mp4', 'mov', 'avi', 'webm'],
        max_bytes=150 * 1024 * 1024,    # 150MB hard cap
    )
    return result['secure_url']