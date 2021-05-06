from fastapi import HTTPException

from api import models, schemes, utils
from api.db import db


async def user_count():
    return await db.func.count(models.User.id).gino.scalar()


async def create_user(user: schemes.CreateUser, auth_user: schemes.User):
    register_off = (await utils.policies.get_setting(schemes.Policy)).disable_registration
    if register_off and (not auth_user or not auth_user.is_superuser):
        raise HTTPException(422, "Registration disabled")
    is_superuser = False
    if auth_user is None:
        count = await user_count()
        is_superuser = True if count == 0 else False
    elif auth_user and auth_user.is_superuser:
        is_superuser = user.is_superuser
    d = user.dict()
    d["is_superuser"] = is_superuser
    return await utils.database.create_object(models.User, d)
