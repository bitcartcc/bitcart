import secrets
from datetime import timedelta

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from gino.crud import UpdateRequest
from sqlalchemy.dialects.postgresql import ARRAY

from api import schemes, settings
from api.db import db
from api.ext.moneyformat import currency_table

# shortcuts
Column = db.Column
Integer = db.Integer
String = db.String
Text = db.Text
Boolean = db.Boolean
Numeric = db.Numeric
DateTime = db.DateTime
Text = db.Text
ForeignKey = db.ForeignKey
JSON = db.JSON
UniqueConstraint = db.UniqueConstraint

# TODO: use bulk insert when asyncpg fix is landed
# See https://github.com/MagicStack/asyncpg/issues/700


async def create_relations(model_id, related_ids, key_info):
    for related_id in related_ids:
        kwargs = {key_info["current_id"]: model_id, key_info["related_id"]: related_id}
        await key_info["table"].create(**kwargs)


async def delete_relations(model_id, key_info):
    await key_info["table"].delete.where(getattr(key_info["table"], key_info["current_id"]) == model_id).gino.status()


class BaseModel(db.Model):
    @property
    def M2M_KEYS(self):
        model_variant = getattr(self, "KEYS", {})
        update_variant = getattr(self._update_request_cls, "KEYS", {})
        return model_variant or update_variant

    async def create_related(self):
        for key in self.M2M_KEYS:
            related_ids = getattr(self, key, [])
            await create_relations(self.id, related_ids, self.M2M_KEYS[key])

    async def add_related(self):
        for key in self.M2M_KEYS:
            key_info = self.M2M_KEYS[key]
            result = (
                await key_info["table"]
                .select(key_info["related_id"])
                .where(getattr(key_info["table"], key_info["current_id"]) == self.id)
                .gino.all()
            )
            setattr(self, key, [obj_id for obj_id, in result if obj_id])

    async def delete_related(self):
        for key_info in self.M2M_KEYS.values():
            await delete_relations(self.id, key_info)

    async def add_fields(self):
        pass

    async def load_data(self):
        await self.add_related()
        await self.add_fields()

    async def _delete(self, *args, **kwargs):
        await self.delete_related()
        return await super()._delete(*args, **kwargs)

    @classmethod
    async def create(cls, **kwargs):
        model = await super().create(**kwargs)
        await model.create_related()
        await model.load_data()
        return model

    @classmethod
    async def validate(cls, **kwargs):
        pass

    @classmethod
    def process_kwargs(cls, kwargs):
        return kwargs

    @classmethod
    def prepare_create(cls, kwargs):
        return kwargs

    @classmethod
    def prepare_edit(cls, kwargs):
        return kwargs


# Abstract class to easily implement many-to-many update behaviour


# NOTE: do NOT edit self, but self._instance instead - it is the target model
class ManyToManyUpdateRequest(UpdateRequest):
    KEYS: dict

    def update(self, **kwargs):
        for key in self.KEYS:
            if key in kwargs:
                setattr(self._instance, key, kwargs.pop(key))
        return super().update(**kwargs)

    async def apply(self):
        for key in self.KEYS:
            key_info = self.KEYS[key]
            data = getattr(self._instance, key, None)
            if data is None:  # pragma: no cover # TODO: maybe simplify
                data = []
            else:
                await delete_relations(self._instance.id, key_info)
            await create_relations(self._instance.id, data, key_info)
            setattr(self._instance, key, data)
        return await super().apply()


class User(BaseModel):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_superuser = Column(Boolean(), default=False)
    created = Column(DateTime(True), nullable=False)

    @classmethod
    def process_kwargs(cls, kwargs):
        from api import utils

        kwargs = super().process_kwargs(kwargs)
        if "password" in kwargs:
            if kwargs["password"] is not None:
                kwargs["hashed_password"] = utils.authorization.get_password_hash(kwargs["password"])
            del kwargs["password"]
        return kwargs


