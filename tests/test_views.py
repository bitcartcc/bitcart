import asyncio
import json as json_module
import os
import platform
from decimal import Decimal
from typing import Dict, List, Union

import pytest
from bitcart import BTC
from starlette.testclient import TestClient

from api import constants, invoices, models, settings, templates, utils
from api.constants import DOCKER_REPO_URL
from api.ext import tor as tor_ext

TEST_XPUB = "tpubDD5MNJWw35y3eoJA7m3kFWsyX5SaUgx2Y3AaGwFk1pjYsHvpgDwRhrStRbCGad8dYzZCkLCvbGKfPuBiG7BabswmLofb7c2yfQFhjqSjaGi"
LIMITED_USER_DATA = {
    "email": "testauthlimited@example.com",
    "password": "test12345",
}
SCRIPT_SETTINGS = {
    "mode": "Manual",
    "domain_settings": {"domain": "bitcartcc.com", "https": True},
    "coins": {"btc": {"network": "testnet", "lightning": True}},
    "additional_services": ["tor"],
    "advanced_settings": {"additional_components": ["custom"]},
}
FALLBACK_SERVER_SETTINGS = {
    "domain_settings": {"domain": "", "https": True},
    "coins": {},
    "additional_services": [],
    "advanced_settings": {
        "installation_pack": "all",
        "bitcart_docker_repository": "",
        "additional_components": [],
    },
}


class DummyInstance:
    coin_name = "BTC"


def get_future_return_value(return_val):
    future = asyncio.Future()
    future.set_result(return_val)
    minor_ver = int(platform.python_version_tuple()[1])
    return future if minor_ver < 8 or asyncio.get_event_loop().is_running() else return_val


class ViewTestMixin:
    """Base class for all modelview tests, as they mostly don't differ

    You must set some parameters unset in this class for it to work in your subclass
    """

    status_mapping: Dict[Union[str, bool], int] = {
        "good": 200,
        "bad": 422,
        "not found": 404,
        True: 200,
        False: 422,
    }
    invoice: bool = False
    json_encoding: bool = True
    auth: bool = False
    name: str  # name used in endpoints
    tests: Dict[str, List[dict]]
    """dict with keys corresponding to testing function, each key is a list of
    dicts, where each dict must have status key, return_data key if status
    is good, obj_id if function requires it, and data if function sends it
    """

    def process_resp(self, resp, test, get_all=False):
        to_check = self.status_mapping[test["status"]]
        assert resp.status_code == to_check
        if to_check == 200:
            data = resp.json()
            if get_all:
                assert data["count"] == len(test["return_data"])
                assert not data["previous"]
                assert not data["next"]
                assert isinstance(data["result"], list)
                data = data["result"]
            if isinstance(data, list):
                for d in data:
                    if isinstance(d, dict):
                        if self.invoice:
                            assert d.get("payments")
                        assert "created" in d
                        d.pop("created", None)
                        d.pop("end_date", None)
                        d.pop("payments", None)
                        d.pop("time_left", None)
            elif isinstance(data, dict):
                if self.invoice:
                    assert data.get("payments")
                assert "created" in data
                data.pop("created", None)
                data.pop("end_date", None)
                data.pop("payments", None)
                data.pop("time_left", None)
            assert data == test["return_data"]

    def send_request(self, url, client, json={}, method="get", token=""):
        headers = {}
        if self.auth:
            headers["Authorization"] = f"Bearer {token}"
        kwargs = {"headers": headers}
        if self.json_encoding:
            kwargs["json"] = json
        else:
            kwargs["data"] = {"data": json_module.dumps(json)}
        return client.request(method, url, **kwargs)

    def test_create(self, client: TestClient, token: str):
        for test in self.tests["create"]:
            resp = self.send_request(f"/{self.name}", client, json=test["data"], method="post", token=token)
            self.process_resp(resp, test)

    def test_get_all(self, client: TestClient, token: str):  # all responses are sorted in creation order
        for test in self.tests["get_all"]:
            resp = self.send_request(f"/{self.name}", client, token=token)
            self.process_resp(resp, test, True)

    def test_get_count(self, client: TestClient, token: str):
        for test in self.tests["get_count"]:
            resp = self.send_request(f"/{self.name}/count", client, token=token)
            self.process_resp(resp, test)

    def test_get_one(self, client: TestClient, token: str):
        for test in self.tests["get_one"]:
            resp = self.send_request(f"/{self.name}/{test['obj_id']}", client, token=token)
            self.process_resp(resp, test)

    def test_partial_update(self, client: TestClient, token: str):
        for test in self.tests["partial_update"]:
            resp = self.send_request(
                f"/{self.name}/{test['obj_id']}",
                client,
                json=test["data"],
                method="patch",
                token=token,
            )
            self.process_resp(resp, test)

    def test_full_update(self, client: TestClient, token: str):
        for test in self.tests["full_update"]:
            resp = self.send_request(
                f"/{self.name}/{test['obj_id']}",
                client,
                json=test["data"],
                method="put",
                token=token,
            )
            self.process_resp(resp, test)

    def test_delete(self, client: TestClient, token: str):
        for test in self.tests["delete"]:
            resp = self.send_request(f"/{self.name}/{test['obj_id']}", client, method="delete", token=token)
            self.process_resp(resp, test)


