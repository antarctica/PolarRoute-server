# Generated by Django 5.1.1 on 2024-10-17 15:19

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("route_api", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="route",
            name="info",
            field=models.JSONField(null=True),
        ),
    ]
