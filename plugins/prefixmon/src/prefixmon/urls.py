from django.urls import path

from prefixmon.views import (
    CloudSubnetDetailView,
    CloudSubnetsDiscoveryView,
    CloudSubnetsView,
    PluginSettingsView,
)

urlpatterns = [
    path("cloud-subnets/", CloudSubnetsView.as_view(), name="cloud_subnets"),
    path("cloud-subnets/discovery/", CloudSubnetsDiscoveryView.as_view(), name="cloud_subnets_discovery"),
    path("cloud-subnets/details/", CloudSubnetDetailView.as_view(), name="cloud_subnet_detail"),
    path("settings/", PluginSettingsView.as_view(), name="settings"),
]
