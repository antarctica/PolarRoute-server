# Generated by Django 5.1.1 on 2024-11-07 21:21

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("route_api", "0006_alter_route_end_name_alter_route_start_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="route",
            name="end_name",
            field=models.CharField(blank=True, default=None, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="route",
            name="start_name",
            field=models.CharField(blank=True, default=None, max_length=100, null=True),
        ),
    ]
