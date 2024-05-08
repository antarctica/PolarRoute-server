# Generated by Django 5.0.6 on 2024-05-08 14:57

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Mesh',
            fields=[
                ('id', models.IntegerField(primary_key=True, serialize=False)),
                ('requested', models.DateTimeField(null=True)),
                ('calculated', models.DateTimeField(null=True)),
                ('file', models.FilePathField(blank=True, null=True)),
                ('status', models.TextField(null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Route',
            fields=[
                ('id', models.IntegerField(primary_key=True, serialize=False)),
                ('requested', models.DateTimeField(null=True)),
                ('calculated', models.DateTimeField(null=True)),
                ('file', models.FilePathField(blank=True, null=True)),
                ('status', models.TextField(null=True)),
                ('waypoint_start', models.JSONField(blank=True)),
                ('waypoint_end', models.JSONField(blank=True)),
                ('mesh', models.ForeignKey(null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='route_api.mesh')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
