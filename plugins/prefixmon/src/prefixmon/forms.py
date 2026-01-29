from django import forms
from django.apps import apps

from prefixmon.models import PluginSettings


class PluginSettingsForm(forms.ModelForm):
    # Показываем выпадающие списки, но сохраняем в модель строки/число
    tag_slug = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "form-select"}))
    vrf_name = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        Tag = apps.get_model("extras", "Tag")
        VRF = apps.get_model("ipam", "VRF")

        tag_choices = [(t.slug, f"{t.name} ({t.slug})") for t in Tag.objects.order_by("name")]
        vrf_choices = [(v.name, v.name) for v in VRF.objects.order_by("name")]

        if tag_choices:
            self.fields["tag_slug"].choices = tag_choices
        else:
            self.fields["tag_slug"] = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))

        if vrf_choices:
            self.fields["vrf_name"].choices = vrf_choices
        else:
            self.fields["vrf_name"] = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))

    class Meta:
        model = PluginSettings
        fields = ["tag_slug", "vrf_name", "address_family", "low_free_threshold"]
        widgets = {
            "address_family": forms.Select(attrs={"class": "form-select"}),
            "low_free_threshold": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }
