from contextlib import asynccontextmanager, contextmanager

import asyncpg
from fastapi import HTTPException
from sqlalchemy import distinct

from api import db, models


@contextmanager
def safe_db_write():
    try:
        yield
    except asyncpg.exceptions.IntegrityConstraintViolationError as e:
        raise HTTPException(422, str(e))


def get_kwargs(model, data, additional_kwargs, user=None):
    kwargs = data if isinstance(data, dict) else data.dict()
    kwargs.update(additional_kwargs)
    if user:
        kwargs["user_id"] = user.id
    return model.process_kwargs(kwargs)


async def create_object(model, data, user=None, **additional_kwargs):
    kwargs = get_kwargs(model, data, additional_kwargs, user)
    kwargs = model.prepare_create(kwargs)
    await model.validate(**kwargs)
    with safe_db_write():
        result = await model.create(**kwargs)
    return result


async def modify_object(model, data, **additional_kwargs):
    kwargs = get_kwargs(model, data, additional_kwargs)
    kwargs = model.prepare_edit(kwargs)
    await model.validate(**kwargs)
    with safe_db_write():
        await model.update(**kwargs).apply()


async def get_object(model, model_id=None, user=None, custom_query=None, raise_exception=True, load_data=True):
    if custom_query is not None:
        query = custom_query
    else:
        query = model.query.where(model.id == model_id)
        if model != models.User and user:
            query = query.where(model.user_id == user.id)
    item = await query.gino.first()
    if not item:
        if raise_exception:
            raise HTTPException(404, f"{model.__name__} with id {model_id} does not exist!")
        return
    if load_data:
        await item.load_data()
    return item


async def get_scalar(query, func, column):
    return await query.with_only_columns([func(distinct(column))]).order_by(None).gino.scalar() or 0


async def postprocess_func(items):
    for item in items:
        await item.load_data()
    return items


async def paginate_object(model, pagination, user, *args, **kwargs):
    return await pagination.paginate(model, user.id if user else None, postprocess=postprocess_func, *args, **kwargs)


@asynccontextmanager
async def iterate_helper():
    async with db.db.acquire() as conn:
        async with conn.transaction():
            yield


async def get_objects(model, ids):  # TODO: maybe use iterate instead?
    data = await model.query.where(model.id.in_(ids)).gino.all()
    await postprocess_func(data)
    return data