class TestUsers(ViewTestMixin):
    name = "users"
    auth = True
    tests = json_module.loads(open("tests/fixtures/users.json").read())


class TestDiscounts(ViewTestMixin):
    name = "discounts"
    auth = True
    tests = json_module.loads(open("tests/fixtures/discounts.json").read())


class TestNotifications(ViewTestMixin):
    name = "notifications"
    auth = True
    tests = json_module.loads(open("tests/fixtures/notifications.json").read())


class TestTemplates(ViewTestMixin):
    name = "templates"
    auth = True
    tests = json_module.loads(open("tests/fixtures/templates.json").read())


class TestWallets(ViewTestMixin):
    name = "wallets"
    auth = True
    tests = json_module.loads(open("tests/fixtures/wallets.json").read())


class TestStores(ViewTestMixin):
    name = "stores"
    auth = True
    tests = json_module.loads(open("tests/fixtures/stores.json").read())


class TestProducts(ViewTestMixin):
    name = "products"
    json_encoding = False
    auth = True
    tests = json_module.loads(open("tests/fixtures/products.json").read())


class TestInvoices(ViewTestMixin):
    name = "invoices"
    auth = True
    invoice = True
    tests = json_module.loads(open("tests/fixtures/invoices.json").read())


def test_docs_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200


def test_rate(client: TestClient):
    resp = client.get("/cryptos/rate")
    data = resp.json()
    assert resp.status_code == 200
    assert isinstance(data, float)
    assert data > 0
    assert client.get("/cryptos/rate?fiat_currency=eur").status_code == 200
    assert client.get("/cryptos/rate?fiat_currency=EUR").status_code == 200
    assert client.get("/cryptos/rate?fiat_currency=test").status_code == 422


