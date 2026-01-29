from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PluginSettings",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tag_slug", models.CharField(default="cloud-subnet", max_length=100)),
                ("vrf_name", models.CharField(default="internet", max_length=100)),
                (
                    "address_family",
                    models.PositiveSmallIntegerField(choices=[(4, "IPv4"), (6, "IPv6")], default=4),
                ),
                ("low_free_threshold", models.PositiveIntegerField(default=10)),
            ],
            options={
                "verbose_name": "Prefixmon Settings",
                "verbose_name_plural": "Prefixmon Settings",
            },
        ),
    ]
