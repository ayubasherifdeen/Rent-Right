from django import forms

from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ["category", "title", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class MaintenanceResolutionForm(forms.Form):
    """
    resolving a request doesn't edit
    MaintenanceRequest fields directly, it goes through
    services.resolve_request() so the trail row is always written too.
    """

    note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Resolution note (optional)",
    )
