from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import RegexValidator

from .models import Role, User, UserProfile


phone_validator = [RegexValidator(
    regex=r'^\+?233\d{9}$|^0\d{9}$',
    message='Enter a valid Ghanaian phone number (e.g. 0241234567 or +233241234567).',
)]


class RegistrationForm(forms.Form):
    """
    Single form for both landlord and tenant registration.
    The role field drives which dashboard the user sees post-login.
    """
    first_name   = forms.CharField(max_length=150, label='First name')
    last_name    = forms.CharField(max_length=150, label='Last name')
    email        = forms.EmailField(label='Email address')
    phone_number = forms.CharField(
        max_length=20,
        label='Phone number',
        validators=phone_validator,
        help_text='We will send your verification code here.',
    )
    role = forms.ChoiceField(
        choices=[
            (Role.TENANT,   'Tenant — I am looking for a place to rent'),
            (Role.LANDLORD, 'Landlord — I have a property to rent out'),
            (Role.PROPERTY_MANAGER, 'Property Manager — I manage properties for landlords'),
        ],
        widget=forms.RadioSelect,
        label='I am a…',
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        min_length=8,
    )
    password2 = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned


class LoginForm(AuthenticationForm):
    """
    Override to use email instead of username in the label.
    Django's authenticate() still uses USERNAME_FIELD = 'email' under the hood.
    """
    username = forms.EmailField(
        label='Email address',
        widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'email'}),
    )


class OTPVerificationForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        label='Verification code',
        widget=forms.TextInput(attrs={
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'placeholder': '123456',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code']
        if not code.isdigit():
            raise forms.ValidationError('Enter the 6-digit numeric code from your SMS.')
        return code


class ProfileUpdateForm(forms.ModelForm):
    """Lets users update their own profile details."""
    first_name = forms.CharField(max_length=150)
    last_name  = forms.CharField(max_length=150)
    phone_number = forms.CharField(
        max_length=20,
        validators=[RegexValidator(
        regex=r'^\+?233\d{9}$|^0\d{9}$',
        message='Enter a valid Ghanaian phone number (e.g. 0241234567 or +233241234567).',
)],
        required=False,
    )

    class Meta:
        model  = UserProfile
        fields = ['national_id', 'profile_photo', 'bio']
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        self.fields['first_name'].initial = self.user.first_name
        self.fields['last_name'].initial  = self.user.last_name
        self.fields['phone_number'].initial = self.user.phone_number

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.first_name    = self.cleaned_data['first_name']
        self.user.last_name     = self.cleaned_data['last_name']
        self.user.phone_number  = self.cleaned_data.get('phone_number', '')
        if commit:
            self.user.save(update_fields=['first_name', 'last_name', 'phone_number'])
            profile.save()
        return profile


class PasswordResetRequestForm(forms.Form):
    phone_number = forms.CharField(
        label="Phone number",
        max_length=15,
        validators=phone_validator,
        widget=forms.TextInput(attrs={
            'placeholder': '0244123456',
            'inputmode': 'tel',
        })
    )


class PasswordResetConfirmForm(forms.Form):
    code         = forms.CharField(max_length=6, min_length=6, label='Reset code')
    new_password = forms.CharField(
        label='New password',
        widget=forms.PasswordInput,
        min_length=8,
    )
    confirm_password = forms.CharField(
        label='Confirm new password',
        widget=forms.PasswordInput,
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('new_password') != cleaned.get('confirm_password'):
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned

