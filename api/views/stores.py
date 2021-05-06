from fastapi import APIRouter, Security

from api import crud, models, schemes, utils

router = APIRouter()


@router.get("/{model_id}/ping")
async def ping_email(
    model_id: int,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["store_management"]),
):
    model = await utils.database.get_object(models.Store, model_id, user)
    return utils.email.check_ping(
        model.email_host,
        model.email_port,
        model.email_user,
        model.email_password,
        model.email,
        model.email_use_ssl,
    )


@router.patch("/{model_id}/checkout_settings", response_model=schemes.Store)
async def set_store_checkout_settings(
    model_id: int,
    settings: schemes.StoreCheckoutSettings,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["store_management"]),
):
    model = await utils.database.get_object(models.Store, model_id, user)
    await model.set_setting(settings)
    return model


utils.routing.ModelView.register(
    router,
    "/",
    models.Store,
    schemes.Store,
    schemes.CreateStore,
    custom_methods={
        "get_one": crud.stores.get_store,
    },
    get_one_model=None,
    get_one_auth=False,
    scopes=["store_management"],
)
