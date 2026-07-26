import json
from urllib import request
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import logging
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.generic import ListView, DetailView
from django.db.models import F
from django.utils import timezone

from apps.applications.models import Application

from .models import Property, Amenity, ListingStatus
from .forms import PropertyForm, PropertyPhotoFormSet
from .filters import PropertyFilter
from .services import (create_listing,
                     publish_listing,
                       increment_view_count,
                       pause_listing,
                       resume_listing,
                       archive_listing,
                       update_listing
)
from apps.accounts.models import ManagedProperty
from apps.accounts.services import (
    can_act_on_property,
    can_create_for_landlord,
    properties_managed_by,
)
#from apps.accounts.notifications import notify_landlord_new_listing


User = get_user_model()

class PropertyListView(ListView):
    # ... unchanged, omitted for brevity ...
    model               = Property
    template_name       = 'listings/property_list.html'
    context_object_name = 'properties'
    paginate_by         = 12

    def get_queryset(self):
        qs = (
            Property.objects
            .filter(status=ListingStatus.LIVE)
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
        context['can_apply'] = (
            self.request.user.is_authenticated
            and hasattr(self.request.user, 'userprofile')
            and self.request.user.userprofile.role == 'tenant'
            and self.request.user.is_verified
        )
        return context


class PropertyDetailView(DetailView):
    # ... unchanged, omitted for brevity ...
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
        Property.objects.filter(pk=obj.pk).update(views_count=F('views_count') + 1)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prop = self.object
        context['photos']      = prop.photos.order_by('-is_primary', 'display_order')
        context['amenities']   = prop.amenities.all()
        context['video']       = prop.video_url
        context['can_apply']   = (
            self.request.user.is_authenticated
            and hasattr(self.request.user, 'userprofile')
            and self.request.user.userprofile.role == 'tenant'
            and self.request.user.is_verified
        )
        context['has_live_application'] = (
            self.request.user.is_authenticated
            and Application.objects.filter(
                tenant=self.request.user,
                rental_property=prop,
                status__in=['pending', 'approved'],
            ).exists()
        )
        return context


@login_required
def create_property(request):
    """
    Landlords create for themselves. Property managers may also create
    a listing on behalf of a landlord they already have an ACTIVE
    ManagedProperty with (see accounts.services.can_create_for_landlord)
    — picked via a `landlord_id` POST field. Fixed from the prior
    version, which set `landlord=request.user` unconditionally: a
    manager submitting this form was becoming the property's landlord
    instead of creating on the real landlord's behalf.
    """
    if not (request.user.is_authenticated and hasattr(request.user, 'userprofile')):
        return redirect('accounts:login')
    role = request.user.userprofile.role
    if role not in ('landlord', 'property_manager'):
        logger = logging.getLogger(__name__)
        logger.warning("create_property access denied for user=%s role=%s", getattr(request.user, 'email', None), role)
        messages.error(request, "Only landlords and property managers can create listings.")
        return redirect('accounts:dashboard')

    is_manager = role == 'property_manager'
    landlord = request.user  # default for the landlord-creates-for-self case

    if is_manager:
        landlord_id = request.POST.get('landlord_id') or request.GET.get('landlord_id')
        if landlord_id:
            landlord = get_object_or_404(User, pk=landlord_id)
            if not can_create_for_landlord(request.user, landlord):
                messages.error(request, "You don't have an active management relationship with this landlord.")
                return redirect('accounts:managed_properties')
        elif request.method == 'POST':
            messages.error(request, "Select which landlord this listing is for.")
            return redirect('listings:create_property')
        # else: GET with no landlord chosen yet — let the template render the picker

    if request.method == 'POST':
        photo_parent = Property(landlord=landlord)
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
                    landlord=landlord,
                    form_data=form.cleaned_data.copy(),
                    photo_formset=photo_formset,
                )
                if is_manager:
                    property_obj.created_by = request.user
                    property_obj.save(update_fields=['created_by'])
                    ManagedProperty.objects.create(
                        property=property_obj,
                        manager=request.user,
                        landlord=landlord,
                        status=ManagedProperty.Status.ACTIVE,
                        responded_at=timezone.now(),
                    )
                    # TODO: notify_landlord_new_listing(property_obj, request.user)
                    # Stubbed — notifications app not built yet (Month 3 per
                    # roadmap). The dashboard badge (unreviewed_manager_listings
                    # in my_listings(), created_by + landlord_reviewed_at on
                    # Property) is the alert mechanism until then. Wire this
                    # call back in once apps.accounts.notifications exists.
                    #notify_landlord_new_listing(property_obj, request.user)
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
            instance=Property(landlord=landlord),
            prefix='photos',
        )

    context = {
        'form':           form,
        'photo_formset':  photo_formset,
        'ACT_220_MAX':    6,
    }
    if is_manager:
        # Landlord picker scoped to landlords this manager already has
        # an ACTIVE link with.
        landlord_ids = ManagedProperty.objects.filter(
            manager=request.user, status=ManagedProperty.Status.ACTIVE,
        ).values_list('landlord_id', flat=True).distinct()
        context['available_landlords'] = User.objects.filter(pk__in=landlord_ids)
        context['selected_landlord'] = landlord if landlord != request.user else None

    return render(request, 'listings/create_property.html', context)


