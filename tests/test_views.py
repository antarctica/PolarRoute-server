import  json, uuid
from unittest.mock import patch, PropertyMock

import celery.states
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIRequestFactory
import pytest

from polarrouteserver.route_api.views import EvaluateRouteView, MeshView, RouteView, RecentRoutesView
from polarrouteserver.route_api.models import Job, Route
from .utils import add_test_mesh_to_db


class TestRouteRequest(TestCase):
    def setUp(self):
        add_test_mesh_to_db()
        self.factory = APIRequestFactory()

    def test_custom_mesh_id(self):
        """Test that non-existent mesh id results in correct error message."""

        data = {
            "start_lat": 0.0,
            "start_lon": 0.0,
            "end_lat": 1.0,
            "end_lon": 1.0,
            "mesh_id": 999
        }

        request = self.factory.post("/api/route/", data=data, format="json")

        response = RouteView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        self.assertIn("Does not exist.", response.data["info"]["error"])

    def test_request_route(self):
        data = {
            "start_lat": 0.0,
            "start_lon": 0.0,
            "end_lat": 1.0,
            "end_lon": 1.0,
        }

        request = self.factory.post("/api/route/", data=data, format="json")

        response = RouteView.as_view()(request)

        self.assertEqual(response.status_code, 202)

        assert f"api/route/{response.data.get('id')}" in response.data.get("status-url")
        assert isinstance(uuid.UUID(response.data.get("id")), uuid.UUID)

    
        # Test that requesting the same route doesn't start a new job.
        # request the same route parameters
        request = self.factory.post("/api/route/", data=data, format="json")
        response2 = RouteView.as_view()(request)
        assert response.data.get('id') == response2.data.get('id')
        assert f"api/route/{response.data.get('id')}" in response2.data.get("status-url")

    def test_evaluate_route(self):
        with open(settings.TEST_ROUTE_PATH) as fp:
            route_json = json.load(fp)

        data=dict(route=route_json)

        request = self.factory.post("/api/evaluate_route/", data=data, format="json")

        response = EvaluateRouteView.as_view()(request)
        self.assertEqual(response.status_code, 200)

pytestmark = pytest.mark.django_db

@pytest.mark.usefixtures("celery_app","celery_worker", "celery_enable_logging")
@pytest.mark.django_db
class TestRouteStatus:
    
    pytestmark = pytest.mark.django_db

    def setUp(self):
        self.factory = APIRequestFactory()
        mesh=add_test_mesh_to_db()
        self.route = Route.objects.create(
            start_lat=1.1, start_lon=1.1, end_lat=2.0, end_lon=2.0, mesh=mesh
        )
        from polarrouteserver.route_api.tasks import optimise_route
        optimise_route(self.route.id)

    def test_get_status_pending(self):

        self.setUp()

        self.job = Job.objects.create(
            id=uuid.uuid1(),
            route=self.route,
        )

        request = self.factory.get(f"/api/route/{self.job.id}")

        response = RouteView.as_view()(request, self.job.id)

        assert response.status_code == 200

        assert response.data.get("status") == "PENDING"

    def test_get_status_complete(self):

        self.setUp()

        with patch(
            "polarrouteserver.route_api.views.AsyncResult.state", new_callable=PropertyMock
        ) as mock_job_status:
            mock_job_status.return_value = celery.states.SUCCESS

            self.job = Job.objects.create(
                id=uuid.uuid1(),
                route=self.route,
            )

            request = self.factory.get(f"/api/route/{self.job.id}")

            response = RouteView.as_view()(request, self.job.id)

            assert response.status_code == 200
            assert response.data.get("status") == "SUCCESS"
            assert isinstance(response.data.get("json_unsmoothed"), list)
            assert isinstance(response.data.get("json"), list)

    def test_request_out_of_mesh(self):

        self.setUp()
        
        with open(settings.TEST_MESH_PATH) as f:
            mesh = json.load(f)
        
        # Request a point that is out of mesh
        lat_min = mesh["config"]["mesh_info"]["region"]["lat_min"]
        lat_max = mesh["config"]["mesh_info"]["region"]["lat_max"]
        lon_min = mesh["config"]["mesh_info"]["region"]["long_min"]
        lon_max = mesh["config"]["mesh_info"]["region"]["long_max"]

        data = {
            "start_lat": lat_min-5,
            "start_lon": lon_min-5,
            "end_lat": abs(lat_max-lat_min)/2,
            "end_lon": abs(lon_max-lon_min)/2,
        }

        # make route request
        request = self.factory.post("/api/route/", data=data, format="json")

        # using try except to ignore deliberate error in celery task in test envrionment
        # in production, celery handles this
        try:
            post_response = RouteView.as_view()(request)
        except AssertionError:
            pass

        assert post_response.status_code == 200
        assert post_response.data["info"]["error"] == "No suitable mesh available."

    
    def test_cancel_route(self):

        self.setUp()

        self.job = Job.objects.create(
            id=uuid.uuid1(),
            route=self.route,
        )

        request = self.factory.delete(f"/api/route/{self.job.id}")

        response = RouteView.as_view()(request, self.job.id)

        assert response.status_code == 202

class TestGetRecentRoutesAndMesh(TestCase):


    def setUp(self):
        self.factory = APIRequestFactory()
        self.mesh = add_test_mesh_to_db()
        self.route1 = self.route = Route.objects.create(
            start_lat=0.0, start_lon=0.0, end_lat=0.0, end_lon=0.0, mesh=self.mesh
        )
        self.route2 = self.route = Route.objects.create(
            start_lat=1.0, start_lon=1.0, end_lat=1.0, end_lon=0.0, mesh=self.mesh
        )
        self.job1 = Job.objects.create(id=uuid.uuid1(), route=self.route1)
        self.job2 = Job.objects.create(id=uuid.uuid1(), route=self.route2)
    
    def test_recent_routes_request(self):

        request = self.factory.get(f"/api/recent_routes/")

        response = RecentRoutesView.as_view()(request)

        assert response.status_code == 200
        assert len(response.data) == 2

    def test_mesh_get(self):

        request = self.factory.get(f"/api/mesh/{self.mesh.id}")

        response = MeshView.as_view()(request, self.mesh.id)

        assert response.status_code == 200
        assert response.data.get("json") is not None
        assert response.data.get("geojson") is not None