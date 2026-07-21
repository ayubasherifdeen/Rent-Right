import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from django.conf import settings


ACT_220_MAX_ADVANCE_MONTHS = 6  # Section 25(5) — hard ceiling, never bypass
LEASE_TERM_CHOICES = [
    (6, '6 months'),
    (12,'1 year (12 months)'),
    (24, '2 years (24 months)'),
    (36, '3 years (36 months)'),
    (0, 'other -  enter below'),
]


# CHOICES

class PropertyType(models.TextChoices):
    APARTMENT    = 'apartment',    'Apartment'
    HOUSE        = 'house',        'House'
    SINGLE_ROOM  = 'single_room',  'Single Room'
    CHAMBER_HALL = 'chamber_hall', 'Chamber & Hall'
    STUDIO       = 'studio',       'Studio'
    TOWNHOUSE    = 'townhouse',    'Townhouse'
    OFFICE       = 'office',       'Office / Commercial'


class FurnishingStatus(models.TextChoices):
    UNFURNISHED     = 'unfurnished',     'Unfurnished'
    SEMI_FURNISHED  = 'semi_furnished',  'Semi-Furnished'
    FULLY_FURNISHED = 'fully_furnished', 'Fully Furnished'


class ListingStatus(models.TextChoices):
    DRAFT     = 'draft',     'Draft'        # landlord hasn't published yet
    ACTIVE    = 'active',    'Active'       # visible to tenants, available
    RENTED    = 'rented',    'Rented'       # currently occupied
    PAUSED    = 'paused',    'Paused'       # landlord hid it temporarily
    ARCHIVED  = 'archived',  'Archived'     # permanently off market
    PENDING_PAYMENT = 'pending_payment', 'Pending Payment'  # tenancy created, rent card not issued yet


class PaymentCycle(models.TextChoices):
    MONTHLY   = 'monthly',   'Monthly'
    QUARTERLY = 'quarterly', 'Quarterly'
    BIANNUAL  = 'biannual',  'Bi-Annual'
    ANNUAL    = 'annual',    'Annual'


class Regions(models.TextChoices):
    GREATER_ACCRA = 'Greater Accra', 'Greater Accra'
    ASHANTI       = 'Ashanti',       'Ashanti'
    WESTERN       = 'Western',       'Western'
    EASTERN       = 'Eastern',       'Eastern'
    CENTRAL       = 'Central',       'Central'
    NORTHERN      = 'Northern',      'Northern'
    UPPER_EAST    = 'Upper East',    'Upper East'
    UPPER_WEST    = 'Upper West',    'Upper West'
    VOLTA         = 'Volta',         'Volta'
    SAVANNAH      = 'Savannah',      'Savannah'
    BRONG_AHAFO   = 'Brong-Ahafo',   'Brong-Ahafo'
    BONO_EAST     = 'Bono East',     'Bono East'
    OTI           = 'Oti',           'Oti'
    AHAFO = 'Ahafo',         'Ahafo'
    WESTERN_NORTH  = 'Western North',  'Western North'
    NORTH_EAST     = 'North East',     'North East'



# AMENITY

class Amenity(models.Model):
    """
    A controlled vocabulary of property features.
    """
    name = models.CharField(max_length=100, unique=True)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="SVG icon name or identifier for display in templates"
    )
    display_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers appear first in the amenity picker"
    )

    class Meta:
        verbose_name_plural = 'amenities'
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


# PROPERTY

