from api import exceptions, models, templates, utils
from api.logger import get_logger
from api.utils.common import get_object_name

logger = get_logger(__name__)


def get_template_matching_str(name, obj):
    template_str = f'Template matching "{name}"'
    if obj and hasattr(obj, "id"):
        template_str += f" for {get_object_name(obj)} {obj.id}"
    template_str += ":"
    return template_str


async def get_template(name, user_id=None, obj=None):
    if obj and obj.templates.get(name):
        query = models.Template.query.where(models.Template.id == obj.templates[name])
    else:
        query = models.Template.query.where(models.Template.name == name)
    if user_id:
        query = query.where(models.Template.user_id == user_id)
    custom_template = await utils.database.get_object(models.Template, custom_query=query, raise_exception=False)
    if custom_template:
        logger.info(f"{get_template_matching_str(name,obj)} selected custom template " f'"{custom_template.name}"')
        return templates.Template(name, custom_template.text)
    if name in templates.templates:
        logger.info(f"{get_template_matching_str(name,obj)} selected default template")
        return templates.templates[name]
    raise exceptions.TemplateDoesNotExistError(f"Template {name} does not exist and has no default")


async def get_product_template(store, product, quantity):
    template = await get_template("product", store.user_id, product)
    return template.render(store=store, product=product, quantity=quantity)


async def get_store_template(store, products):
    template = await get_template("shop", store.user_id, store)
    return template.render(store=store, products=products)


async def get_notify_template(store, invoice):
    template = await get_template("notification", store.user_id, store)
    return template.render(store=store, invoice=invoice)
