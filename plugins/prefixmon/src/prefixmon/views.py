from django.apps import apps
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from prefixmon.forms import PluginSettingsForm
from prefixmon.models import PluginSettings


def _get_plugin_setting(key, default):
    cfg = getattr(settings, "PLUGINS_CONFIG", {}).get("prefixmon", {}) or {}
    return cfg.get(key, default)


def _get_db_settings():
    defaults = {
        "tag_slug": _get_plugin_setting("tag_slug", "cloud-subnet"),
        "vrf_name": _get_plugin_setting("vrf_name", "internet"),
        "address_family": int(_get_plugin_setting("address_family", 4)),
        "low_free_threshold": int(_get_plugin_setting("low_free_threshold", 10)),
    }
    obj, _ = PluginSettings.objects.get_or_create(id=1, defaults=defaults)
    return obj


def _get_prefix_stats(prefix_obj):
    size = getattr(prefix_obj.prefix, "size", 0) or 0
    is_pool = getattr(prefix_obj, "is_pool", False)
    version = getattr(prefix_obj.prefix, "version", 4)

    if version == 4 and not is_pool:
        if size == 1:
            total_usable = 1
        elif size == 2:
            total_usable = 2
        else:
            total_usable = max(0, size - 2)
    else:
        total_usable = size

    try:
        util_pct = prefix_obj.get_utilization()
        if util_pct is not None and size:
            used = int(round(size * float(util_pct) / 100))
            free = max(0, total_usable - used)
        else:
            used = 0
            free = total_usable
        util_pct = float(util_pct) if util_pct is not None else 0
    except Exception:
        used = 0
        free = total_usable
        util_pct = 0

    return total_usable, used, free, round(util_pct, 1)


def _get_cloud_prefixes_queryset():
    Prefix = apps.get_model("ipam", "Prefix")
    VRF = apps.get_model("ipam", "VRF")
    s = _get_db_settings()
    vrf = VRF.objects.filter(name=s.vrf_name).first()
    if not vrf:
        return Prefix.objects.none()
    return (
        Prefix.objects.filter(tags__slug=s.tag_slug)
        .filter(prefix__family=s.address_family)
        .filter(vrf=vrf)
        .distinct()
    )


class CloudSubnetsView(LoginRequiredMixin, TemplateView):
    template_name = "prefixmon/cloud_subnets.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        s = _get_db_settings()
        qs = _get_cloud_prefixes_queryset()
        low_free_threshold = int(s.low_free_threshold)

        prefix_rows = []
        for prefix in qs:
            total_usable, used, free, util_pct = _get_prefix_stats(prefix)
            prefix_rows.append(
                {
                    "prefix": prefix,
                    "total_addresses": total_usable,
                    "free_addresses": free,
                    "utilization_percent": util_pct,
                    "is_low_free": free <= low_free_threshold,
                }
            )
        context["prefix_rows"] = prefix_rows
        context["low_free_threshold"] = low_free_threshold
        context["settings"] = s
        return context


class CloudSubnetsDiscoveryView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        qs = _get_cloud_prefixes_queryset()
        low_free_threshold = int(_get_db_settings().low_free_threshold)
        data = []
        for prefix in qs:
            total_usable, used, free, util_pct = _get_prefix_stats(prefix)
            data.append(
                {
                    "{#PREFIX}": str(prefix.prefix),
                    "{#VRF}": str(prefix.vrf) if getattr(prefix, "vrf", None) else "",
                    "{#SCOPE}": str(prefix.scope) if getattr(prefix, "scope", None) else "",
                    "{#TOTAL}": total_usable,
                    "{#USED}": used,
                    "{#FREE}": free,
                    "{#UTIL}": util_pct,
                    "{#LOW_FREE}": int(free <= low_free_threshold),
                }
            )
        return JsonResponse({"data": data})


class CloudSubnetDetailView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        prefix_param = request.GET.get("prefix") or request.GET.get("free")
        if not prefix_param:
            return JsonResponse({"data": []})

        prefix_param = prefix_param.strip().replace("\\/", "/")
        low_free_threshold = int(_get_db_settings().low_free_threshold)
        target = _get_cloud_prefixes_queryset().filter(prefix=prefix_param).first()
        if target is None:
            return JsonResponse({"data": []})

        total_usable, used, free, util_pct = _get_prefix_stats(target)
        row = {
            "{#PREFIX}": str(target.prefix),
            "{#VRF}": str(target.vrf) if getattr(target, "vrf", None) else "",
            "{#SCOPE}": str(target.scope) if getattr(target, "scope", None) else "",
            "{#TOTAL}": total_usable,
            "{#USED}": used,
            "{#FREE}": free,
            "{#UTIL}": util_pct,
            "{#LOW_FREE}": int(free <= low_free_threshold),
        }
        return JsonResponse({"data": [row]})


class PluginSettingsView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponse("Forbidden", status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        s = _get_db_settings()
        form = PluginSettingsForm(instance=s)
        return render(request, "prefixmon/settings.html", {"form": form})

    def post(self, request, *args, **kwargs):
        s = _get_db_settings()
        form = PluginSettingsForm(request.POST, instance=s)
        if form.is_valid():
            form.save()
            return redirect(reverse("plugins:prefixmon:settings"))
        return render(request, "prefixmon/settings.html", {"form": form})
