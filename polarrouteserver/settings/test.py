from pathlib import Path

from .base import *

TEST_MESH_PATH = Path("tests", "fixtures", "test_vessel_mesh.json")
TEST_ROUTE_PATH = Path("tests", "fixtures", "test_route.json")
MESH_DIR = Path("tests", "fixtures")
MESH_METADATA_DIR = MESH_DIR

CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "db+sqlite:///results.sqlite"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_STORE_EAGER_RESULT = True
CELERY_TASK_EAGER_PROPAGATES = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}
