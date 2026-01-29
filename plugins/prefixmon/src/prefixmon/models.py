from django.db import models


class PluginSettings(models.Model):
    """
    Singleton-настройки плагина (редактируются через UI).
    Храним одну строку (id=1).
    """

    ADDRESS_FAMILY_CHOICES = (
        (4, "IPv4"),
        (6, "IPv6"),
    )

    tag_slug = models.CharField(max_length=100, default="cloud-subnet")
    vrf_name = models.CharField(max_length=100, default="internet")
    address_family = models.PositiveSmallIntegerField(choices=ADDRESS_FAMILY_CHOICES, default=4)
    low_free_threshold = models.PositiveIntegerField(default=10)

    class Meta:
        app_label = "prefixmon"
        verbose_name = "Prefixmon Settings"
        verbose_name_plural = "Prefixmon Settings"
