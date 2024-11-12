from datetime import datetime
import logging

from celery.result import AsyncResult
import rest_framework.status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.reverse import reverse

from polarrouteserver.celery import app
from .models import Job, Route
from .tasks import optimise_route
from .serializers import RouteSerializer
from .utils import route_exists, select_mesh

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

        force_recalculate = data.get("force_recalculate", False)

        mesh = select_mesh(start_lat, start_lon, end_lat, end_lon)

        if mesh is None:
            return Response(
                data={
                    "info": {"error": "No suitable mesh available."},
                    "status": "FAILURE",
                },
                headers={"Content-Type": "application/json"},
                status=rest_framework.status.HTTP_200_OK,
            )
        # TODO Future: calculate an up to date mesh if none available

        existing_route = route_exists(mesh, start_lat, start_lon, end_lat, end_lon)

        if existing_route is not None:
            if not force_recalculate:
                logger.info(f"Existing route found: {existing_route}")
                response_data = RouteSerializer(existing_route).data
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
                return Response(
                    data=response_data,
                    headers={"Content-Type": "application/json"},
                    status=rest_framework.status.HTTP_202_ACCEPTED,
                )
            else:
                logger.info(
                    f"Found existing route(s) but got force_recalculate={force_recalculate}, beginning recalculation."
                )

        # Create route in database
        route = Route.objects.create(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            mesh=mesh,
            start_name=start_name,
            end_name=end_name,
        )

        # Start the task calculation
        task = optimise_route.delay(route.id)

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
        for route in routes_today:
            job = route.job_set.latest("datetime")

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