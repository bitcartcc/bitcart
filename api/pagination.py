import asyncio
from typing import Callable, Optional, Union

import asyncpg
from fastapi import Query
from sqlalchemy import Text, func, or_, text
from starlette.requests import Request

from api import models, utils
from api.db import db


class Pagination:
    default_offset = 0
    default_limit = 5
    max_offset = None
    max_limit = 1000

    def __init__(
        self,
        request: Request,
        offset: int = Query(default=default_offset, ge=0, le=max_offset),
        limit: int = Query(default=default_limit, ge=-1, le=max_limit),
        query: str = Query(default=""),
        multiple: bool = Query(default=False),
        sort: str = Query(default=""),
        desc: bool = Query(default=True),
    ):
        self.request = request
        self.offset = offset
        self.limit = limit
        self.query = query
        self.multiple = multiple
        if self.multiple:
            self.query = self.query.replace(",", "|")
        self.sort = sort
        self.desc = desc
        self.desc_s = "desc" if desc else ""
        self.model = None

    def get_previous_url(self) -> Union[None, str]:
        if self.offset <= 0:
            return None
        if self.offset - self.limit <= 0:
            return str(self.request.url.remove_query_params(keys=["offset"]))
        return str(self.request.url.include_query_params(limit=self.limit, offset=self.offset - self.limit))

    def get_next_url(self, count) -> Union[None, str]:
        if self.offset + self.limit >= count or self.limit == -1:
            return None
        return str(self.request.url.include_query_params(limit=self.limit, offset=self.offset + self.limit))

    async def get_count(self, query) -> int:
        return await utils.database.get_scalar(query, db.func.count, self.model.id)

    async def get_list(self, query) -> list:
        if not self.sort:
            self.sort = "created"
            self.desc_s = "desc"
        if self.limit != -1:
            query = query.limit(self.limit)
        query = query.order_by(text(f"{self.sort} {self.desc_s}"))
        try:
            return await query.offset(self.offset).gino.all()
        except asyncpg.exceptions.UndefinedColumnError:
            return []

    def search(self):
        if not self.query:
            return []
        return or_(
            *[
                getattr(self.model, m.key)
                .cast(Text)
                .op("~*")(f"{self.query}")  # NOTE: not cross-db, postgres case-insensitive regex
                for m in self.model.__table__.columns
            ]
        )

    async def paginate(
        self,
        model,
        user_id=None,
        store_id=None,
        category=None,
        min_price=None,
        max_price=None,
        sale=False,
        postprocess: Optional[Callable] = None,
        app_id=None,
        redirect_url=None,
        permissions=None,
        count_only=False,
    ) -> Union[dict, int]:
        query = self.get_queryset(
            model, user_id, sale, store_id, category, min_price, max_price, app_id, redirect_url, permissions
        )
        if count_only:
            return await self.get_count(query)
        count, data = await asyncio.gather(self.get_count(query), self.get_list(query.group_by(model.id)))
        if postprocess:
            data = await postprocess(data)
        return {
            "count": count,
            "next": self.get_next_url(count),
            "previous": self.get_previous_url(),
            "result": data,
        }

    def get_base_query(self, model):
        self.model = model
        query = model.query
        queries = self.search()
        query = query.where(queries) if queries != [] else query  # sqlalchemy core requires explicit checks
        return query

    def get_queryset(self, model, user_id, sale, store_id, category, min_price, max_price, app_id, redirect_url, permissions):
        query = self.get_base_query(model)
        if user_id is not None and model != models.User:
            query = query.where(model.user_id == user_id)
        if model == models.Product:
            query = self._filter_in_product(query, store_id, category, min_price, max_price, sale)
        elif model == models.Token:
            query = self._filter_in_token(query, app_id, redirect_url, permissions)
        return query

    @staticmethod
    def _filter_in_product(query, store_id, category, min_price, max_price, sale):
        if sale:
            query = (
                query.select_from(models.Product.join(models.DiscountxProduct).join(models.Discount))
                .having(func.count(models.DiscountxProduct.product_id) > 0)
                .where(models.Discount.end_date > utils.time.now())
            )
        if store_id is not None:
            query = query.where(models.Product.store_id == store_id)
        if category and category != "all":
            query = query.where(models.Product.category == category)
        if min_price is not None:
            query = query.where(models.Product.price >= min_price)
        if max_price is not None:
            query = query.where(models.Product.price <= max_price)
        return query

    @staticmethod
    def _filter_in_token(query, app_id, redirect_url, permissions):
        if app_id is not None:
            query = query.where(models.Token.app_id == app_id)
        if redirect_url is not None:
            query = query.where(models.Token.redirect_url == redirect_url)
        if permissions is not None:
            query = query.where(models.Token.permissions.contains(permissions))
        return query
