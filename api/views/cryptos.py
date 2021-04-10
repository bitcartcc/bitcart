import math
import re
from typing import Optional

from fastapi import APIRouter, HTTPException

from .. import constants, settings

router = APIRouter()


@router.get("/fiatlist")
async def get_fiatlist(query: Optional[str] = None):
    s = None
    for coin in settings.cryptos:
        fiat_list = await settings.cryptos[coin].list_fiat()
        if not s:
            s = set(fiat_list)
        else:
            s = s.intersection(fiat_list)
    if query is not None:
        pattern = re.compile(query, re.IGNORECASE)
        s = [x for x in s if pattern.match(x)]
    return sorted(s)


@router.get("")  # Note: we use empty string there as it's included as subrouter, to avoid redirects
async def get_cryptos():
    return {
        "count": len(settings.cryptos),
        "next": None,
        "previous": None,
        "result": list(settings.cryptos.keys()),
    }


@router.get("/supported")
async def get_supported_cryptos():
    return constants.SUPPORTED_CRYPTOS


@router.get("/rate")
async def rate(currency: str = "btc", fiat_currency: str = "USD"):
    rate = await settings.get_coin(currency).rate(fiat_currency.upper())
    if math.isnan(rate):
        raise HTTPException(422, "Unsupported fiat currency")
    return rate