from fastapi import APIRouter, Security
from sqlalchemy import distinct, func, select

from api import crud, db, models, schemes, utils

router = APIRouter()


@router.get("/stats")
async def get_stats(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["full_control"])):
    queries = []
    output_formats = []
    for index, orm_model in enumerate(utils.routing.ModelView.crud_models):
        label = orm_model.__name__.lower() + "s"  # based on naming convention, i.e. User->users
        query = select([func.count(distinct(orm_model.id))])
        if orm_model != models.User:
            query = query.where(orm_model.user_id == user.id)
        queries.append(query.label(label))
        output_formats.append((label, index))
    result = await db.db.first(select(queries))
    response = {key: result[ind] for key, ind in output_formats}
    response.pop("users", None)
    response["balance"] = await utils.wallets.get_wallet_balances(user)
    return response


@router.get("/me", response_model=schemes.DisplayUser)
async def get_me(user: models.User = Security(utils.authorization.AuthDependency())):
    return user


utils.routing.ModelView.register(
    router,
    "/",
    models.User,
    schemes.User,
    schemes.CreateUser,
    display_model=schemes.DisplayUser,
    custom_methods={"post": crud.users.create_user},
    post_auth=False,
    scopes={
        "get_all": ["server_management"],
        "get_count": ["server_management"],
        "get_one": ["server_management"],
        "post": [],
        "patch": ["server_management"],
        "put": ["server_management"],
        "delete": ["server_management"],
    },
)
