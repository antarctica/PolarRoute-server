from datetime import datetime
import logging

from celery.result import AsyncResult
from meshiphi.mesh_generation.environment_mesh import EnvironmentMesh
import rest_framework.status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.reverse import reverse

from polarrouteserver.celery import app
from .models import Job, Route, Mesh
from .tasks import optimise_route
from .serializers import RouteSerializer
from .utils import (
    evaluate_route,
    route_exists,
    select_mesh,
    select_mesh_for_route_evaluation,
)

logger = logging.getLogger(__name__)


class LoggingMixin:
    """
    Provides full logging of requests and responses
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("django.request")

    def initial(self, request, *args, **kwargs):
        try:
            self.logger.debug(
                {
                    "request": request.data,
                    "method": request.method,
                    "endpoint": request.path,
                    "user": request.user.username,
                    "ip_address": request.META.get("REMOTE_ADDR"),
                    "user_agent": request.META.get("HTTP_USER_AGENT"),
                }
            )
        except Exception:
            self.logger.exception("Error logging request data")

        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        try:
            self.logger.debug(
                {
                    "response": response.data,
                    "status_code": response.status_code,
                    "user": request.user.username,
                    "ip_address": request.META.get("REMOTE_ADDR"),
                    "user_agent": request.META.get("HTTP_USER_AGENT"),
                }
            )
        except Exception:
            self.logger.exception("Error logging response data")

        return super().finalize_response(request, response, *args, **kwargs)


class RouteView(LoggingMixin, GenericAPIView):
    serializer_class = RouteSerializer

    def post(self, request):
        """Entry point for route requests"""

        logger.info(
            f"{request.method} {request.path} from {request.META.get('REMOTE_ADDR')}: {request.data}"
        )

        data = request.data

        # TODO validate request JSON
        start_lat = data["start_lat"]
        start_lon = data["start_lon"]
        end_lat = data["end_lat"]
        end_lon = data["end_lon"]
        start_name = data.get("start_name", None)
        end_name = data.get("end_name", None)
        custom_mesh_id = data.get("mesh_id", None)
        force_recalculate = data.get("force_recalculate", False)

        if custom_mesh_id:
            try:
                logger.info(f"Got custom mesh id {custom_mesh_id} in request.")
                meshes = [Mesh.objects.get(id=custom_mesh_id)]
            except Mesh.DoesNotExist:
                msg = f"Mesh id {custom_mesh_id} requested. Does not exist."
                logger.info(msg)
                return Response(
                    data={
                        "info": {"error": msg},
                        "status": "FAILURE",
                    },
                    headers={"Content-Type": "application/json"},
                    status=rest_framework.status.HTTP_202_ACCEPTED,
                )
        else:
            meshes = select_mesh(start_lat, start_lon, end_lat, end_lon)

        if meshes is None:
            return Response(
                data={
                    "info": {"error": "No suitable mesh available."},
                    "status": "FAILURE",
                },
                headers={"Content-Type": "application/json"},
                status=rest_framework.status.HTTP_200_OK,
            )

        logger.debug(f"Using meshes: {[mesh.id for mesh in meshes]}")
        # TODO Future: calculate an up to date mesh if none available

        existing_route = route_exists(meshes, start_lat, start_lon, end_lat, end_lon)

        if existing_route is not None:
            if not force_recalculate:
                logger.info(f"Existing route found: {existing_route}")
                response_data = RouteSerializer(existing_route).data
                if existing_route.job_set.count() > 0:
                    existing_job = existing_route.job_set.latest("datetime")

                    response_data.update(
                        {
                            "info": {
                                "info": "Pre-existing route found and returned. To force new calculation, include 'force_recalculate': true in POST request."
                            },
                            "id": str(existing_job.id),
                            "status-url": reverse(
                                "route", args=[existing_job.id], request=request
                            ),
                        }
                    )

                else:
                    response_data.update(
                        {
                            "info": {
                                "error": "Pre-existing route was found but there was an error.\
                                To force new calculation, include 'force_recalculate': true in POST request."
                            }
                        }
                    )
                return Response(
                    data=response_data,
                    headers={"Content-Type": "application/json"},
                    status=rest_framework.status.HTTP_202_ACCEPTED,
                )
            else:
                logger.info(
                    f"Found existing route(s) but got force_recalculate={force_recalculate}, beginning recalculation."
                )

        logger.debug(
            f"Using mesh {meshes[0].id} as primary mesh with {[mesh.id for mesh in meshes[1:]]} as backup."
        )

        # Create route in database
        route = Route.objects.create(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            mesh=meshes[0],
            start_name=start_name,
            end_name=end_name,
        )

        # Start the task calculation
        task = optimise_route.delay(
            route.id, backup_mesh_ids=[mesh.id for mesh in meshes[1:]]
        )

        # Create database record representing the calculation job
        job = Job.objects.create(
            id=task.id,
            route=route,
        )

        # Prepare response data
        data = {
            "id": job.id,
            # url to request status of requested route
            "status-url": reverse("route", args=[job.id], request=request),
        }

        return Response(
            data,
            headers={"Content-Type": "application/json"},
            status=rest_framework.status.HTTP_202_ACCEPTED,
        )

    def get(self, request, id):
        "Return status of route calculation and route itself if complete."

        logger.info(
            f"{request.method} {request.path} from {request.META.get('REMOTE_ADDR')}"
        )

        # update job with latest state
        job = Job.objects.get(id=id)

        # status = job.status
        result = AsyncResult(id=str(id), app=app)
        status = result.state

        data = {"id": str(id), "status": status}

        data.update(RouteSerializer(job.route).data)

        if status == "FAILURE":
            data.update({"error": job.route.info})

        return Response(
            data,
            headers={"Content-Type": "application/json"},
            status=rest_framework.status.HTTP_200_OK,
        )

    def delete(self, request, id):
        """Cancel route calculation"""

        logger.info(
            f"{request.method} {request.path} from {request.META.get('REMOTE_ADDR')}"
        )

        result = AsyncResult(id=str(id), app=app)
        result.revoke()

        return Response(
            {},
            headers={"Content-Type": "application/json"},
            status=rest_framework.status.HTTP_202_ACCEPTED,
        )


class RecentRoutesView(LoggingMixin, GenericAPIView):
    def get(self, request):
        """Get recent routes"""

        logger.info(
            f"{request.method} {request.path} from {request.META.get('REMOTE_ADDR')}"
        )

        # only get today's routes
        routes_today = Route.objects.filter(requested__date=datetime.now().date())
        response_data = []
        logger.debug(f"Found {len(routes_today)} routes today.")
        for route in routes_today:
            logger.debug(f"{route.id}")
            try:
                job = route.job_set.latest("datetime")
            except Job.DoesNotExist:
                logger.debug(f"Job does not exist for route {route.id}")
                continue

            result = AsyncResult(id=str(job.id), app=app)
            status = result.state

            data = {"id": str(job.id), "status": status}

            data.update(RouteSerializer(route).data)

            if status == "FAILURE":
                data.update({"error": route.info})

            response_data.append(data)

        return Response(
            response_data,
            headers={"Content-Type": "application/json"},
            status=rest_framework.status.HTTP_200_OK,
        )


class MeshView(LoggingMixin, GenericAPIView):
    def get(self, request, id):
        logger.info(
            f"{request.method} {request.path} from {request.META.get('REMOTE_ADDR')}"
        )

        data = {}

        try:
            mesh = Mesh.objects.get(id=id)
            data.update(
                dict(
                    id=mesh.id,
                    json=mesh.json,
                    geojson=EnvironmentMesh.load_from_json(mesh.json).to_geojson(),
                )
            )

            status = rest_framework.status.HTTP_200_OK

        except Mesh.DoesNotExist:
            status = rest_framework.status.HTTP_204_NO_CONTENT

        return Response(
            data,
            headers={"Content-Type": "application/json"},
            status=status,
        )


class EvaluateRouteView(LoggingMixin, GenericAPIView):
    def post(self, request):
        data = request.data
        route_json = data.get("route", None)
        custom_mesh_id = data.get("custom_mesh_id", None)

        if custom_mesh_id:
            try:
                mesh = Mesh.objects.get(id=custom_mesh_id)
                meshes = [mesh]
            except Mesh.DoesNotExist:
                return Response(
                    {"error": f"Mesh with id {custom_mesh_id} not found."},
                    headers={"Content-Type": "application/json"},
                    status=rest_framework.status.HTTP_204_NO_CONTENT,
                )
        else:
            meshes = select_mesh_for_route_evaluation(route_json)

        result_dict = evaluate_route(route_json, meshes[0])

        return Response(
            result_dict,
            headers={"Content-Type": "application/json"},
            status=rest_framework.status.HTTP_200_OK,
        )
