from api import models, settings, utils


async def get_wallet_coin_by_id(model_id: int, user):
    wallet = await utils.database.get_object(models.Wallet, model_id, user)
    return settings.get_coin(wallet.currency, wallet.xpub)
