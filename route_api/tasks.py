from datetime import datetime
import gzip
import json
from pathlib import Path
import os

from celery import states
from celery.exceptions import Ignore
from celery.utils.log import get_task_logger
from django.conf import settings
from django.utils import timezone
import numpy as np
import pandas as pd
import polar_route
from polar_route.route_planner import RoutePlanner
from polar_route.utils import extract_geojson_routes
import yaml

from polarrouteserver.celery import app
from .models import Mesh, Route


logger = get_task_logger(__name__)


@app.task(bind=True)
def optimise_route(
    self,
    route_id: int,
    mesh: str | int = settings.MESH_PATH,
) -> dict:
    """
    Use PolarRoute to calculate optimal route from Route database object and mesh.
    Saves Route in database and returns route geojson as dictionary.

    Params:
        route_id(int): id of record in Route database table
        mesh(str|int): path to vessel mesh file or id of record in Mesh database table

    Returns:
        dict: route geojson as dictionary
    """
    route = Route.objects.get(id=route_id)

    if isinstance(mesh, Path | str):
        with open(mesh) as f:
            logger.info(f"Loading mesh file {mesh}")
            vessel_mesh = json.load(f)
    elif isinstance(mesh, int):
        logger.info(f"Loading mesh {mesh} from database.")
        vessel_mesh = Mesh.objects.get(id=mesh).json

    # convert waypoints into pandas dataframe for PolarRoute
    waypoints = pd.DataFrame(
        {
            "Name": ["Start", "End"],
            "Lat": [route.start_lat, route.end_lat],
            "Long": [route.start_lon, route.end_lon],
            "Source": ["X", np.nan],
            "Destination": [np.nan, "X"],
        }
    )

    try:
        # Calculate route
        rp = RoutePlanner(vessel_mesh, settings.TRAVELTIME_CONFIG, waypoints)

        # Calculate optimal dijkstra path between waypoints
        rp.compute_routes()

        # save the initial unsmoothed route
        logger.info("Saving unsmoothed Dijkstra paths.")
        route.json_unsmoothed = extract_geojson_routes(rp.to_json())
        route.calculated = timezone.now()
        route.polar_route_version = polar_route.__version__
        route.save()

        # Smooth the dijkstra routes
        rp.compute_smoothed_routes()

        # Save the smoothed route(s)
        logger.info("Route smoothing complete.")
        extracted_routes = extract_geojson_routes(rp.to_json())

        # Update the database
        route.json = extracted_routes
        route.calculated = timezone.now()
        route.polar_route_version = polar_route.__version__
        route.save()
        return extracted_routes

    except Exception as e:
        self.update_state(state=states.FAILURE)
        route.info = f"{e}"
        route.save()
        raise Ignore()


@app.task(bind=True)
def import_new_meshes(self):
    """Look for new meshes and insert them into the database."""

    # find the latest metadata file
    files = os.listdir(settings.MESH_DIR)
    file_list = [
        os.path.join(settings.MESH_DIR, file)
        for file in files
        if file.startswith("upload_metadata_") and file.endswith(".yaml.gz")
    ]
    if len(file_list) == 0:
        msg = "Upload metadata file not found."
        logger.error(msg)
        raise FileNotFoundError(msg)
    latest_metadata_file = max(file_list, key=os.path.getctime)

    # load in the metadata
    with gzip.open(latest_metadata_file, "rb") as f:
        metadata = yaml.load(f.read(), Loader=yaml.Loader)

    meshes_added = []
    for record in metadata["records"]:
        # we only want the vessel json files
        if not record["filepath"].endswith(".vessel.json"):
            continue

        # extract the filename from the filepath
        mesh_filename = record["filepath"].split("/")[-1]

        # load in the mesh json
        with gzip.open(Path(settings.MESH_DIR, mesh_filename + ".gz"), "rb") as f:
            mesh_json = json.load(f)

        # create an entry in the database
        mesh, created = Mesh.objects.get_or_create(
            md5=record["md5"],
            defaults={
                "name": mesh_filename,
                "created": datetime.strptime(record["created"], "%Y%m%dT%H%M%S"),
                "json": mesh_json,
                "meshiphi_version": record["meshiphi"],
                "lat_min": record["latlong"]["latmin"],
                "lat_max": record["latlong"]["latmax"],
                "lon_min": record["latlong"]["lonmin"],
                "lon_max": record["latlong"]["lonmax"],
            },
        )
        if created:
            logger.info(
                f"Adding new mesh to database: {mesh.id} {mesh.name} {mesh.created}"
            )
            meshes_added.append(
                {"id": mesh.id, "md5": record["md5"], "name": mesh.name}
            )

    return meshes_added
