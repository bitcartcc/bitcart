from api import invoices, models, settings, utils
from api.events import event_handler
from api.ext.configurator import deploy_task
from api.logger import get_logger

logger = get_logger(__name__)


@event_handler.on("expired_task")
async def create_expired_task(event, event_data):
    invoice = await utils.database.get_object(models.Invoice, event_data["id"], raise_exception=False)
    if not invoice:
        return
    await invoices.make_expired_task(invoice)


@event_handler.on("sync_wallet")
async def sync_wallet(event, event_data):
    model = await utils.database.get_object(models.Wallet, event_data["id"], raise_exception=False)
    if not model:
        return
    coin = settings.get_coin(model.currency, model.xpub)
    balance = await coin.balance()
    logger.info(f"Wallet {model.id} synced, balance: {balance['confirmed']}")
    await utils.redis.publish_message(
        f"wallet:{model.id}", {"status": "success", "balance": str(balance["confirmed"])}
    )  # convert for json serialization


event_handler.add_handler("deploy_task", deploy_task)
