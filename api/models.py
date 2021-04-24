import secrets

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from gino.crud import UpdateRequest
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from api import settings
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

# Abstract class to easily implement many-to-many update behaviour


class ManyToManyUpdateRequest(UpdateRequest):
    KEYS: dict

    def update(self, **kwargs):
        for key in self.KEYS:
            setattr(self, key, kwargs.pop(key, None))
        return super().update(**kwargs)

    async def apply(self):
        for key in self.KEYS:
            key_info = self.KEYS[key]
            data = getattr(self, key)
            if data is None:
                data = []
            else:
                await key_info["table"].delete.where(
                    getattr(key_info["table"], key_info["current_id"]) == self._instance.id
                ).gino.status()
            for i in data:
                kwargs = {key_info["current_id"]: self._instance.id, key_info["related_id"]: i}
                await key_info["table"].create(**kwargs)
            setattr(self._instance, key, data)
        return await super().apply()


class User(db.Model):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_superuser = Column(Boolean(), default=False)
    created = Column(DateTime(True), nullable=False)


class WalletUpdateRequest(UpdateRequest):
    async def apply(self):
        coin = settings.get_coin(self._instance.currency)
        if await coin.validate_key(self._instance.xpub):
            return await super().apply()
        else:
            raise HTTPException(422, "Wallet key invalid")


class Wallet(db.Model):
    __tablename__ = "wallets"
    _update_request_cls = WalletUpdateRequest

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=1000), index=True)
    xpub = Column(String(length=1000), index=True)
    currency = Column(String(length=1000), index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="wallets")
    created = Column(DateTime(True), nullable=False)
    lightning_enabled = Column(Boolean(), default=False)

    @classmethod
    async def create(cls, **kwargs):
        kwargs["currency"] = kwargs.get("currency") or "btc"
        coin = settings.get_coin(kwargs.get("currency"))
        if await coin.validate_key(kwargs.get("xpub")):
            return await super().create(**kwargs)
        else:
            raise HTTPException(422, "Wallet key invalid")


class Notification(db.Model):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="notifications")
    name = Column(String(length=1000), index=True)
    provider = Column(String(length=10000))
    data = Column(JSON)
    created = Column(DateTime(True), nullable=False)


class Template(db.Model):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="templates")
    name = Column(String(length=100000), index=True)
    text = Column(Text())
    created = Column(DateTime(True), nullable=False)
    _unique_constaint = UniqueConstraint("user_id", "name")


class WalletxStore(db.Model):
    __tablename__ = "walletsxstores"

    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="SET NULL"))
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"))


class NotificationxStore(db.Model):
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


class Store(db.Model):
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
    wallets = relationship("Wallet", secondary=WalletxStore)
    notifications = relationship("Notification", secondary=NotificationxStore)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="stores")
    created = Column(DateTime(True), nullable=False)

    def get_setting(self, scheme):
        data = self.checkout_settings or {}
        return scheme(**data)

    async def set_setting(self, scheme):
        json_data = jsonable_encoder(scheme, exclude_unset=True)
        await self.update(checkout_settings=json_data).apply()


class Discount(db.Model):
    __tablename__ = "discounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="discounts")
    name = Column(String(length=1000), index=True)
    percent = Column(Integer)
    description = Column(Text, index=True)
    promocode = Column(Text)
    currencies = Column(String(length=10000), index=True)
    end_date = Column(DateTime(True), nullable=False)
    created = Column(DateTime(True), nullable=False)


class DiscountxProduct(db.Model):
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


class Product(db.Model):
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
    store = relationship("Store", back_populates="products")
    discounts = relationship("Discount", secondary=DiscountxProduct)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="products")
    created = Column(DateTime(True), nullable=False)


class ProductxInvoice(db.Model):
    __tablename__ = "productsxinvoices"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"))
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"))
    count = Column(Integer)


class InvoiceUpdateRequest(ManyToManyUpdateRequest):
    KEYS = {
        "products": {
            "table": ProductxInvoice,
            "current_id": "invoice_id",
            "related_id": "product_id",
        },
    }


class PaymentMethod(db.Model):
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
        data = super().to_dict()
        invoice_id = data.pop("invoice_id")
        invoice = await Invoice.query.where(Invoice.id == invoice_id).gino.first()
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


class Invoice(db.Model):
    __tablename__ = "invoices"
    _update_request_cls = InvoiceUpdateRequest

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
    products = relationship("Product", secondary=ProductxInvoice)
    store_id = Column(
        Integer,
        ForeignKey("stores.id", deferrable=True, initially="DEFERRED", ondelete="SET NULL"),
        index=True,
    )
    order_id = Column(Text)
    store = relationship("Store", back_populates="invoices")
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="invoices")
    created = Column(DateTime(True), nullable=False)

    @classmethod
    async def create(cls, **kwargs):
        from api import crud
        from api.invoices import InvoiceStatus

        store_id = kwargs["store_id"]
        kwargs["status"] = InvoiceStatus.PENDING
        store = await Store.get(store_id)
        await crud.stores.get_store(None, None, store, True)
        if not store.wallets:
            raise HTTPException(422, "No wallet linked")
        if not kwargs.get("user_id"):
            kwargs["user_id"] = store.user_id
        kwargs.pop("products", None)
        return await super().create(**kwargs), store.wallets


class Setting(db.Model):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text)
    value = Column(Text)
    created = Column(DateTime(True), nullable=False)


class Token(db.Model):
    __tablename__ = "tokens"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"), index=True)
    app_id = Column(String)
    redirect_url = Column(String)
    permissions = Column(ARRAY(String))
    created = Column(DateTime(True), nullable=False)

    @classmethod
    async def create(cls, **kwargs):
        kwargs["id"] = secrets.token_urlsafe()
        return await super().create(**kwargs)
