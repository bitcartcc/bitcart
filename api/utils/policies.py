import json

from api import models, utils


async def get_setting(scheme):
    name = scheme.__name__.lower()
    item = await utils.database.get_object(
        models.Setting, custom_query=models.Setting.query.where(models.Setting.name == name), raise_exception=False
    )
    if not item:
        return scheme()
    return scheme(**json.loads(item.value))


async def set_setting(scheme):
    name = scheme.__class__.__name__.lower()
    json_data = scheme.dict(exclude_unset=True)
    data = {"name": name, "value": json_data}
    model = await utils.database.get_object(
        models.Setting, custom_query=models.Setting.query.where(models.Setting.name == name), raise_exception=False
    )
    if model:
        value = json.loads(model.value)
        for key in json_data:
            value[key] = json_data[key]
        data["value"] = json.dumps(value)
        await utils.database.modify_object(model, data)
    else:
        data["value"] = json.dumps(json_data)
        await utils.database.create_object(models.Setting, data)
    return scheme
