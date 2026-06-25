import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import logging
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.views.generic import ListView, DetailView
from django.db.models import F

from .models import Property, Amenity, ListingStatus
from .forms import PropertyForm, PropertyPhotoFormSet
from .filters import PropertyFilter
from .services import create_listing, publish_listing, increment_view_count


# ─────────────────────────────────────────────
# LIST VIEW — CBV
# ─────────────────────────────────────────────

class PropertyListView(ListView):
    """
    WHY A CLASS-BASED VIEW HERE?
    ListView is perfect for this use case: paginate a queryset, pass it to a template.
    It handles pagination, queryset fetching, and context building automatically.
    We only override what we need to customise.

    The filter is wired in via get_queryset() — this is the standard pattern
    for combining django-filter with a ListView.
    """
    model               = Property
    template_name       = 'listings/property_list.html'
    context_object_name = 'properties'
    paginate_by         = 12   # 12 cards per page — works for 3 or 4 column grids

    def get_queryset(self):
        """
        select_related('landlord')       — fetches the landlord in the same SQL query
        prefetch_related('photos')       — fetches all photos in a second query, cached
        filter(is_primary=True)          — used in the template via property.primary_photo

        Without select_related/prefetch_related, displaying 12 listing cards would
        generate 12 × 2 = 24 extra DB queries (one per property for landlord, one per
        property for primary photo). This collapses it to 3 queries total.
        """
        qs = (
            Property.objects
            .filter(status=ListingStatus.ACTIVE)
            .select_related('landlord')
            .prefetch_related('photos', 'amenities')
            .order_by('-created_at')
        )
        self.filterset = PropertyFilter(self.request.GET, queryset=qs)
        return self.filterset.qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter']    = self.filterset
        context['amenities'] = Amenity.objects.all()
        context['total_count'] = self.filterset.qs.count()
        return context


# ─────────────────────────────────────────────
# DETAIL VIEW — CBV
# ─────────────────────────────────────────────

class PropertyDetailView(DetailView):
    """
    DetailView handles: fetch object by pk, 404 if not found, render template.
    We override get_object() to increment the view counter and prefetch photos.
    """
    model               = Property
    template_name       = 'listings/property_detail.html'
    context_object_name = 'property'

    def get_object(self, queryset=None):
        obj = (
            Property.objects
            .select_related('landlord', 'landlord__userprofile')
            .prefetch_related('photos', 'amenities')
            .get(pk=self.kwargs['pk'])
        )
        # Increment view count on every page load
        # F expression does atomic SQL increment — no race condition
        Property.objects.filter(pk=obj.pk).update(views_count=F('views_count') + 1)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = self.get_object()
        context['photos']      = prop.photos.order_by('-is_primary', 'display_order')
        context['amenities']   = prop.amenities.all()
        context['can_apply']   = (
            self.request.user.is_authenticated
            and hasattr(self.request.user, 'userprofile')
            and self.request.user.userprofile.role == 'tenant'
            and self.request.user.is_verified
        )
        return context


@login_required
def create_property(request):
    """
    WHY A FUNCTION-BASED VIEW HERE?
    This view handles a formset (photos alongside the main form).
    CBVs can handle formsets but the code becomes contorted.
    FBV is cleaner when there's real logic to orchestrate.

    The pattern:
    - GET: render empty form + empty photo formset
    - POST (valid): call service, redirect to detail page
    - POST (invalid): re-render with errors

    The 'landlord_required' decorator is intentionally not used here so property
    managers can also create listings. The service layer handles ownership.
    """
    # Redirect non-landlords / non-managers
    if not (request.user.is_authenticated and hasattr(request.user, 'userprofile')):
        return redirect('accounts:login')
    role = request.user.userprofile.role
    if role not in ('landlord', 'property_manager'):
        logger = logging.getLogger(__name__)
        logger.warning("create_property access denied for user=%s role=%s", getattr(request.user, 'email', None), role)
        messages.error(request, "Only landlords and property managers can create listings.")
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        photo_parent = Property(landlord=request.user)
        form         = PropertyForm(request.POST, request.FILES)
        photo_formset = PropertyPhotoFormSet(
            request.POST,
            request.FILES,
            instance=photo_parent,
            prefix='photos',
        )

        if form.is_valid() and photo_formset.is_valid():
            try:
                property_obj = create_listing(
                    landlord=request.user,
                    form_data=form.cleaned_data.copy(),
                    photo_formset=photo_formset,
                )
                messages.success(request, f"'{property_obj.title}' created as a draft.")
                return redirect('listings:publish_prompt', pk=property_obj.pk)
            except ValidationError as e:
                if hasattr(e, 'message_dict'):
                    for field, errors in e.message_dict.items():
                        for error in errors:
                            if field in form.fields:
                                form.add_error(field, error)
                            else:
                                form.add_error(None, error)
                else:
                    form.add_error(None, e)
            except Exception as e:
                messages.error(request, f"Error creating listing: {e}")
    else:
        form          = PropertyForm()
        photo_formset = PropertyPhotoFormSet(
            instance=Property(landlord=request.user),
            prefix='photos',
        )

    return render(request, 'listings/create_property.html', {
        'form':           form,
        'photo_formset':  photo_formset,
        'ACT_220_MAX':    6,
    })



@login_required
def publish_prompt(request, pk):
    """
    After creation, landlord lands here.
    Shows a preview and a 'Publish Now' button.
    """
    prop = get_object_or_404(Property, pk=pk, landlord=request.user)

    if request.method == 'POST':
        try:
            publish_listing(prop)
            messages.success(request, f"'{prop.title}' is now live!")
            return redirect('listings:property_detail', pk=prop.pk)
        except ValueError as e:
            messages.error(request, str(e))

    return render(request, 'listings/publish_prompt.html', {'property': prop})



@login_required
def my_listings(request):
    """Landlord's own property portfolio."""
    properties = (
        Property.objects
        .filter(landlord=request.user)
        .prefetch_related('photos')
        .order_by('-created_at')
    )
    return render(request, 'listings/my_listings.html', {'properties': properties})



def map_data(request):
    """
    Returns a JSON array of all active, geolocated properties.
    Leaflet.js fetches this endpoint on page load and drops pins.

    WHY A SEPARATE ENDPOINT?
    Because the map needs coordinates for ALL active properties —
    not just the 12 on the current page. The list view is paginated,
    so we can't get coordinates from the page HTML alone.

    Only returning what Leaflet needs (no full descriptions) keeps
    the response small. A property with 20 fields becomes 6 fields here.

    Green pin = available (status=active)
    Grey pin  = rented (status=rented)
    """
    properties = (
        Property.objects
        .filter(
            status__in=[ListingStatus.ACTIVE, ListingStatus.RENTED],
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .values(
            'id', 'title', 'address', 'monthly_rent', 'advance_months',
            'property_type', 'bedrooms', 'status', 'latitude', 'longitude',
        )
    )

    features = [
        {
            'id':            str(p['id']),
            'title':         p['title'],
            'address':       p['address'],
            'monthly_rent':  float(p['monthly_rent']),
            'advance_months': p['advance_months'],
            'property_type': p['property_type'],
            'bedrooms':      p['bedrooms'],
            'status':        p['status'],
            'lat':           float(p['latitude']),
            'lng':           float(p['longitude']),
            'url':           f"/listings/{p['id']}/",
        }
        for p in properties
    ]

    return JsonResponse({'properties': features})

  