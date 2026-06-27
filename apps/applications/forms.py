"""
applications/forms.py

Deliberately thin. The form collects what the tenant types — move-in date
and an optional message. All business-rule validation (role, property status,
duplicate check) lives in services.py, not here.

Why? Forms validate shape and format. Services validate business rules.
Keeping them separate means services stay testable without a POST request,
and forms stay reusable across different surfaces (API, admin, future mobile).
"""

import datetime
from django import forms


class ApplicationForm(forms.Form):
    move_in_date = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'style': (
                    'width:100%; padding:10px 14px; border-radius:8px; '
                    'border:1px solid #E5E0D8; font-family:Inter,sans-serif; '
                    'font-size:14px; color:#1C3829; background:#fff; '
                    'outline:none;'
                ),
            }
        ),
        label='Preferred move-in date',
        help_text='When would you like to move in?',
    )
    message = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'rows': 4,
                'placeholder': 'Introduce yourself to the landlord (optional)…',
                'style': (
                    'width:100%; padding:10px 14px; border-radius:8px; '
                    'border:1px solid #E5E0D8; font-family:Inter,sans-serif; '
                    'font-size:14px; color:#1C3829; background:#fff; '
                    'resize:vertical; outline:none;'
                ),
            }
        ),
        label='Message to landlord',
        required=False,
    )

    def clean_move_in_date(self):
        date = self.cleaned_data['move_in_date']
        if date < datetime.date.today():
            raise forms.ValidationError("Move-in date cannot be in the past.")
        return date
