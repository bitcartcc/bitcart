import io

import pytest

from api import models, utils
from api.ext.export import db_to_json, json_to_csv, merge_keys


def test_merge_keys():
    assert merge_keys(None, "test") == "test"
    assert merge_keys("test", None) == "test"
    assert merge_keys("test", "test") == "test_test"


@pytest.mark.asyncio
async def test_db_to_json():
    items = await models.Invoice.query.gino.all()
    await utils.database.postprocess_func(items)
    json = list(db_to_json(items))
    assert len(json) == 1
    assert isinstance(json[0], dict)


def test_json_to_csv():
    converted = json_to_csv([{"test": 1, "list": [1, 2, 3], "obj": {"obj2": {"field": 4}}}])
    assert isinstance(converted, io.StringIO)
    value = converted.getvalue()
    assert value.strip() == "list,list_1,list_2,obj_obj2_field,test\r\n1,2,3,4,1"