def test_wallet_history(client: TestClient, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/wallets/history/1", headers=headers).status_code == 404
    assert client.get("/wallets/history/4", headers=headers).status_code == 404
    resp = client.get("/wallets/history/2", headers=headers)
    client.post("/wallets", json={"name": "test7", "xpub": TEST_XPUB}, headers=headers).json()
    assert resp.status_code == 200
    assert resp.json() == []
    resp1 = client.get("/wallets/history/4", headers=headers)
    assert resp1.status_code == 200
    data2 = resp1.json()
    assert len(data2) == 1
    assert data2[0]["amount"] == "0.01"
    assert data2[0]["txid"] == "ee4f0c4405f9ba10443958f5c6f6d4552a69a80f3ec3bed1c3d4c98d65abe8f3"
    resp2 = client.get("/wallets/history/0", headers=headers)
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


def test_create_token(client: TestClient):
    assert client.post("/token", json={"email": "test44@example.com", "password": 123456}).status_code == 401
    assert client.post("/token", json={"email": "test1@example.com", "password": 123456}).status_code == 401
    resp = client.post("/token", json={"email": "test44@example.com", "password": 12345})
    assert resp.status_code == 200
    j = resp.json()
    assert j.get("access_token")
    assert j["token_type"] == "bearer"


def test_noauth(client: TestClient):
    assert client.get("/users").status_code == 401
    assert client.get("/wallets").status_code == 401
    assert client.get("/stores").status_code == 401
    assert client.get("/products").status_code == 401
    assert client.get("/invoices").status_code == 401
    assert (
        client.post(
            "/discounts", json={"name": "test_no_auth", "percent": 20, "end_date": "2020-01-01 21:19:34.503627"}
        ).status_code
        == 401
    )
    assert client.get("/products?&store=2").status_code == 200
    assert client.post("/users", json={"email": "noauth@example.com", "password": "noauth"}).status_code == 200
    assert client.post("/token", json={"email": "noauth@example.com", "password": "noauth"}).status_code == 200


def test_superuseronly(client: TestClient, token: str):
    token_usual = client.post("/token", json={"email": "noauth@example.com", "password": "noauth"}).json()["access_token"]
    assert client.get("/users", headers={"Authorization": f"Bearer {token_usual}"}).status_code == 403
    assert client.get("/users", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_users_me(client: TestClient, token: str):
    assert client.get("/users/me").status_code == 401
    resp = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    j = resp.json()
    assert j.items() > {"is_superuser": True, "id": 1, "email": "testauth@example.com"}.items()
    assert "created" in j


def test_wallets_balance(client: TestClient, token: str):
    assert client.get("/wallets/balance").status_code == 401
    resp = client.get("/wallets/balance", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == 0.01


def test_fiatlist(client: TestClient):
    resp = client.get("/cryptos/fiatlist")
    assert resp.status_code == 200
    j1 = resp.json()
    assert isinstance(j1, list)
    assert "BTC" in j1
    assert "USD" in j1
    resp2 = client.get("/cryptos/fiatlist?query=b")
    assert resp2.status_code == 200
    j2 = resp2.json()
    assert isinstance(j2, list)
    assert "BTC" in j2
    resp3 = client.get("/cryptos/fiatlist?query=U")
    assert resp3.status_code == 200
    j3 = resp3.json()
    assert isinstance(j3, list)
    assert "USD" in j3


def test_fiatlist_multi_coins(client: TestClient, mocker):
    class DummyCoin:
        async def list_fiat(self):
            ...

    btc, ltc = DummyCoin(), DummyCoin()
    orig_cryptos = settings.cryptos
    settings.cryptos = {"BTC": btc, "LTC": ltc}
    mocker.patch.object(btc, "list_fiat", return_value=get_future_return_value(["USD", "RMB", "JPY"]))
    mocker.patch.object(ltc, "list_fiat", return_value=get_future_return_value(["USD", "RUA", "AUD"]))
    resp = client.get("/cryptos/fiatlist")
    assert resp.json() == ["USD"]
    settings.cryptos = orig_cryptos


async def check_ws_response(ws):
    data = await ws.receive_json()
    assert data == {"status": "paid"}
    data = await ws.receive_json()
    assert data == {"status": "complete"}


async def check_ws_response_complete(ws):
    data = await ws.receive_json()
    assert data == {"status": "complete"}


async def check_ws_response2(ws):
    data = await ws.receive_json()
    assert data == {"status": "success", "balance": "0.01"}


def test_ping_email(client: TestClient, token: str):
    resp0 = client.get("/stores/55/ping")
    assert resp0.status_code == 401
    resp = client.get("/stores/55/ping", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404
    resp1 = client.get("/stores/2/ping", headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200
    assert not resp1.json()


def test_user_stats(client: TestClient, token: str):
    resp = client.get("/users/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {
        "wallets": 3,
        "stores": 2,
        "discounts": 1,
        "products": 1,
        "invoices": 0,
        "notifications": 1,
        "templates": 1,
        "balance": 0.01,
    }


def test_categories(client: TestClient):
    assert client.get("/products/categories").status_code == 422
    resp = client.get("/products/categories?store=1")
    resp2 = client.get("/products/categories?store=2")
    assert resp.status_code == 200
    assert resp.json() == ["all"]
    assert resp2.status_code == 200
    assert resp2.json() == ["all", "Test"]


def check_token(result):
    assert isinstance(result, dict)
    assert result["user_id"] == 1
    assert result["app_id"] == "1"
    assert result["redirect_url"] == "test.com"
    assert result["permissions"] == ["full_control"]


def test_token(client: TestClient, token: str):
    assert client.get("/token").status_code == 401
    resp = client.get("/token", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    j = resp.json()
    assert j["count"] == 1
    assert not j["previous"]
    assert not j["next"]
    result = j["result"]
    assert isinstance(result, list)
    assert len(result) == 1
    result = result[0]
    check_token(result)


def test_token_current(client: TestClient, token: str):
    assert client.get("/token/current").status_code == 401
    resp = client.get("/token/current", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    j = resp.json()
    check_token(j)
    assert j["id"] == token


def test_token_count(client: TestClient, token: str):
    assert client.get("/token/count").status_code == 401
    resp = client.get("/token/count", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == 1


def test_patch_token(client: TestClient, token: str):
    assert client.patch(f"/token/{token}").status_code == 401
    assert (
        client.patch(
            "/token/{token}",
            json={"redirect_url": "test"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 404
    )
    resp = client.patch(
        f"/token/{token}",
        json={"redirect_url": "google.com:443"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    j = resp.json()
    assert j["redirect_url"] == "google.com:443"
    assert j["id"] == token


def test_create_tokens(client: TestClient, token: str):
    assert client.post("/token").status_code == 401
    assert client.post("/token", json={"email": "test1", "password": "test2"}).status_code == 401
    assert client.post("/token", json={"email": "testauth@example.com", "password": "test12345"}).status_code == 200
    assert client.post("/token", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    # Selective permissions control is done by client, not by server
    resp = client.post(
        "/token",
        json={"permissions": ["store_management:2"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    j = resp.json()
    assert j["permissions"] == ["store_management:2"]
    # Limited token can't access higher scopes
    assert (
        client.post(
            "/token",
            json={"permissions": ["store_management"]},
            headers={"Authorization": f"Bearer {j['id']}"},
        ).status_code
        == 403
    )

    assert client.post("/users", json=LIMITED_USER_DATA).status_code == 200
    # Strict mode: non-superuser user can't create superuser token
    assert client.post("/token", json={**LIMITED_USER_DATA, "permissions": ["server_management"]}).status_code == 422
    # Non-strict mode: silently removes server_management permission
    resp = client.post(
        "/token",
        json={**LIMITED_USER_DATA, "permissions": ["server_management"], "strict": False},
    )
    assert resp.status_code == 200
    assert resp.json()["permissions"] == []


def test_delete_token(client: TestClient, token: str):
    assert client.delete("/token/1").status_code == 401
    assert client.delete("/token/1", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    all_tokens = client.get("/token", headers={"Authorization": f"Bearer {token}"}).json()["result"]
    for token_data in all_tokens:
        if token_data["id"] == token:
            continue  # skip our token
        resp = client.delete(f"/token/{token_data['id']}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == token_data
    test_token_count(client, token)


def test_management_commands(client: TestClient, log_file_deleting: str, token: str):
    assert client.post("/manage/update").status_code == 401
    limited_user_token = client.post("/token", json=LIMITED_USER_DATA).json()["id"]
    assert client.post("/manage/update", headers={"Authorization": f"Bearer {limited_user_token}"}).status_code == 403
    assert client.post("/manage/update", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/manage/restart", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/manage/cleanup/images", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/manage/cleanup/logs", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/manage/cleanup", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/manage/daemons", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    settings.LOG_DIR = "tests/fixtures"
    assert client.post("/manage/cleanup", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert not os.path.exists(log_file_deleting)
    settings.LOG_DIR = None  # cleanup


def test_policies(client: TestClient, token: str):
    resp = client.get("/manage/policies")
    assert resp.status_code == 200
    assert resp.json() == {
        "allow_anonymous_configurator": True,
        "disable_registration": False,
        "discourage_index": False,
        "check_updates": True,
    }
    assert client.post("/manage/policies").status_code == 401
    resp = client.post(
        "/manage/policies",
        json={"disable_registration": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "allow_anonymous_configurator": True,
        "disable_registration": True,
        "discourage_index": False,
        "check_updates": True,
    }
    assert client.post("/users", json={"email": "noauth@example.com", "password": "noauth"}).status_code == 422
    # Test for loading data from db instead of loading scheme's defaults
    assert client.get("/manage/policies").json() == {
        "allow_anonymous_configurator": True,
        "disable_registration": True,
        "discourage_index": False,
        "check_updates": True,
    }
    resp = client.post(
        "/manage/policies",
        json={"disable_registration": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "allow_anonymous_configurator": True,
        "disable_registration": False,
        "discourage_index": False,
        "check_updates": True,
    }
    resp = client.get("/manage/stores")
    assert resp.status_code == 200
    assert resp.json() == {"pos_id": 1, "email_required": True}
    assert client.post("/manage/stores").status_code == 401
    resp = client.post(
        "/manage/stores",
        json={"pos_id": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"pos_id": 2, "email_required": True}
    assert client.get("/manage/stores").json() == {"pos_id": 2, "email_required": True}
    resp = client.post(
        "/manage/stores",
        json={"pos_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"pos_id": 1, "email_required": True}


def test_no_token_management(client: TestClient, token: str):
    limited_user_token = client.post("/token", json=LIMITED_USER_DATA).json()["id"]
    assert client.get("/token/current", headers={"Authorization": f"Bearer {limited_user_token}"}).status_code == 200
    assert client.get("/token", headers={"Authorization": f"Bearer {limited_user_token}"}).status_code == 403
    assert client.get("/token/count", headers={"Authorization": f"Bearer {limited_user_token}"}).status_code == 403
    assert (
        client.patch(
            f"/token/{limited_user_token}",
            headers={"Authorization": f"Bearer {limited_user_token}"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/token/{limited_user_token}",
            headers={"Authorization": f"Bearer {limited_user_token}"},
        ).status_code
        == 403
    )


def test_non_superuser_permissions(client: TestClient):
    resp = client.post(
        "/token",
        json={**LIMITED_USER_DATA, "permissions": ["full_control"], "strict": False},
    )
    token = resp.json()["access_token"]
    assert client.get("/token", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/users/2", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_notification_list(client: TestClient):
    resp = client.get("/notifications/list")
    assert resp.status_code == 200
    assert resp.json() == {
        "count": len(settings.notifiers),
        "next": None,
        "previous": None,
        "result": list(settings.notifiers.keys()),
    }


def test_notification_schema(client: TestClient):
    resp = client.get("/notifications/schema")
    assert resp.status_code == 200
    assert resp.json() == settings.notifiers


def test_template_list(client: TestClient):
    resp = client.get("/templates/list")
    assert resp.status_code == 200
    assert resp.json() == {
        "count": len(templates.templates_strings),
        "next": None,
        "previous": None,
        "result": templates.templates_strings,
    }
    resp1 = client.get("/templates/list?show_all=true")
    result = [v for template_set in templates.templates_strings.values() for v in template_set]
    assert resp1.status_code == 200
    assert resp1.json() == {
        "count": len(result),
        "next": None,
        "previous": None,
        "result": result,
    }
    resp2 = client.get("/templates/list?applicable_to=product")
    assert resp2.status_code == 200
    assert resp2.json() == {
        "count": len(templates.templates_strings["product"]),
        "next": None,
        "previous": None,
        "result": templates.templates_strings["product"],
    }
    resp3 = client.get("/templates/list?applicable_to=notfound")
    assert resp3.status_code == 200
    assert resp3.json() == {
        "count": 0,
        "next": None,
        "previous": None,
        "result": [],
    }


@pytest.mark.asyncio
async def test_services(async_client: TestClient, token: str):
    resp = await async_client.get("/tor/services")
    assert resp.status_code == 200
    assert resp.json() == await tor_ext.get_data("anonymous_services_dict", {}, json_decode=True)
    resp2 = await async_client.get("/tor/services", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    assert resp2.json() == await tor_ext.get_data("services_dict", {}, json_decode=True)


def test_export_invoices(client: TestClient, token: str):
    assert client.get("/invoices/export").status_code == 401
    json_resp = client.get("/invoices/export", headers={"Authorization": f"Bearer {token}"})
    assert json_resp.status_code == 200
    assert json_resp.json() == []
    assert "bitcartcc-export" in json_resp.headers["content-disposition"]
    resp2 = client.get("/invoices/export?export_format=json", headers={"Authorization": f"Bearer {token}"})
    assert resp2.json() == json_resp.json()
    csv_resp = client.get("/invoices/export?export_format=csv", headers={"Authorization": f"Bearer {token}"})
    assert csv_resp.status_code == 200
    assert "bitcartcc-export" in csv_resp.headers["content-disposition"]
    assert csv_resp.text == "\r\n"


def test_batch_commands(client: TestClient, token: str):
    assert client.post("/invoices/batch").status_code == 401
    assert client.post("/invoices/batch", headers={"Authorization": f"Bearer {token}"}).status_code == 422
    assert (
        client.post(
            "/invoices/batch", json={"ids": [], "command": "test"}, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 404
    )
    assert (
        client.post("/invoices", json={"store_id": -1, "price": 0.5}, headers={"Authorization": f"Bearer {token}"}).status_code
        == 404
    )
    resp1 = client.post("/invoices", json={"store_id": 2, "price": 0.5}, headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200
    invoice_id_1 = resp1.json()["id"]
    resp2 = client.post("/invoices", json={"store_id": 2, "price": 0.5}, headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    invoice_id_2 = resp2.json()["id"]
    assert (
        client.post(
            "/invoices/batch",
            json={"ids": [invoice_id_1, invoice_id_2], "command": "delete"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )
    assert client.get("/invoices", headers={"Authorization": f"Bearer {token}"}).json()["result"] == []
    resp3 = client.post("/invoices", json={"store_id": 2, "price": 0.5}, headers={"Authorization": f"Bearer {token}"})
    assert resp3.status_code == 200
    invoice_id_3 = resp3.json()["id"]
    assert (
        client.post(
            "/invoices/batch",
            json={"ids": [invoice_id_3], "command": "mark_invalid"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )
    assert client.get(f"/invoices/{invoice_id_3}", headers={"Authorization": f"Bearer {token}"}).json()["status"] == "invalid"
    assert (
        client.post(
            "/invoices/batch",
            json={"ids": [invoice_id_3], "command": "mark_complete"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )
    assert client.get(f"/invoices/{invoice_id_3}", headers={"Authorization": f"Bearer {token}"}).json()["status"] == "complete"
    client.delete(f"/invoices/{invoice_id_3}", headers={"Authorization": f"Bearer {token}"})  # cleanup


@pytest.mark.asyncio
async def test_wallet_ws(async_client, token: str):
    r = await async_client.post(
        "/wallets",
        json={"name": "testws1", "xpub": TEST_XPUB},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    wallet_id = r.json()["id"]
    async with async_client.websocket_connect(f"/ws/wallets/{wallet_id}?token={token}") as websocket:
        await asyncio.sleep(1)
        await utils.redis.publish_message(
            f"wallet:{wallet_id}", {"status": "success", "balance": str((await BTC(xpub=TEST_XPUB).balance())["confirmed"])}
        )
        await check_ws_response2(websocket)
    with pytest.raises(Exception):
        async with async_client.websocket_connect(f"/ws/wallets/{wallet_id}") as websocket:
            await check_ws_response2(websocket)
    with pytest.raises(Exception):
        async with async_client.websocket_connect(f"/ws/wallets/{wallet_id}?token=x") as websocket:
            await check_ws_response2(websocket)
    with pytest.raises(Exception):
        async with async_client.websocket_connect(f"/ws/wallets/555?token={token}") as websocket:
            await check_ws_response2(websocket)


@pytest.mark.asyncio
async def test_invoice_ws(async_client, token: str):
    r = await async_client.post("/invoices", json={"store_id": 2, "price": 5}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    invoice_id = data["id"]
    async with async_client.websocket_connect(f"/ws/invoices/{invoice_id}") as websocket:
        await asyncio.sleep(1)
        await invoices.new_payment_handler(
            DummyInstance(), None, data["payments"][0]["payment_address"], "Paid", None
        )  # emulate paid invoice
        await check_ws_response(websocket)
        async with async_client.websocket_connect(
            f"/ws/invoices/{invoice_id}"
        ) as websocket2:  # test if after invoice was completed websocket returns immediately
            await check_ws_response_complete(websocket2)
    with pytest.raises(Exception):
        async with async_client.websocket_connect("/ws/invoices/555") as websocket:
            await check_ws_response(websocket)
    with pytest.raises(Exception):
        async with async_client.websocket_connect("/ws/invoices/invalid_id") as websocket:
            await check_ws_response(websocket)


@pytest.mark.parametrize("currencies", ["", "DUMMY", "btc"])
def test_create_invoice_discount(client: TestClient, token: str, currencies: str):
    # create discount
    new_discount = {"name": "apple", "percent": 50, "currencies": currencies, "end_date": "2099-12-31 00:00:00.000000"}
    create_discount_resp = client.post("/discounts", json=new_discount, headers={"Authorization": f"Bearer {token}"})
    assert create_discount_resp.status_code == 200
    discount_id = create_discount_resp.json()["id"]
    # create product
    new_product = {"name": "apple", "price": 0.80, "quantity": 1.0, "store_id": 2, "discounts": [discount_id]}
    create_product_resp = client.post(
        "/products", data={"data": json_module.dumps(new_product)}, headers={"Authorization": f"Bearer {token}"}
    )
    assert create_product_resp.status_code == 200
    product_id = create_product_resp.json()["id"]
    invoice_resp = client.post(
        "/invoices",
        json={"store_id": 2, "price": 0.5, "products": [product_id], "discount": discount_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invoice_resp.status_code == 200
    assert {
        "price": 0.5,
        "store_id": 2,
        "discount": discount_id,
        "products": [product_id],
    }.items() < invoice_resp.json().items()
    assert (
        client.delete(f"/invoices/{invoice_resp.json()['id']}", headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )


@pytest.mark.parametrize("order_id,expect_status_code", [(-1, 404), (10, 200)])
def test_get_invoice_by_order_id(client: TestClient, token: str, order_id: int, expect_status_code):
    resp = None
    if expect_status_code == 200:
        resp = client.post(
            "/invoices",
            json={"store_id": 2, "price": 0.98, "order_id": str(order_id)},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
    assert (
        client.get(f"/invoices/order_id/{order_id}", headers={"Authorization": f"Bearer {token}"}).status_code
        == expect_status_code
    )
    if resp:
        assert client.delete(f"/invoices/{resp.json()['id']}", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_get_max_product_price(client: TestClient, token: str):
    # create product
    price = 999999.0
    new_product = {"name": "apple", "price": price, "quantity": 1.0, "store_id": 2}
    create_product_resp = client.post(
        "/products", data={"data": json_module.dumps(new_product)}, headers={"Authorization": f"Bearer {token}"}
    )
    assert create_product_resp.status_code == 200
    maxprice_resp = client.get(
        f"/products/maxprice?store={new_product['store_id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert maxprice_resp.status_code == 200
    assert maxprice_resp.json() == price


def test_create_product_with_image(client: TestClient, token: str, image: bytes):
    new_product = {"name": "sunflower", "price": 0.1, "quantity": 1.0, "store_id": 2}
    # post
    create_product_resp = client.post(
        "/products",
        data={"data": json_module.dumps(new_product)},
        files={"image": image},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_product_resp.status_code == 200
    product_dict = create_product_resp.json()
    assert isinstance(product_dict["image"], str)
    assert product_dict["image"] == f"images/products/{product_dict['id']}.png"
    # patch
    patch_product_resp = client.patch(
        f"/products/{product_dict['id']}",
        data={
            "data": json_module.dumps(
                {"price": 0.15, "quantity": 2.0, "user_id": product_dict["user_id"], "name": "sunflower"}
            )
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_product_resp.status_code == 200
    # put
    put_product_data = {
        "id": product_dict["id"],
        "name": "banana",
        "price": 0.01,
        "quantity": 1.0,
        "store_id": 2,
        "discounts": [],
        "templates": {},
        "user_id": product_dict["user_id"],
    }
    put_product_resp = client.put(
        f"/products/{product_dict['id']}",
        data={"data": json_module.dumps(put_product_data)},
        files={"image": image},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert put_product_resp.status_code == 200


@pytest.mark.asyncio
async def test_create_invoice_without_coin_rate(async_client, token: str, mocker):
    price = 9.9
    # mock coin rate missing
    mocker.patch("bitcart.BTC.rate", return_value=get_future_return_value(Decimal("nan")))
    # create invoice
    r = await async_client.post(
        "/invoices", json={"store_id": 2, "price": price, "currency": "DUMMY"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    result = r.json()
    invoice_id = result["id"]
    assert result["price"] == price
    await async_client.delete(f"/invoices/{invoice_id}", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_create_invoice_and_pay(async_client, token: str):
    # create invoice
    r = await async_client.post("/invoices", json={"store_id": 2, "price": 9.9}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    invoice_id = data["id"]
    # get payment
    payment_method = await utils.database.get_object(
        models.PaymentMethod,
        invoice_id,
        custom_query=models.PaymentMethod.query.where(models.PaymentMethod.invoice_id == invoice_id),
    )
    await invoices.new_payment_handler(
        DummyInstance(), None, data["payments"][0]["payment_address"], "complete", None
    )  # pay the invoice
    # validate invoice paid_currency
    assert (await utils.database.get_object(models.Invoice, invoice_id)).paid_currency == payment_method.currency.upper()
    await async_client.delete(f"/invoices/{invoice_id}", headers={"Authorization": f"Bearer {token}"})


def test_get_public_store(client: TestClient):
    user_id = client.post("/users", json={"email": "test2auth@example.com", "password": "test12345"}).json()["id"]
    new_token = client.post(
        "/token",
        json={"email": "test2auth@example.com", "password": "test12345", "permissions": ["full_control"]},
    ).json()["access_token"]
    # When logged in, prohibit any access to non-own objects, even if public access is available
    assert client.get("/stores/2", headers={"Authorization": f"Bearer {new_token}"}).status_code == 404
    client.delete(f"/users/{user_id}")
    # get store without user
    store = client.get("/stores/2")
    assert set(store.json().keys()) == {"created", "name", "default_currency", "email", "id", "user_id", "checkout_settings"}


def test_get_product_params(client: TestClient, token: str):
    assert client.get("/products/2", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/products/2?store=2", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/products/2?store=555", headers={"Authorization": f"Bearer {token}"}).status_code == 404


def test_product_count_params(client: TestClient, token: str):
    resp = client.get(
        "/products/count?sale=true&store=2&category=Test&min_price=0.0001&max_price=100.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json() == 0


def test_updatecheck(client: TestClient):
    resp = client.get("/update/check")
    assert resp.status_code == 200
    assert resp.json() == {"update_available": False, "tag": None}


def test_logs_list(client: TestClient, token: str):
    assert client.get("/manage/logs").status_code == 401
    resp = client.get("/manage/logs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []
    settings.LOG_DIR = "tests/fixtures"
    assert client.get("/manage/logs", headers={"Authorization": f"Bearer {token}"}).json() == [
        "bitcart-log.log",
        "bitcart-log.log.test",
    ]
    settings.LOG_DIR = None  # cleanup


def test_logs_get(client: TestClient, token: str):
    assert client.get("/manage/logs/1").status_code == 401
    assert client.get("/manage/logs/1", headers={"Authorization": f"Bearer {token}"}).status_code == 400
    settings.LOG_DIR = "tests/fixtures"
    assert client.get("/manage/logs/1", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    resp = client.get("/manage/logs/bitcart-log.log", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == "Test"
    settings.LOG_DIR = None  # cleanup


def test_logs_delete(client: TestClient, log_file: str, token: str):
    assert client.delete("/manage/logs/1").status_code == 401
    assert client.delete("/manage/logs/1", headers={"Authorization": f"Bearer {token}"}).status_code == 400
    # Tests that it is impossible to delete files outside logs directory:
    assert client.delete("/manage/logs//root/path", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert client.delete("/manage/logs/..%2F.gitignore", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    settings.LOG_DIR = "tests/fixtures"
    assert client.delete("/manage/logs/1", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert client.delete("/manage/logs/bitcart-log.log", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    resp = client.delete("/manage/logs/bitcart.log", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() is True
    settings.LOG_DIR = None  # cleanup
    assert not os.path.exists(log_file)


def test_cryptos(client: TestClient):
    resp = client.get("/cryptos")
    assert resp.status_code == 200
    assert resp.json() == {
        "count": len(settings.cryptos),
        "next": None,
        "previous": None,
        "result": list(settings.cryptos.keys()),
    }


def test_wallet_balance(client: TestClient, token: str):
    assert client.get("/wallets/2/balance").status_code == 401
    resp = client.get("/wallets/4/balance", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"confirmed": 0.01, "lightning": 0.0, "unconfirmed": 0.0, "unmatured": 0.0}


def test_lightning_endpoints(client: TestClient, token: str):
    assert client.get("/wallets/2/checkln").status_code == 401
    assert client.get("/wallets/555/checkln", headers={"Authorization": f"Bearer {token}"}).status_code == 404
    resp = client.get("/wallets/2/checkln", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() is False
    resp2 = client.get("/wallets/2/channels", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    assert resp2.json() == []
    assert (
        client.post(
            "/wallets/2/channels/open", json={"node_id": "test", "amount": 0.1}, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/wallets/2/channels/close", json={"channel_point": "test"}, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 400
    )
    assert (
        client.post("/wallets/2/lnpay", json={"invoice": "test"}, headers={"Authorization": f"Bearer {token}"}).status_code
        == 400
    )


def test_multiple_wallets_same_currency(client: TestClient, token: str):
    resp = client.post(
        "/stores", json={"name": "Multiple Currency", "wallets": [2, 3]}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    store_id = resp.json()["id"]
    resp = client.post("/invoices", json={"price": 5, "store_id": store_id})
    assert resp.status_code == 200
    resp = resp.json()
    invoice_id = resp["id"]
    assert len(resp["payments"]) == 2
    assert resp["payments"][0]["name"] == "BTC (1)"
    assert resp["payments"][1]["name"] == "BTC (2)"
    # cleanup
    client.delete(f"/invoices/{invoice_id}", headers={"Authorization": f"Bearer {token}"})
    client.delete(f"/stores/{store_id}", headers={"Authorization": f"Bearer {token}"})


def test_change_store_checkout_settings(client: TestClient, token: str):
    assert client.patch("/stores/2/checkout_settings").status_code == 401
    assert (
        client.patch(
            "/stores/555/checkout_settings", json={"expiration": 60}, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 404
    )
    resp = client.patch("/stores/2/checkout_settings", json={"expiration": 60}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["checkout_settings"]["expiration"] == 60
    assert len(resp.json()["wallets"]) > 0
    resp2 = client.get("/stores/2", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    assert resp2.json() == resp.json()
    # cleanup
    assert (
        client.patch(
            "/stores/2/checkout_settings", json={"expiration": 15}, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 200
    )


def test_products_list(client: TestClient):
    assert client.get("/products").status_code == 401
    assert client.get("/products?store=1").status_code == 200
    resp = client.get("/products?store=0")
    assert resp.status_code == 200
    assert resp.json()["result"] == []


def test_configurator(client: TestClient, token: str):
    assert client.post("/configurator/deploy").status_code == 422
    assert (
        client.post(
            "/manage/policies",
            json={"allow_anonymous_configurator": False},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )
    assert client.post("/configurator/deploy", json=SCRIPT_SETTINGS).status_code == 422
    assert (
        client.post(
            "/manage/policies",
            json={"allow_anonymous_configurator": True},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )
    resp = client.post("/configurator/deploy", json=SCRIPT_SETTINGS)
    assert resp.status_code == 200
    assert resp.json()["success"]
    script = resp.json()["output"]
    assert "sudo su -" in script
    assert f"git clone {DOCKER_REPO_URL} bitcart-docker" in script
    assert "BITCART_CRYPTOS=btc" in script
    assert "BITCART_HOST=bitcartcc.com" in script
    assert "BTC_NETWORK=testnet" in script
    assert "BTC_LIGHTNING=True" in script
    assert "BITCART_ADDITIONAL_COMPONENTS=custom,tor" in script
    deploy_settings = SCRIPT_SETTINGS.copy()
    deploy_settings["mode"] = "Remote"
    resp = client.post("/configurator/deploy", json=deploy_settings)
    assert client.get("/configurator/deploy-result/1").status_code == 404
    assert resp.status_code == 200
    assert not resp.json()["success"]
    deploy_id = resp.json()["id"]
    resp2 = client.get(f"/configurator/deploy-result/{deploy_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert not data["success"]
    assert data["id"] == deploy_id
    deploy_settings = SCRIPT_SETTINGS.copy()
    deploy_settings["mode"] = "Current"
    assert client.post("/configurator/deploy", json=deploy_settings).status_code == 401
    resp = client.post("/configurator/deploy", json=deploy_settings, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert not resp.json()["success"]
    deploy_id = resp.json()["id"]
    resp2 = client.get(f"/configurator/deploy-result/{deploy_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert not data["success"]
    assert data["id"] == deploy_id


def test_supported_cryptos(client: TestClient):
    resp = client.get("/cryptos/supported")
    assert resp.status_code == 200
    assert resp.json() == constants.SUPPORTED_CRYPTOS


def test_get_server_settings(client: TestClient, token: str):
    assert client.get("/configurator/server-settings").status_code == 405
    assert client.post("/configurator/server-settings").status_code == 401
    resp = client.post("/configurator/server-settings", json={"host": ""})
    assert resp.status_code == 200
    assert resp.json() == FALLBACK_SERVER_SETTINGS
    resp = client.post("/configurator/server-settings", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == FALLBACK_SERVER_SETTINGS  # SSH unconfigured
