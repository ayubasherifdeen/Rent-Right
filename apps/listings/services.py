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
        video_file = form_data.pop('video_file', None)
        form_data.pop('lease_term_preset', None)
        form_data.pop('lease_term_months_custom', None)

        for field, value in form_data.items():
            setattr(property_obj, field, value)

        property_obj.full_clean()
        property_obj.save()
        property_obj.amenities.set(amenities)

        if video_file:
            try:
                url = upload_property_video(video_file, property_obj.pk)
                property_obj.video_url = url
                property_obj.save(update_fields=['video_url'])
            except Exception:
                logger.exception("Failed to upload property video")
                raise ValueError("Failed to upload property video. Please try again later.")
            
        if photo_formset:
            photos = photo_formset.save(commit=False)
            photos = [
                p for p in photos
                if p.pk or p.image   # keep existing DB records OR new ones with an image
            ]
            for photo in photos:
                photo.property = property_obj
                photo.save()
            for photo in photo_formset.deleted_objects:
                photo.delete()

    logger.debug(f"[LISTINGS] Updated property '{property_obj.title}' (id={property_obj.pk})")
    return property_obj


def pause_listing(property_obj):
    """
    Temporarily hide an active listing from tenants without losing it.
    Landlord can resume later — e.g. taking a short break from showings.
    """
    if property_obj.status != ListingStatus.LIVE:
        raise ValueError(
            f"Cannot pause a listing with status '{property_obj.status}'. "
            f"Only live listings can be paused."
        )
    property_obj.status = ListingStatus.PAUSED
    property_obj.save(update_fields=['status', 'updated_at'])
    logger.debug(f"[LISTINGS] Paused '{property_obj.title}'")
    return property_obj
 
 
def resume_listing(property_obj):
    """Bring a paused listing back to active/visible."""
    if property_obj.status != ListingStatus.PAUSED:
        raise ValueError(
            f"Cannot resume a listing with status '{property_obj.status}'. "
            f"Only paused listings can be resumed."
        )
    property_obj.status = ListingStatus.LIVE
    property_obj.save(update_fields=['status', 'updated_at'])
    logger.debug(f"[LISTINGS] Resumed '{property_obj.title}'")
    return property_obj
 
 
def archive_listing(property_obj):
    """
    Permanently take a listing off the market.
 
    Allowed from draft/active/paused. Deliberately NOT allowed from
    'rented' — there's a live tenancy there
    """
    allowed = {ListingStatus.DRAFT, ListingStatus.LIVE, ListingStatus.PAUSED}
    if property_obj.status not in allowed:
        raise ValueError(
            f"Cannot archive a listing with status '{property_obj.status}'. "
            f"Only draft, live, or paused listings can be archived."
        )
    property_obj.status = ListingStatus.ARCHIVED
    property_obj.save(update_fields=['status', 'updated_at'])
    logger.debug(f"[LISTINGS] Archived '{property_obj.title}'")
    return property_obj
 

def publish_listing(property_obj):
    """Move a listing from DRAFT to LIVE"""
    if property_obj.status != ListingStatus.DRAFT:
        raise ValueError(f"Cannot publish a listing with status '{property_obj.status}'.")
    property_obj.status = ListingStatus.LIVE
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

    If the provider does not return a usable URL, raise a clear ValueError so the
    calling view can stop the request and avoid rendering a broken empty video tag.
    """
    import cloudinary.uploader

    result = cloudinary.uploader.upload(
        video_file,
        resource_type='video',
        folder=f'listings/{property_id}/videos',
        allowed_formats=['mp4', 'mov', 'avi', 'webm'],
        max_bytes=150 * 1024 * 1024,
    )

    secure_url = result.get('secure_url') if isinstance(result, dict) else None
    if not secure_url:
        raise ValueError('Cloudinary did not return a valid video URL for this upload.')

    return secure_url


def relist_after_lease_end(property_obj):
    """
    Landlord confirms the unit is actually vacant and puts it back on
    the market after a tenancy ended.
    """
    if property_obj.status != ListingStatus.LEASE_ENDED:
        raise ValueError(
            f"Cannot relist a listing with status '{property_obj.status}'. "
            f"Only listings whose lease has ended can be relisted this way."
        )
    property_obj.status = ListingStatus.LIVE
    property_obj.save(update_fields=['status', 'updated_at'])
    logger.debug(f"[LISTINGS] Relisted '{property_obj.title}' after lease end")
    return property_obj