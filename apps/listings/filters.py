import django_filters
from django import forms
from .models import Property, Amenity, PropertyType, FurnishingStatus


class PropertyFilter(django_filters.FilterSet):
    """
    django-filter is the cleanest way to handle multi-field search in Django.

    Instead of writing: ?type=apartment&min_rent=500&max_rent=2000&bedrooms=2
    and manually parsing each query param in the view, we declare a FilterSet.
    The library builds the queryset automatically.

    CONVENTION:
    - `field_name` = the model field to filter on
    - `lookup_expr` = how to compare ('gte' = ≥, 'lte' = ≤, 'icontains' = case-insensitive contains)
    - `label` = what the user sees in the form / API docs
    """

    property_type = django_filters.ChoiceFilter(
        choices=PropertyType.choices,
        empty_label='Any type',
        label='Property Type',
    )

    min_rent = django_filters.NumberFilter(
        field_name='monthly_rent',
        lookup_expr='gte',
        label='Min monthly rent (GHC)',
        widget=forms.NumberInput(attrs={'placeholder': '0'}),
    )

    max_rent = django_filters.NumberFilter(
        field_name='monthly_rent',
        lookup_expr='lte',
        label='Max monthly rent (GHC)',
        widget=forms.NumberInput(attrs={'placeholder': '5000'}),
    )

    bedrooms = django_filters.NumberFilter(
        field_name='bedrooms',
        lookup_expr='gte',
        label='Min bedrooms',
        widget=forms.NumberInput(attrs={'min': 0, 'placeholder': '0'}),
    )

    furnishing = django_filters.ChoiceFilter(
        field_name='furnishing_status',
        choices=FurnishingStatus.choices,
        empty_label='Any furnishing',
        label='Furnishing',
    )

    city = django_filters.CharFilter(
        lookup_expr='icontains',
        label='City',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Accra, Kumasi'}),
    )

    neighbourhood = django_filters.CharFilter(
        lookup_expr='icontains',
        label='Neighbourhood',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. East Legon, Osu'}),
    )

    amenities = django_filters.ModelMultipleChoiceFilter(
        queryset=Amenity.objects.all(),
        widget=forms.CheckboxSelectMultiple(),
        label='Amenities',
        conjoined=True,  # AND logic: must have ALL selected amenities (not any)
    )

    class Meta:
        model  = Property
        fields = [
            'property_type', 'min_rent', 'max_rent',
            'bedrooms', 'furnishing', 'city', 'neighbourhood', 'amenities',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active listings to tenants
        self.queryset = self.queryset.filter(status='active')
