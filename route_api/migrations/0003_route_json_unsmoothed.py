# Generated by Django 5.1.1 on 2024-10-15 11:13

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("route_api", "0002_rename_status_mesh_info_rename_status_route_info"),
    ]

    operations = [
        migrations.AddField(
            model_name="route",
            name="json_unsmoothed",
            field=models.JSONField(null=True),
        ),
    ]