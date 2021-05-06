import os

from fastapi import APIRouter, HTTPException, Security

from api import constants, models, schemes, settings, utils

router = APIRouter()

# Docker deployment maintenance commands


@router.post("/restart")
async def restart_server(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    if settings.DOCKER_ENV:  # pragma: no cover
        return utils.host.run_host_output("./restart.sh", "Successfully started restart process!")
    return {"status": "error", "message": "Not running in docker"}


@router.post("/update")
async def update_server(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    if settings.DOCKER_ENV:  # pragma: no cover
        return utils.host.run_host_output("./update.sh", "Successfully started update process!")
    return {"status": "error", "message": "Not running in docker"}


@router.post("/cleanup/images")
async def cleanup_images(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    if settings.DOCKER_ENV:  # pragma: no cover
        return utils.host.run_host_output("./cleanup.sh", "Successfully started cleanup process!")
    return {"status": "error", "message": "Not running in docker"}


@router.post("/cleanup/logs")
async def cleanup_logs(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    if not settings.LOG_DIR:
        return {"status": "error", "message": "Log file unconfigured"}
    for f in os.listdir(settings.LOG_DIR):
        if f.startswith(f"{constants.LOG_FILE_NAME}."):
            try:
                os.remove(os.path.join(settings.LOG_DIR, f))
            except OSError:  # pragma: no cover
                pass
    return {"status": "success", "message": "Successfully cleaned up logs!"}


@router.post("/cleanup")
async def cleanup_server(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    data = [await cleanup_images(), await cleanup_logs()]
    message = ""
    for result in data:
        if result["status"] != "success":
            message += f"{result['message']}\n"
        else:
            return {"status": "success", "message": "Successfully started cleanup process!"}
    return {"status": "error", "message": message}


@router.get("/daemons")
async def get_daemons(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    return settings.crypto_settings


@router.get("/policies", response_model=schemes.Policy)
async def get_policies():
    return await utils.policies.get_setting(schemes.Policy)


@router.post("/policies", response_model=schemes.Policy)
async def set_policies(
    settings: schemes.Policy,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"]),
):
    return await utils.policies.set_setting(settings)


@router.get("/stores", response_model=schemes.GlobalStorePolicy)
async def get_store_policies():
    return await utils.policies.get_setting(schemes.GlobalStorePolicy)


@router.post("/stores", response_model=schemes.GlobalStorePolicy)
async def set_store_policies(
    settings: schemes.GlobalStorePolicy,
    user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"]),
):
    return await utils.policies.set_setting(settings)


@router.get("/logs")
async def get_logs_list(user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])):
    if not settings.LOG_DIR:
        return []
    data = sorted([f for f in os.listdir(settings.LOG_DIR) if f.startswith(f"{constants.LOG_FILE_NAME}.")], reverse=True)
    if os.path.exists(os.path.join(settings.LOG_DIR, constants.LOG_FILE_NAME)):
        data = [constants.LOG_FILE_NAME] + data
    return data


@router.get("/logs/{log}")
async def get_log_contents(
    log: str, user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])
):
    if not settings.LOG_DIR:
        raise HTTPException(400, "Log file unconfigured")
    try:
        with open(os.path.join(settings.LOG_DIR, log)) as f:
            contents = f.read()
        return contents
    except OSError:
        raise HTTPException(404, "This log doesn't exist")


@router.delete("/logs/{log}")
async def delete_log(
    log: str, user: models.User = Security(utils.authorization.AuthDependency(), scopes=["server_management"])
):
    if not settings.LOG_DIR:
        raise HTTPException(400, "Log file unconfigured")
    if log == constants.LOG_FILE_NAME:
        raise HTTPException(403, "Forbidden to delete current log file")
    try:
        os.remove(os.path.join(settings.LOG_DIR, log))
        return True
    except OSError:
        raise HTTPException(404, "This log doesn't exist")
