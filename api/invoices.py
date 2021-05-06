import asyncio

from sqlalchemy import or_, select

from api import constants, models, settings, utils
from api.ext.moneyformat import currency_table
from api.logger import get_logger
from api.utils.logging import log_errors

logger = get_logger(__name__)

STATUS_MAPPING = {
    0: "Pending",
    3: "complete",
    2: "invalid",
    1: "expired",
    4: "In progress",
    5: "Failed",
    "Paid": "complete",
    "Pending": "pending",
    "Unknown": "invalid",
    "Expired": "expired",
}


class InvoiceStatus:
    PENDING = "pending"
    PAID = "paid"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    INVALID = "invalid"
    COMPLETE = "complete"


def get_pending_invoice_statuses():
    return or_(
        models.Invoice.status == InvoiceStatus.PENDING,
        models.Invoice.status == InvoiceStatus.PAID,
        models.Invoice.status == InvoiceStatus.CONFIRMED,
    )


def get_pending_invoices_query(currency):
    return (
        select(
            [
                models.PaymentMethod,
                models.Invoice,
                models.Wallet.xpub,
            ]
        )
        .where(models.PaymentMethod.invoice_id == models.Invoice.id)
        .where(get_pending_invoice_statuses())
        .where(models.PaymentMethod.currency == currency.lower())
        .where(models.WalletxStore.wallet_id == models.Wallet.id)
        .where(models.WalletxStore.store_id == models.Invoice.store_id)
        .where(models.Wallet.currency == models.PaymentMethod.currency)
        .order_by(models.PaymentMethod.id)
    )


async def iterate_pending_invoices(currency):
    with log_errors():  # connection issues
        async with utils.database.iterate_helper():
            async for method, invoice, xpub in get_pending_invoices_query(currency).gino.load(
                (models.PaymentMethod, models.Invoice, models.Wallet.xpub)
            ).iterate():
                await invoice.load_data()
                yield method, invoice, xpub


async def make_expired_task(invoice):
    invoice.add_invoice_expiration()  # to ensure it is the most recent one
    left = invoice.time_left + 1  # to ensure it's already expired at that moment
    if left > 0:
        await asyncio.sleep(left)
    try:
        invoice = await utils.database.get_object(models.Invoice, invoice.id)  # refresh data to get new status
    except Exception:
        return  # invoice deleted meantime
    if invoice.status == InvoiceStatus.PENDING:  # to ensure there are no duplicate notifications
        await update_status(invoice, InvoiceStatus.EXPIRED)


async def mark_invoice_paid(invoice, method, xpub, electrum_status):
    electrum_status = convert_status(electrum_status)
    if invoice.status == InvoiceStatus.PENDING and electrum_status == InvoiceStatus.COMPLETE:
        if method.lightning:
            await update_status(invoice, InvoiceStatus.COMPLETE, method)
        else:
            await update_status(invoice, InvoiceStatus.PAID, method)
            await update_confirmations(
                invoice, method, await get_confirmations(method, xpub)
            )  # to trigger complete for stores accepting 0-conf
    return True


async def new_payment_handler(instance, event, address, status, status_str):
    with log_errors():
        data = (
            await get_pending_invoices_query(instance.coin_name.lower())
            .where(or_(models.PaymentMethod.payment_address == address, models.PaymentMethod.rhash == address))
            .gino.load((models.PaymentMethod, models.Invoice, models.Wallet.xpub))
            .first()
        )
        if not data:  # received payment but no matching invoice
            return
        method, invoice, xpub = data
        await invoice.load_data()
        await mark_invoice_paid(invoice, method, xpub, status)


async def update_confirmations(invoice, method, confirmations):
    await method.update(confirmations=confirmations).apply()
    store = await utils.database.get_object(models.Store, invoice.store_id)
    status = invoice.status
    if confirmations >= 1:
        status = InvoiceStatus.CONFIRMED
    if confirmations >= store.checkout_settings.transaction_speed:
        status = InvoiceStatus.COMPLETE
    await update_status(invoice, status, method)


async def get_confirmations(method, xpub):
    coin = settings.get_coin(method.currency, xpub)
    invoice_data = await coin.get_request(method.payment_address)
    return min(
        constants.MAX_CONFIRMATION_WATCH, invoice_data.get("confirmations", 0)
    )  # don't store arbitrary number of confirmations


