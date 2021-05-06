from decimal import Decimal
from typing import List

from bitcart.errors import BaseError as BitcartBaseError
from fastapi import APIRouter, HTTPException, Security

from api import crud, models, schemes, utils

router = APIRouter()


@router.get("/history/{model_id}", response_model=List[schemes.TxResponse])
async def wallet_history(
    model_id: int,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"]),
):
    response: List[schemes.TxResponse] = []
    if model_id == 0:
        for model in await models.Wallet.query.where(models.Wallet.user_id == user.id).gino.all():
            await utils.wallets.get_wallet_history(model, response)
    else:
        model = await utils.database.get_object(models.Wallet, model_id, user)
        await utils.wallets.get_wallet_history(model, response)
    return response


@router.get("/balance", response_model=Decimal)
async def get_balances(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"])):
    return await utils.wallets.get_wallet_balances(user)


@router.get("/{model_id}/balance")
async def get_wallet_balance(
    model_id: int, user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"])
):
    coin = await crud.wallets.get_wallet_coin_by_id(model_id, user)
    return await coin.balance()


@router.get("/{model_id}/checkln")
async def check_wallet_lightning(
    model_id: int,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"]),
):
    try:
        coin = await crud.wallets.get_wallet_coin_by_id(model_id, user)
        return await coin.node_id
    except BitcartBaseError:
        return False


@router.get("/{model_id}/channels")
async def get_wallet_channels(
    model_id: int,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"]),
):
    try:
        coin = await crud.wallets.get_wallet_coin_by_id(model_id, user)
        return await coin.list_channels()
    except BitcartBaseError:
        return []


@router.post("/{model_id}/channels/open")
async def open_wallet_channel(
    model_id: int,
    params: schemes.OpenChannelScheme,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"]),
):
    try:
        coin = await crud.wallets.get_wallet_coin_by_id(model_id, user)
        return await coin.open_channel(params.node_id, params.amount)
    except BitcartBaseError:
        raise HTTPException(400, "Failed to open channel")


@router.post("/{model_id}/channels/close")
async def close_wallet_channel(
    model_id: int,
    params: schemes.CloseChannelScheme,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"]),
):
    try:
        coin = await crud.wallets.get_wallet_coin_by_id(model_id, user)
        return await coin.close_channel(params.channel_point, force=params.force)
    except BitcartBaseError:
        raise HTTPException(400, "Failed to close channel")


@router.post("/{model_id}/lnpay")
async def wallet_lnpay(
    model_id: int,
    params: schemes.LNPayScheme,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["wallet_management"]),
):
    try:
        coin = await crud.wallets.get_wallet_coin_by_id(model_id, user)
        return await coin.lnpay(params.invoice)
    except BitcartBaseError:
        raise HTTPException(400, "Failed to pay the invoice")


utils.routing.ModelView.register(
    router,
    "/",
    models.Wallet,
    schemes.CreateWallet,
    schemes.CreateWallet,
    schemes.Wallet,
    background_tasks_mapping={"post": "sync_wallet"},
    scopes=["wallet_management"],
)
