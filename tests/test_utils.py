import datetime
import hashlib
import json

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from haversine import inverse_haversine, Unit, Direction
import pytest

from polarrouteserver.route_api.models import Mesh, Route
from polarrouteserver.route_api.utils import evaluate_route, route_exists, select_mesh, select_mesh_for_route_evaluation
from .utils import add_test_mesh_to_db

class TestRouteExists(TestCase):
    "Test function for checking for existing routes"

    def setUp(self):
        "Create a route in the test database"

        self.mesh = add_test_mesh_to_db()

        self.start_lat = 64.16
        self.start_lon = -21.99
        self.end_lat = 78.24
        self.end_lon = 15.61

        self.route = Route.objects.create(
            calculated=timezone.now(),
            start_lat=self.start_lat,
            start_lon=self.start_lon,
            end_lat=self.end_lat,
            end_lon=self.end_lon,
            mesh=self.mesh
        )

    def test_route_exists(self):
        "Test case where exact requested route exists"

        route = route_exists(
            self.mesh,
            start_lat=self.start_lat,
            start_lon=self.start_lon,
            end_lat=self.end_lat,
            end_lon=self.end_lon,
        )
        assert route == self.route

    def test_no_route_exists(self):
        "Test case where no similar route exists"

        route = route_exists(
            self.mesh,
            start_lat=0,
            start_lon=0,
            end_lat=0,
            end_lon=0,
        )
        assert route is None

    def test_exact_route_returned(self):
        """Test exact route returned if other nearby routes exist"""

        # use inverse haversine method to create points at specified distance from start and end points
        in_tolerance_start = inverse_haversine(
            (self.start_lat, self.start_lon),
            0.9 * settings.WAYPOINT_DISTANCE_TOLERANCE,
            Direction.NORTH,
            unit=Unit.NAUTICAL_MILES,
        )
        in_tolerance_end = inverse_haversine(
            (self.end_lat, self.end_lon),
            0.9 * settings.WAYPOINT_DISTANCE_TOLERANCE,
            Direction.NORTH,
            unit=Unit.NAUTICAL_MILES,
        )

        # create another nearby route
        Route.objects.create(
            calculated=timezone.now(),
            start_lat=in_tolerance_start[0],
            start_lon=in_tolerance_start[1],
            end_lat=in_tolerance_end[0],
            end_lon=in_tolerance_end[1],
            mesh=self.mesh
        )

        route = route_exists(
            self.mesh,
            start_lat=self.start_lat,
            start_lon=self.start_lon,
            end_lat=self.end_lat,
            end_lon=self.end_lon,
        )
        assert route == self.route

        ### Test that closest of multiple routes is the one returned if no exact route is found
        # remove the exact route
        route.delete()

        in_tolerance_start = inverse_haversine(
            (self.start_lat, self.start_lon),
            0.8 * settings.WAYPOINT_DISTANCE_TOLERANCE,
            Direction.NORTH,
            unit=Unit.NAUTICAL_MILES,
        )
        in_tolerance_end = inverse_haversine(
            (self.end_lat, self.end_lon),
            0.8 * settings.WAYPOINT_DISTANCE_TOLERANCE,
            Direction.NORTH,
            unit=Unit.NAUTICAL_MILES,
        )

        # create another nearby route
        closest_route = Route.objects.create(
            calculated=timezone.now(),
            start_lat=in_tolerance_start[0],
            start_lon=in_tolerance_start[1],
            end_lat=in_tolerance_end[0],
            end_lon=in_tolerance_end[1],
            mesh=self.mesh
        )

        # search for route with no exact match
        route = route_exists(
            self.mesh,
            start_lat=self.start_lat,
            start_lon=self.start_lon,
            end_lat=self.end_lat,
            end_lon=self.end_lon,
        )
        assert route == closest_route

class TestSelectMesh(TestCase):

    def setUp(self):
        # create some meshes in the database

        self.southern_mesh = Mesh.objects.create(
            name = "southern_test_mesh.vessel.json",
            md5 = hashlib.md5("dummy_hashable_string".encode('utf-8')).hexdigest(),
            meshiphi_version = "2.1.13",
            valid_date_start = timezone.now().date() - datetime.timedelta(days=3),
            valid_date_end = timezone.now().date(),
            created = datetime.datetime.now(datetime.timezone.utc),
            lat_min =  -80.0,
            lat_max =  -40.0,
            lon_min = -110.0,
            lon_max =   -5.0
        )

    def test_select_mesh(self):
        assert select_mesh(
            start_lat = -60,
            start_lon = -55,
            end_lat   = -80,
            end_lon   = -110
        ) == [self.southern_mesh]

        # test that when no containing mesh available, the result is None
        assert select_mesh(
            start_lat = -90,
            start_lon = -55,
            end_lat   = -80,
            end_lon   = -110
        ) == None

    def test_smallest_mesh(self):
        self.smallest_mesh = Mesh.objects.create(
            name = "smallest_test_mesh.vessel.json",
            md5 = hashlib.md5("dummy_hashable_string".encode('utf-8')).hexdigest(),
            meshiphi_version = "2.1.13",
            valid_date_start = timezone.now().date() - datetime.timedelta(days=3),
            valid_date_end = timezone.now().date(),
            created = datetime.datetime.now(datetime.timezone.utc),
            lat_min =  -80.0,
            lat_max =  -56.0,
            lon_min = -115.0,
            lon_max =    0.0,
        )

        self.smaller_mesh = Mesh.objects.create(
            name = "smaller_test_mesh.vessel.json",
            md5 = hashlib.md5("dummy_hashable_string".encode('utf-8')).hexdigest(),
            meshiphi_version = "2.1.13",
            valid_date_start = timezone.now().date() - datetime.timedelta(days=3),
            valid_date_end = timezone.now().date(),
            created = datetime.datetime.now(datetime.timezone.utc),
            lat_min =  -85.0,
            lat_max =  -60.0,
            lon_min = -117.0,
            lon_max =    0.0,
        )

        # check that we've actually made a smaller mesh
        assert self.smaller_mesh.size < self.southern_mesh.size
        assert self.smallest_mesh.size < self.smaller_mesh.size

        assert select_mesh(
            start_lat = -60,
            start_lon = -55,
            end_lat   = -80,
            end_lon   = -110
        ) == [self.smallest_mesh, self.smaller_mesh, self.southern_mesh]

    def test_select_mesh_for_route_evaluation(self):

        self.mesh_for_evaluation = add_test_mesh_to_db()

        with open(settings.TEST_ROUTE_PATH) as fp:
            self.route_json = json.load(fp)

        assert select_mesh_for_route_evaluation(self.route_json) == [self.mesh_for_evaluation]

@pytest.mark.django_db
def test_evaluate_route():
    add_test_mesh_to_db()

    with open(settings.TEST_ROUTE_PATH) as fp:
        route_json = json.load(fp)

    mesh = select_mesh_for_route_evaluation(route_json)

    assert mesh is not None

    result = evaluate_route(route_json, mesh[0])
    assert isinstance(result, dict)