from urllib.error import URLError

from captcha.fields import ReCaptchaField
from captcha.widgets import ReCaptchaV2Checkbox
from django import forms
from django.core.exceptions import ValidationError


class ResilientReCaptchaField(ReCaptchaField):
    """django-recaptcha only catches HTTPError; an unreachable Google or a timeout must not become a 500."""

    def validate(self, value):
        try:
            super().validate(value)
        except (URLError, TimeoutError, OSError):
            raise ValidationError(self.error_messages['captcha_error'], code='captcha_error')


class CommentCaptchaForm(forms.Form):
    captcha = ResilientReCaptchaField(widget=ReCaptchaV2Checkbox)
