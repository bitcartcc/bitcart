import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Security, UploadFile
from fastapi.security import SecurityScopes
from pydantic import ValidationError
from starlette.requests import Request

from api import db, models, pagination, schemes, utils

router = APIRouter()


def parse_data(data, scheme):
    data = json.loads(data)
    try:
        data = scheme(**data)
    except ValidationError as e:
        raise HTTPException(422, e.errors())
    return data


async def create_product(
    data: str = Form(...),
    image: UploadFile = File(None),
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["product_management"]),
):
    data = parse_data(data, schemes.CreateProduct)
    data.image = utils.files.get_image_filename(image)
    with utils.database.safe_db_write():
        obj = await utils.database.create_object(models.Product, data, user)
        if image:  # TODO: remove when object id gets generated from python
            filename = utils.files.get_image_filename(image, False, obj)
            await obj.update(image=filename).apply()
            await utils.files.save_image(filename, image)
    return obj


async def get_product_noauth(model_id: int, store: Optional[int] = None):
    query = models.Product.query.where(models.Product.id == model_id)
    if store is not None:
        query = query.where(models.Product.store_id == store)
    item = await utils.database.get_object(models.Product, model_id, custom_query=query)
    return item


async def process_edit_product(model_id, data, image, user, patch=True):
    data = parse_data(data, schemes.Product)
    item = await utils.database.get_object(models.Product, model_id, user)
    if image:
        filename = utils.files.get_image_filename(image, False, item)
        data.image = filename
        await utils.files.save_image(filename, image)
    else:
        utils.files.safe_remove(item.image)
        data.image = None
    data = data.dict(exclude_unset=True) if patch else data.dict()
    await utils.database.modify_object(item, data)
    return item


async def patch_product(
    model_id: int,
    data: str = Form(...),
    image: UploadFile = File(None),
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["product_management"]),
):
    return await process_edit_product(model_id, data, image, user)


async def put_product(
    model_id: int,
    data: str = Form(...),
    image: UploadFile = File(None),
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["product_management"]),
):
    return await process_edit_product(model_id, data, image, user, patch=False)


async def delete_product(item: schemes.Product, user: schemes.User) -> schemes.Product:
    utils.files.safe_remove(item.image)
    await item.delete()
    return item


async def get_products(
    request: Request,
    pagination: pagination.Pagination = Depends(),
    store: Optional[int] = None,
    category: Optional[str] = "",
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    sale: Optional[bool] = False,
):
    try:
        user = await utils.authorization.AuthDependency()(request, SecurityScopes(["product_management"]))
    except HTTPException:
        if store is None:
            raise
        user = None
    return await utils.database.paginate_object(models.Product, pagination, user, store, category, min_price, max_price, sale)


@router.get("/maxprice")
async def get_max_product_price(store: int):
    return await utils.database.get_scalar(
        models.Product.query.where(models.Product.store_id == store), db.db.func.max, models.Product.price
    )


async def products_count(
    request: Request,
    pagination: pagination.Pagination = Depends(),
    store: Optional[int] = None,
    category: Optional[str] = "",
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    sale: Optional[bool] = False,
):
    user = None
    if store is None:
        user = await utils.authorization.AuthDependency()(request, SecurityScopes(["product_management"]))
    return await utils.database.paginate_object(
        models.Product, pagination, user, store, category, min_price, max_price, sale, count_only=True
    )


@router.get("/categories")
async def categories(store: int):
    dataset = {
        category
        for category, in await models.Product.select("category").where(models.Product.store_id == store).gino.all()
        if category
    }
    dataset.discard("all")
    return ["all"] + sorted(dataset)


utils.routing.ModelView.register(
    router,
    "/",
    models.Product,
    schemes.Product,
    schemes.CreateProduct,
    custom_methods={"delete": delete_product},
    request_handlers={
        "get": get_products,
        "get_one": get_product_noauth,
        "post": create_product,
        "patch": patch_product,
        "put": put_product,
        "get_count": products_count,
    },
    scopes=["product_management"],
)
