from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator as DjangoFileExtensionValidator
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Property, PropertyPhoto, Amenity, ACT_220_MAX_ADVANCE_MONTHS, LEASE_TERM_CHOICES, Regions

MAX_VIDEO_SIZE = 150 * 1024 * 1024

class PropertyForm(forms.ModelForm):
    """
    The primary listing creation/edit form.

    ACT 220 ENFORCEMENT — FIRST LINE OF DEFENCE:
    clean_advance_months() is the user-facing enforcement point.
    It gives a clear, human-readable error at form submission time —
    before anything touches the database. The model's clean() is the
    second line of defence (catches admin/API submissions).

    INSTALLMENT PROMPT:
    If `advance_months` > 6, instead of just erroring, the form sets
    `suggest_instalment = True` so the view can render the instalment
    schedule builder. The landlord chose > 6 months — we don't refuse,
    we redirect: "cap it at 6, put the rest in an instalment plan".
    """

    def validate_video_size(file):
        if file.size > MAX_VIDEO_SIZE:
            mb = file.size / (1024 * 1024)
            raise DjangoValidationError(f"Video is {mb:.1f}MB. Max: 150MB.")

    # Override to add placeholder and better help text
    advance_months = forms.IntegerField(
        min_value=1,
        max_value=ACT_220_MAX_ADVANCE_MONTHS,
        initial=6,
        help_text=(
            f"Maximum {ACT_220_MAX_ADVANCE_MONTHS} months under Section 25(5) "
            f"of the Rent Act, 1963 (Act 220)."
        ),
        error_messages={
            'max_value': (
                "Section 25(5) of the Rent Act, 1963 (Act 220) limits advance rent "
                "to a maximum of %(limit_value)s months. You entered %(show_value)s months. "
                "To collect more, set up an Instalment Plan."
            ),
        },
        widget=forms.NumberInput(attrs={
            'min': 1,
            'max': ACT_220_MAX_ADVANCE_MONTHS,
            'placeholder': '6',
        })
    )
    lease_term_preset = forms.ChoiceField(
        choices = [('','Select release term...')] + LEASE_TERM_CHOICES,
        required=True,
        label='Lease Term',
        widget=forms.Select(attrs={'id':'id_lease_term_preset'}),
    )
    lease_term_months_custom = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=240,   # 20 years — generous upper bound
        label='Custom lease term (months)',
        widget=forms.NumberInput(attrs={
            'placeholder': 'e.g. 18',
            'id': 'id_lease_term_months_custom',
        }),
        help_text='Enter the number of months if not in the list above.',
    )
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

    lease_term_months = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model  = Property
        fields = [
            'title', 'description', 'property_type', 'furnishing_status',
            'bedrooms', 'bathrooms',
            'address', 'neighbourhood', 'city', 'region', 'latitude', 'longitude',
            'monthly_rent', 'payment_cycle', 'advance_months', 'security_deposit','lease_term_months',
            'amenities', 'available_from','video_file',
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        

    def clean(self):
        """
        Cross-field validation + lease term resolution.
        Note: advance vs lease_term cross-check lives in the model's clean().
        Keeping it there means it's enforced everywhere (admin, API, tests)
        not just in this form.
        """
        cleaned_data = super().clean()
 
        preset = cleaned_data.get('lease_term_preset')
        custom = cleaned_data.get('lease_term_months_custom')
        available_from =cleaned_data.get('available_from')

        from django.utils.timezone import localdate
        today = localdate()   
        if available_from and available_from <= today:
            self.add_error(
                'available_from',
                'Select available from date that is in the future.'
            ) 
 
        if preset not in (None, ''):
            preset = int(preset)
            if preset == 0:
                # "Other" selected — require the custom input
                if not custom:
                    self.add_error(
                        'lease_term_months_custom',
                        'Please enter the lease term in months.'
                    )
                else:
                    cleaned_data['lease_term_months'] = custom
            else:
                cleaned_data['lease_term_months'] = preset
 
        # GPS must be both or neither
        latitude  = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')
        if (latitude is None) != (longitude is None):
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
 
        advance_months = cleaned_data.get('advance_months')
        lease_term_months = cleaned_data.get('lease_term_months')
        if advance_months is not None and lease_term_months is not None:
            if advance_months > lease_term_months:
                self.add_error(
                    'advance_months',
                    'Advance months cannot exceed the total lease term.'
                )
 
        return cleaned_data

    def clean_advance_months(self):
        """
        Act 220 Section 25(5) enforcement.
        This is called automatically by Django during form.is_valid().
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


class PropertyPhotoForm(forms.ModelForm):
    """Simple photo upload form. Used in formset for multi-photo upload."""
    image = forms.ImageField(required=False)
    is_primary = forms.BooleanField(required=False)
    display_order = forms.IntegerField(required=False)

    class Meta:
        model  = PropertyPhoto
        fields = ['image', 'caption', 'is_primary', 'display_order']
        widgets = {
            'caption': forms.TextInput(attrs={'placeholder': 'e.g. Living room, Master bedroom...'}),
            'is_primary': forms.RadioSelect(),
        }

    def clean_photos(self):
        """
        Ensure that at least one photo is marked as primary.
        This is called automatically by Django during formset.is_valid().
        """
        images = self.cleaned_data.get('image', [])
        primary_count = sum(1 for image in images if image.get('is_primary'))
        if primary_count == 0:
            raise ValidationError("Please mark one photo as the primary image.")
        return images

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