async def new_block_handler(instance, event, height):
    await asyncio.sleep(3)  # wait for electrum to update invoices
    async for method, invoice, xpub in iterate_pending_invoices(instance.coin_name.lower()):
        with log_errors():  # issues processing one item
            if (
                invoice.status not in [InvoiceStatus.PAID, InvoiceStatus.CONFIRMED]
                or method.get_name() != invoice.paid_currency
                or method.lightning
            ):
                continue
            await invoice.load_data()
            confirmations = await get_confirmations(method, xpub)
            if confirmations != method.confirmations:
                await update_confirmations(invoice, method, confirmations)


async def invoice_notification(invoice: models.Invoice, status: str):
    await utils.notifications.send_ipn(invoice, status)
    if status == InvoiceStatus.COMPLETE:
        logger.info(f"Invoice {invoice.id} complete, sending notifications...")
        store = await utils.database.get_object(models.Store, invoice.store_id)
        await utils.notifications.notify(store, await utils.templates.get_notify_template(store, invoice))
        if invoice.products:
            if utils.email.check_ping(
                store.email_host,
                store.email_port,
                store.email_user,
                store.email_password,
                store.email,
                store.email_use_ssl,
            ):
                messages = []
                products = await utils.database.get_objects(models.Product, invoice.products)
                for product in products:
                    product.price = currency_table.normalize(
                        invoice.currency, product.price
                    )  # to be formatted correctly in emails
                    relation = (
                        await models.ProductxInvoice.query.where(models.ProductxInvoice.invoice_id == invoice.id)
                        .where(models.ProductxInvoice.product_id == product.id)
                        .gino.first()
                    )
                    quantity = relation.count
                    product_template = await utils.templates.get_product_template(store, product, quantity)
                    messages.append(product_template)
                    logger.debug(
                        f"Invoice {invoice.id} email notification: rendered product template for product {product.id}:\n"
                        f"{product_template}"
                    )
                store_template = await utils.templates.get_store_template(store, messages)
                logger.debug(f"Invoice {invoice.id} email notification: rendered final template:\n{store_template}")
                utils.email.send_mail(
                    store,
                    invoice.buyer_email,
                    store_template,
                )


def convert_status(status):
    if isinstance(status, int):
        status = STATUS_MAPPING[status]
    elif isinstance(status, str) and status in STATUS_MAPPING:
        status = STATUS_MAPPING[status]
    if not status:
        status = InvoiceStatus.EXPIRED
    return status


async def update_status(invoice, status, method=None):
    status = convert_status(status)
    if invoice.status != status and status != InvoiceStatus.PENDING and invoice.status != InvoiceStatus.COMPLETE:
        log_text = f"Updating status of invoice {invoice.id}"
        if method:
            full_method_name = method.get_name()
            if not invoice.paid_currency and status in [InvoiceStatus.PAID, InvoiceStatus.COMPLETE]:
                await invoice.update(paid_currency=full_method_name, discount=method.discount).apply()
            log_text += f" with payment method {full_method_name}"
        logger.info(f"{log_text} to {status}")
        await invoice.update(status=status).apply()
        await utils.redis.publish_message(f"invoice:{invoice.id}", {"status": status})
        if not settings.TEST:
            await invoice_notification(invoice, status)
        return True


async def create_expired_tasks():
    with log_errors():
        async with utils.database.iterate_helper():
            async for invoice in models.Invoice.query.where(get_pending_invoice_statuses()).gino.iterate():
                with log_errors():
                    asyncio.ensure_future(make_expired_task(invoice))


async def check_pending(currency):
    async for method, invoice, xpub in iterate_pending_invoices(currency):
        with log_errors():  # issues processing one item
            if invoice.status == InvoiceStatus.EXPIRED:
                continue
            coin = settings.get_coin(method.currency, xpub)
            if method.lightning:
                invoice_data = await coin.get_invoice(method.rhash)
            else:
                invoice_data = await coin.get_request(method.payment_address)
            await mark_invoice_paid(invoice, method, xpub, invoice_data["status"])
