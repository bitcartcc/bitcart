from decimal import Decimal

from api import models, settings, utils


async def get_wallet_history(model, response):
    coin = settings.get_coin(model.currency, model.xpub)
    txes = (await coin.history())["transactions"]
    for i in txes:
        response.append({"date": i["date"], "txid": i["txid"], "amount": i["bc_value"]})


async def get_wallet_balance(coin):
    return (await coin.balance())["confirmed"]


async def get_wallet_balances(user):
    balances = Decimal()
    async with utils.database.iterate_helper():
        async for wallet in models.Wallet.query.where(models.Wallet.user_id == user.id).gino.iterate():
            balances += await get_wallet_balance(settings.get_coin(wallet.currency, wallet.xpub))
    return balances
