from fastapi import APIRouter

from api import models, schemes, utils

router = APIRouter()

utils.routing.ModelView.register(
    router,
    "/",
    models.Discount,
    schemes.Discount,
    schemes.CreateDiscount,
    scopes=["discount_management"],
)