class Property(models.Model):
    """
    The core listing model.

    Three things worth understanding about this model:

    1. ACT 220 ENFORCEMENT
       `advance_months` is validated at form level (forms.py) AND model level
       (clean() below). The model-level check catches anything that bypasses the
       form — admin panel edits, API calls, test data. The constant
       ACT_220_MAX_ADVANCE_MONTHS = 6 is the single source of truth.

    2. GPS COORDINATES
       Stored as DecimalField, not PointField (PostGIS). PostGIS requires
       a PostgreSQL extension that complicates local dev and deployment.
       DecimalField works everywhere — Leaflet only needs lat/lng floats.
       We can migrate to PostGIS if radius-search performance demands it.

    3. INSTALLMENT FLAG
       `has_instalment_plan` is set to True by the create_listing service
       when the landlord configures a schedule. It drives the badge shown
       to tenants ("📋 Instalment Agreement Available") and gates the
       negotiations app later.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Ownership
    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='properties',
        limit_choices_to={'userprofile__role__in': ['landlord', 'property_manager']},
    )

    # Core attributes
    title       = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    property_type     = models.CharField(max_length=20, choices=PropertyType.choices)
    furnishing_status = models.CharField(
        max_length=20,
        choices=FurnishingStatus.choices,
        default=FurnishingStatus.UNFURNISHED,
    )
    status = models.CharField(
        max_length=20,
        choices=ListingStatus.choices,
        default=ListingStatus.DRAFT,
    )

    # Size
    bedrooms  = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
        help_text="0 for studio / single room"
    )
    bathrooms = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )

    # Location
    address        = models.CharField(max_length=300)
    neighbourhood  = models.CharField(max_length=100, blank=True)
    city           = models.CharField(max_length=100, default='Accra')
    region         = models.CharField(
        max_length=100,
        choices=Regions.choices,
        default=Regions.GREATER_ACCRA,
    )
    latitude  = models.DecimalField(
        max_digits=9, decimal_places=6,
        null=True, blank=True,
        help_text="Decimal degrees. Drop pin on map or enter manually."
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6,
        null=True, blank=True,
    )

    # Financials: Act 220(5) lives here
    monthly_rent    = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(1)],
        help_text="Monthly rent in GHC"
    )
    payment_cycle   = models.CharField(
        max_length=15,
        choices=PaymentCycle.choices,
        default=PaymentCycle.ANNUAL,
        help_text="How often payment is collected"
    )
    advance_months  = models.PositiveSmallIntegerField(
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(ACT_220_MAX_ADVANCE_MONTHS)],
        help_text=(
            f"Advance payment required at move-in. "
            f"Maximum {ACT_220_MAX_ADVANCE_MONTHS} months per Section 25(5) of Act 220."
        )
    )
    security_deposit = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Refundable security deposit in GHC. 0 if none."
    )
    lease_term_months =models.PositiveSmallIntegerField(
        default = 12,
        validators=[MinValueValidator(0),
                    MaxValueValidator(240),
                    ],
        help_text="Total duration of tenancy in months. "
    
    )
    video_url = models.URLField(
        blank=True,
        help_text="Cloudinary video URL — set automatically on upload, don't edit manually."
    )
    
    # Instalment negotiation flag
    has_instalment_plan = models.BooleanField(
        default=False,
        help_text=(
            "True when landlord has configured an instalment schedule. "
            "Enables the negotiation engine and shows the 📋 badge."
        )
    )

    # Amenities
    amenities = models.ManyToManyField(Amenity, blank=True, related_name='properties')

    # Metadata of property
    available_from = models.DateField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    views_count    = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = 'properties'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.address}"

    def get_absolute_url(self):
        """
        for detailed view links. Used in templates and redirects after form submission.
        """
        return reverse('listings:property_detail', kwargs={'pk': self.pk})

    def clean(self):
        """
        Model-level validation — the second layer of Act 220 enforcement.

        Django calls clean() automatically in:
        - Admin panel saves
        - Form validation (when using ModelForm with full_clean())
        """
        errors = {}

        if self.advance_months and self.advance_months > ACT_220_MAX_ADVANCE_MONTHS:
            errors['advance_months'] = (
                f"Advance rent cannot exceed {ACT_220_MAX_ADVANCE_MONTHS} months "
                f"under Section 25(5) of the Rent Act, 1963 (Act 220). "
                f"You entered {self.advance_months} months."
            )

        if self.latitude and self.longitude:
            # Ghana bounding box — rough sanity check on coordinates
            if not (-3.5 <= float(self.latitude) <= 11.5):
                errors['latitude'] = "Latitude must be within Ghana (roughly -3.5° to 11.5°)."
            if not (-3.5 <= float(self.longitude) <= 1.5):
                errors['longitude'] = "Longitude must be within Ghana (roughly -3.5° to 1.5°)."

        if self.advance_months and self.lease_term_months:
            if self.advance_months > self.lease_term_months:
                errors['advance_months'] = (
                    f"Advance months ({self.advance_months}) cannot exceed "
                    f"the total lease term of ({self.lease_term_months}). "
                    f"A tenant cannot paymore upfront than the full tenancy is worth"
                )
        if errors:
            raise ValidationError(errors)


    @property
    def advance_amount(self):
        """Total move-in payment in GHC. Used on listing card and detail page."""
        return self.monthly_rent * self.advance_months

    @property
    def is_available(self):
        return self.status == ListingStatus.ACTIVE

    @property
    def primary_photo(self):
        """
        Returns the primary photo or None.
        Uses prefetch_related in views to avoid N+1 queries.
        """
        return self.photos.filter(is_primary=True).first()

    @property
    def act_220_compliant(self):
        """Always True for listings in the system — clean() guarantees it."""
        return self.advance_months <= ACT_220_MAX_ADVANCE_MONTHS
    
    @property
    def total_rent(self):
        """Total rent obligation over the full lease term in GHC"""
        return self.monthly_rent * self.lease_term_months
    
    @property
    def lease_term_years(self):
        "Convert lease month terms to years"
        if self.lease_term_months % 12 == 0:
            years =self.lease_term_months // 12
            return f"{years} year{'s' if years > 1 else ''}"
        return f"{self.lease_term_months} months"

    @property
    def payment_count(self):
        """
        How many payment rows the rent card will have.
        Used by the rent card generator to know how many rows to create.
        """
        cycle_map = {
            'monthly':   1,
            'quarterly': 3,
            'biannual':  6,
            'annual':    12,
        }
        divisor = cycle_map.get(self.payment_cycle, 12)
        return self.lease_term_months // divisor


# PROPERTY PHOTO
def _property_photo_path(instance, filename):
    """
    Generates upload path: listings/<property_uuid>/<filename>
    This function is referenced by PropertyPhoto.image — Django calls it at upload time.
    """
    return f"listings/{instance.property.pk}/{filename}"

class PropertyPhoto(models.Model):
    """
    Separate model for photos, not an ArrayField or JSONField.

    Why? Each photo needs:
    - Its own upload path
    - An is_primary flag (only one per property)
    - A display_order for the gallery
    - The ability to delete/replace individual photos

    All of that is painful with an array. A join table is the clean solution.
    """

    property    = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='photos')
    image       = models.ImageField(upload_to=_property_photo_path)
    caption     = models.CharField(max_length=200, blank=True)
    is_primary  = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0, blank=True, null=True, help_text="Lower numbers appear first in the gallery")
    uploaded_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'display_order']

    def __str__(self):
        label = "Primary" if self.is_primary else f"Photo {self.display_order}"
        return f"{self.property.title} — {label}"

    def save(self, *args, **kwargs):
        """
        Enforce: only one primary photo per property.
        If this photo is being saved as primary, demote all others first.
        Runs inside a transaction (called by the service layer).
        """
        if self.is_primary:
            PropertyPhoto.objects.filter(
                property=self.property,
                is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)