@login_required
def edit_property(request, pk):
    """
    Edit an existing listing — draft or otherwise.

    Mirrors create_property but binds the form/formset to the existing
    instance and routes through update_listing() instead of
    create_listing(). Any status can be edited except archived.
    """
    property_obj = get_object_or_404(Property, pk=pk)
    if not can_act_on_property(request.user, property_obj):
        raise PermissionDenied

    # v11 §5.2 fix: reachable and true exactly when a manager, not the
    # landlord, is editing.
    is_manager_editing = request.user.id != property_obj.landlord_id

    if property_obj.status == ListingStatus.ARCHIVED:
        messages.error(request, "Archived listings can't be edited.")
        return redirect('listings:my_listings')

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES, instance=property_obj)
        photo_formset = PropertyPhotoFormSet(
            request.POST,
            request.FILES,
            instance=property_obj,
            prefix='photos',
        )

        if form.is_valid() and photo_formset.is_valid():
            try:
                update_listing(
                    property_obj=property_obj,
                    form_data=form.cleaned_data.copy(),
                    photo_formset=photo_formset,
                )
                messages.success(request, f"'{property_obj.title}' updated.")
                return redirect('listings:property_detail', pk=property_obj.pk)
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
                messages.error(request, f"Error updating listing: {e}")
    else:
        form = PropertyForm(instance=property_obj)
        photo_formset = PropertyPhotoFormSet(instance=property_obj, prefix='photos')

    return render(request, 'listings/edit_property.html', {
        'form':               form,
        'photo_formset':      photo_formset,
        'ACT_220_MAX':        6,
        'editing':            True,
        'property':           property_obj,
        'is_manager_editing': is_manager_editing,
    })


@login_required
def update_listing_status(request, pk):
    """
    Single endpoint for pause / resume / archive. Fixed: was
    `get_object_or_404(Property, pk=pk, landlord=request.user)`, which
    404'd for any manager acting on a delegated property — the exact
    queryset §4 of the design doc flagged for replacement. Now uses
    can_act_on_property() like edit_property() does.
    """
    property_obj = get_object_or_404(Property, pk=pk)
    if not can_act_on_property(request.user, property_obj):
        raise PermissionDenied

    if request.method != 'POST':
        return redirect('listings:my_listings')

    action_map = {
        'pause':   pause_listing,
        'resume':  resume_listing,
        'archive': archive_listing,
    }
    handler = action_map.get(request.POST.get('action'))
    if handler is None:
        messages.error(request, "Unknown action.")
        return redirect('listings:my_listings')

    try:
        handler(property_obj)
        messages.success(
            request,
            f"'{property_obj.title}' is now {property_obj.get_status_display().lower()}."
        )
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('listings:my_listings')


@login_required
def publish_prompt(request, pk):
    """
    After creation, lands here. Changed from `landlord=request.user` to
    can_act_on_property() so a manager who just created a listing on a
    landlord's behalf (create_property) can reach this step too —
    otherwise the manager would create the draft and immediately 404
    trying to publish it.
    """
    prop = get_object_or_404(Property, pk=pk)
    if not can_act_on_property(request.user, prop):
        raise PermissionDenied

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
    """
    Landlord's own portfolio, now also surfacing:
    - unreviewed_manager_listings: listings a manager created on this
      landlord's behalf that they haven't acknowledged yet (drives the
      "added by your manager" badge — see mark_listing_reviewed)
    - managed_properties: properties this user manages for someone
      else, if they're also a property_manager
    """
    properties = (
        Property.objects
        .filter(landlord=request.user)
        .prefetch_related('photos')
        .order_by('-created_at')
    )

    unreviewed_manager_listings = properties.filter(
        created_by__isnull=False, landlord_reviewed_at__isnull=True,
    ).exclude(created_by=request.user)

    status_filter = request.GET.get('status') or ''
    needs_review = request.GET.get('needs_review') == '1'

    if needs_review:
        properties = properties.filter(pk__in=unreviewed_manager_listings.values_list('pk', flat=True))
    elif status_filter:
        properties = properties.filter(status=status_filter)

    context = {
        'properties': properties,
        'unreviewed_manager_listings': unreviewed_manager_listings,
        'status_filter': status_filter,
        'needs_review': needs_review,
        'listing_statuses': ListingStatus.choices,
    }

    if hasattr(request.user, 'userprofile') and request.user.userprofile.role == 'property_manager':
        context['managed_properties'] = (
            properties_managed_by(request.user)
            .prefetch_related('photos')
            .order_by('-created_at')
        )

    return render(request, 'listings/my_listings.html', context)


@login_required
def mark_listing_reviewed(request, pk):
    """Landlord acknowledges a listing their manager added. Idempotent."""
    property_obj = get_object_or_404(Property, pk=pk, landlord=request.user)
    if property_obj.landlord_reviewed_at is None:
        property_obj.landlord_reviewed_at = timezone.now()
        property_obj.save(update_fields=['landlord_reviewed_at'])
    return redirect('listings:my_listings')


def map_data(request):
    """Unchanged — no manager-related access concerns here, it's a
    public feed of active/rented listings, not scoped to a user."""
    properties = (
        Property.objects
        .filter(
            status__in=[ListingStatus.LIVE, ListingStatus.RENTED],
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