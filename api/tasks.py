import asyncio

from bitcart_async import BTC

from . import models, schemes, settings

RPC_URL = settings.RPC_URL
RPC_USER = settings.RPC_USER
RPC_PASS = settings.RPC_PASS


async def poll_updates(obj: models.Invoice, xpub: str):
    address = obj.bitcoin_address
    if not address:
        return
    btc_instance = BTC(RPC_URL, xpub=xpub,
                       rpc_user=RPC_USER, rpc_pass=RPC_PASS)
    while True:
        invoice_data = await btc_instance.getrequest(address)
        if invoice_data["status"] != "Pending":
            if invoice_data["status"] == "Unknown":
                status = "invalid"
            if invoice_data["status"] == "Expired":
                status = "expired"
            if invoice_data["status"] == "Paid":
                status = "complete"
            await obj.update(status=status).apply()
            return
        await asyncio.sleep(1)


async def sync_wallet(model: models.Wallet):
    try:
        balance = await BTC(
            RPC_URL,
            xpub=model.xpub,
            rpc_user=RPC_USER,
            rpc_pass=RPC_PASS).balance()
        await model.update(balance=balance["confirmed"]).apply()
    except ValueError:  # wallet loading error
        await model.delete()