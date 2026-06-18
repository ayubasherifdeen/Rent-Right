from django import forms
from django.core.exceptions import ValidationError
from .models import Property, PropertyPhoto, Amenity, ACT_220_MAX_ADVANCE_MONTHS


class PropertyForm(forms.ModelForm):
    """
    The primary listing creation/edit form.

    ACT 220 ENFORCEMENT — FIRST LINE OF DEFENCE:
    clean_advance_months() is the user-facing enforcement point.
    It gives a clear, human-readable error at form submission time —
    before anything touches the database. The model's clean() is the
    second line of defence (catches admin/API submissions).

    Why is the cap enforced here AND in the model?
    Defence in depth. Forms can be bypassed (API, admin, shell). Models
    can be bypassed (.update() calls). Having both means there's no way
    into the database with an illegal value short of raw SQL.

    INSTALMENT PROMPT:
    If `advance_months` > 6, instead of just erroring, the form sets
    `suggest_instalment = True` so the view can render the instalment
    schedule builder. The landlord chose > 6 months — we don't refuse,
    we redirect: "cap it at 6, put the rest in an instalment plan".
    """

    # Override to add placeholder and better help text
    advance_months = forms.IntegerField(
        min_value=1,
        max_value=ACT_220_MAX_ADVANCE_MONTHS,
        initial=6,
        help_text=(
            f"Maximum {ACT_220_MAX_ADVANCE_MONTHS} months under Section 25(5) "
            f"of the Rent Act, 1963 (Act 220)."
        ),
        widget=forms.NumberInput(attrs={
            'min': 1,
            'max': ACT_220_MAX_ADVANCE_MONTHS,
            'placeholder': '6',
        })
    )
    video_file = forms.FileField(
        required=False,
        help_text="Optional walkthrough video. Max 150MB. MP4, MOV, or WebM.",
        widget=forms.FileInput(attrs={
            'accept': 'video/mp4,video/quicktime,video/webm,video/avi',
        })
    )

    class Meta:
        model  = Property
        fields = [
            'title', 'description', 'property_type', 'furnishing_status',
            'bedrooms', 'bathrooms',
            'address', 'neighbourhood', 'city', 'region', 'latitude', 'longitude',
            'monthly_rent', 'payment_cycle', 'advance_months', 'security_deposit',
            'amenities', 'available_from',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe the property...'}),
            'available_from': forms.DateInput(attrs={'type': 'date'}),
            'amenities': forms.CheckboxSelectMultiple(),
            'latitude': forms.NumberInput(attrs={'step': '0.000001', 'placeholder': '5.603717'}),
            'longitude': forms.NumberInput(attrs={'step': '0.000001', 'placeholder': '-0.186964'}),
        }
        labels = {
            'monthly_rent': 'Monthly Rent (GHC)',
            'security_deposit': 'Security Deposit (GHC)',
            'available_from': 'Available From',
        }

    def clean_advance_months(self):
        """
        Act 220 Section 25(5) enforcement.
        This is called automatically by Django during form.is_valid().
        The name pattern clean_<fieldname> is Django's hook for per-field validation.
        """
        advance_months = self.cleaned_data.get('advance_months')

        if advance_months is None:
            return advance_months

        if advance_months > ACT_220_MAX_ADVANCE_MONTHS:
            raise ValidationError(
                f"Section 25(5) of the Rent Act, 1963 (Act 220) limits advance rent "
                f"to a maximum of {ACT_220_MAX_ADVANCE_MONTHS} months. "
                f"You entered {advance_months} months. "
                f"To collect more, set up an Instalment Plan — this lets you structure "
                f"future payments while keeping the move-in advance legal."
            )

        return advance_months

    def clean(self):
        """
        Cross-field validation — runs after all individual field clean() methods.
        Used when one field's validity depends on another.
        """
        cleaned_data = super().clean()
        latitude  = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')

        # If one GPS coordinate is given, both must be given
        if (latitude is None) != (longitude is None):
            raise ValidationError(
                "Please provide both latitude and longitude, or neither."
            )

        return cleaned_data


class PropertyPhotoForm(forms.ModelForm):
    """Simple photo upload form. Used in formset for multi-photo upload."""
    class Meta:
        model  = PropertyPhoto
        fields = ['image', 'caption', 'is_primary', 'display_order']
        widgets = {
            'caption': forms.TextInput(attrs={'placeholder': 'e.g. Living room, Master bedroom...'}),
        }


# Formset: up to 10 photos per property, at least 0 required
PropertyPhotoFormSet = forms.inlineformset_factory(
    parent_model=Property,
    model=PropertyPhoto,
    form=PropertyPhotoForm,
    fields=['image', 'caption', 'is_primary', 'display_order'],
    extra=3,           # 3 empty upload slots shown by default
    max_num=10,        # hard cap
    can_delete=True,   # X button on each existing photo
)
