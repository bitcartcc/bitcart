from fastapi import APIRouter

from api import models, schemes, settings, utils
from api.utils.common import prepare_compliant_response

router = APIRouter()


@router.get("/list")
async def get_notifications():
    return prepare_compliant_response(list(settings.notifiers.keys()))


@router.get("/schema")
async def get_notifications_schema():
    return settings.notifiers


utils.routing.ModelView.register(
    router,
    "/",
    models.Notification,
    schemes.Notification,
    schemes.CreateNotification,
    scopes=["notification_management"],
)