class Wallet(BaseModel):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=1000), index=True)
    xpub = Column(String(length=1000), index=True)
    currency = Column(String(length=1000), index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    created = Column(DateTime(True), nullable=False)
    lightning_enabled = Column(Boolean(), default=False)

    async def add_fields(self):
        from api import utils

        self.balance = await utils.wallets.get_wallet_balance(settings.get_coin(self.currency, self.xpub))

    @classmethod
    async def validate(cls, **kwargs):
        if "currency" in kwargs:
            coin = settings.get_coin(kwargs["currency"])
            if not await coin.validate_key(kwargs.get("xpub")):
                raise HTTPException(422, "Wallet key invalid")


class Notification(BaseModel):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    name = Column(String(length=1000), index=True)
    provider = Column(String(length=10000))
    data = Column(JSON)
    created = Column(DateTime(True), nullable=False)


class Template(BaseModel):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    name = Column(String(length=100000), index=True)
    text = Column(Text())
    created = Column(DateTime(True), nullable=False)
    _unique_constaint = UniqueConstraint("user_id", "name")


class WalletxStore(BaseModel):
    __tablename__ = "walletsxstores"

    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="SET NULL"))
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"))


class NotificationxStore(BaseModel):
    __tablename__ = "notificationsxstores"

    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="SET NULL"))
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"))


class StoreUpdateRequest(ManyToManyUpdateRequest):
    KEYS = {
        "wallets": {
            "table": WalletxStore,
            "current_id": "store_id",
            "related_id": "wallet_id",
        },
        "notifications": {
            "table": NotificationxStore,
            "current_id": "store_id",
            "related_id": "notification_id",
        },
    }


class Store(BaseModel):
    __tablename__ = "stores"
    _update_request_cls = StoreUpdateRequest

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(1000), index=True)
    default_currency = Column(Text)
    email = Column(String(1000), index=True)
    email_host = Column(String(1000))
    email_password = Column(String(1000))
    email_port = Column(Integer)
    email_use_ssl = Column(Boolean)
    email_user = Column(String(1000))
    checkout_settings = Column(JSON)
    templates = Column(JSON)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    created = Column(DateTime(True), nullable=False)

    def get_setting(self, scheme):
        data = self.checkout_settings or {}
        return scheme(**data)

    async def set_setting(self, scheme):
        json_data = jsonable_encoder(scheme, exclude_unset=True)
        await self.update(checkout_settings=json_data).apply()

    async def add_fields(self):
        self.checkout_settings = self.get_setting(schemes.StoreCheckoutSettings)


class Discount(BaseModel):
    __tablename__ = "discounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    name = Column(String(length=1000), index=True)
    percent = Column(Integer)
    description = Column(Text, index=True)
    promocode = Column(Text)
    currencies = Column(String(length=10000), index=True)
    end_date = Column(DateTime(True), nullable=False)
    created = Column(DateTime(True), nullable=False)


class DiscountxProduct(BaseModel):
    __tablename__ = "discountsxproducts"

    discount_id = Column(Integer, ForeignKey("discounts.id", ondelete="SET NULL"))
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"))


class ProductUpdateRequest(ManyToManyUpdateRequest):
    KEYS = {
        "discounts": {
            "table": DiscountxProduct,
            "current_id": "product_id",
            "related_id": "discount_id",
        },
    }


class Product(BaseModel):
    __tablename__ = "products"
    _update_request_cls = ProductUpdateRequest

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=1000), index=True)
    price = Column(Numeric(16, 8), nullable=False)
    quantity = Column(Numeric(16, 8), nullable=False)
    download_url = Column(String(100000))
    category = Column(Text)
    description = Column(Text)
    image = Column(String(100000))
    store_id = Column(
        Integer,
        ForeignKey("stores.id", deferrable=True, initially="DEFERRED", ondelete="SET NULL"),
        index=True,
    )
    status = Column(String(1000), nullable=False)
    templates = Column(JSON)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    created = Column(DateTime(True), nullable=False)


class ProductxInvoice(BaseModel):
    __tablename__ = "productsxinvoices"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"))
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"))
    count = Column(Integer)


