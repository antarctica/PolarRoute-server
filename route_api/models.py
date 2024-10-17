import logging

from celery.result import AsyncResult
from django.db import models
from django.utils import timezone

from polarrouteserver.celery import app

logger = logging.getLogger(__name__)


class Mesh(models.Model):
    id = models.BigAutoField(primary_key=True)
    meshiphi_version = models.CharField(max_length=60, null=True)
    md5 = models.CharField(max_length=64)
    created = models.DateTimeField()
    lat_min = models.FloatField()
    lat_max = models.FloatField()
    lon_min = models.FloatField()
    lon_max = models.FloatField()
    json = models.JSONField(null=True)
    name = models.CharField(max_length=50, null=True)


class Route(models.Model):
    requested = models.DateTimeField(default=timezone.now)
    calculated = models.DateTimeField(null=True)
    file = models.FilePathField(null=True, blank=True)
    info = models.JSONField(null=True)
    mesh = models.ForeignKey(Mesh, on_delete=models.DO_NOTHING, null=True)
    start_lat = models.FloatField()
    start_lon = models.FloatField()
    end_lat = models.FloatField()
    end_lon = models.FloatField()
    json = models.JSONField(null=True)
    json_unsmoothed = models.JSONField(null=True)
    polar_route_version = models.CharField(max_length=60, null=True)


class Job(models.Model):
    "Route or mesh calculation jobs"

    id = models.UUIDField(
        primary_key=True
    )  # use uuids for primary keys to align with celery

    datetime = models.DateTimeField(default=timezone.now)
    route = models.ForeignKey(Route, on_delete=models.DO_NOTHING)

    @property
    def status(self):
        result = AsyncResult(self.id, app=app)
        return result.state