class PaymentMethod(BaseModel):
    __tablename__ = "paymentmethods"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"))
    amount = Column(Numeric(16, 8), nullable=False)
    rate = Column(Numeric(16, 8))
    discount = Column(Integer)
    confirmations = Column(Integer, nullable=False)
    recommended_fee = Column(Numeric(16, 8), nullable=False)
    currency = Column(String(length=1000), index=True)
    payment_address = Column(Text, nullable=False)
    payment_url = Column(Text, nullable=False)
    rhash = Column(Text)
    lightning = Column(Boolean(), default=False)
    node_id = Column(Text)

    async def to_dict(self, index: int = None):
        from api import utils

        data = super().to_dict()
        invoice_id = data.pop("invoice_id")
        invoice = await utils.database.get_object(Invoice, invoice_id, load_data=False)  # To avoid recursion
        data["amount"] = currency_table.format_currency(self.currency, self.amount)
        data["rate"] = currency_table.format_currency(invoice.currency, self.rate, fancy=False)
        data["rate_str"] = currency_table.format_currency(invoice.currency, self.rate)
        data["name"] = self.get_name(index)
        return data

    def get_name(self, index: int = None):
        name = f"{self.currency} (⚡)" if self.lightning else self.currency
        if index:
            name += f" ({index})"
        return name.upper()


class Invoice(BaseModel):
    __tablename__ = "invoices"

    KEYS = {
        "products": {
            "table": ProductxInvoice,
            "current_id": "invoice_id",
            "related_id": "product_id",
        },
    }

    id = Column(Integer, primary_key=True, index=True)
    price = Column(Numeric(16, 8), nullable=False)
    currency = Column(Text)
    paid_currency = Column(String(length=1000))
    status = Column(String(1000), nullable=False)
    expiration = Column(Integer)
    buyer_email = Column(String(10000))
    discount = Column(Integer)
    promocode = Column(Text)
    notification_url = Column(Text)
    redirect_url = Column(Text)
    store_id = Column(
        Integer,
        ForeignKey("stores.id", deferrable=True, initially="DEFERRED", ondelete="SET NULL"),
        index=True,
    )
    order_id = Column(Text)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    created = Column(DateTime(True), nullable=False)

    async def add_related(self):
        from api import crud

        self.payments = []
        payment_methods = (
            await PaymentMethod.query.where(PaymentMethod.invoice_id == self.id).order_by(PaymentMethod.id).gino.all()
        )
        for index, method in crud.invoices.get_methods_inds(payment_methods):
            self.payments.append(await method.to_dict(index))
        await super().add_related()

    async def create_related(self):
        # NOTE: we don't call super() here, as the ProductxInvoice creation is delegated to CRUD utils
        pass

    @classmethod
    def prepare_edit(cls, kwargs):
        kwargs = super().prepare_edit(kwargs)
        kwargs.pop("products", None)  # Don't process edit requests for products
        return kwargs

    def add_invoice_expiration(self):
        from api import utils

        self.expiration_seconds = self.expiration * 60
        date = self.created + timedelta(seconds=self.expiration_seconds) - utils.time.now()
        self.time_left = utils.time.time_diff(date)

    async def add_fields(self):
        self.add_invoice_expiration()


class Setting(BaseModel):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text)
    value = Column(Text)
    created = Column(DateTime(True), nullable=False)

    @classmethod
    def prepare_create(cls, kwargs):
        from api import utils

        kwargs = super().prepare_create(kwargs)
        kwargs["created"] = utils.time.now()
        return kwargs


class Token(BaseModel):
    __tablename__ = "tokens"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"), index=True)
    app_id = Column(String)
    redirect_url = Column(String)
    permissions = Column(ARRAY(String))
    created = Column(DateTime(True), nullable=False)

    @classmethod
    def prepare_create(cls, kwargs):
        kwargs = super().prepare_create(kwargs)
        kwargs["id"] = secrets.token_urlsafe()
        return kwargs
