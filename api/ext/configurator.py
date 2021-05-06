import json
import re
import time

from fastapi import HTTPException
from fastapi.security import SecurityScopes
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from api import events, schemes, settings, utils
from api.constants import DOCKER_REPO_URL
from api.logger import get_logger
from api.schemes import SSHSettings
from api.utils.logging import log_errors

COLOR_PATTERN = re.compile(r"\x1b[^m]*m")
BASH_INTERMEDIATE_COMMAND = 'echo "end-of-command $(expr 1 + 1)"'
INTERMEDIATE_OUTPUT = "end-of-command 2"
MAX_OUTPUT_WAIT = 10
OUTPUT_INTERVAL = 0.5
BUFFER_SIZE = 17640

REDIS_KEY = "bitcartcc_configurator_ext"
KEY_TTL = 60 * 60 * 24  # 1 day

logger = get_logger(__name__)


def install_package(package):
    return f"apt-get update && apt-get install -y {package}"


def create_bash_script(settings):
    git_repo = settings.advanced_settings.bitcart_docker_repository or DOCKER_REPO_URL
    root_password = settings.ssh_settings.root_password
    reverseproxy = "nginx-https" if settings.domain_settings.https else "nginx"
    cryptos_str = ",".join(settings.coins.keys())
    installation_pack = settings.advanced_settings.installation_pack
    additional_components = sorted(set(settings.additional_services + settings.advanced_settings.additional_components))
    domain = settings.domain_settings.domain or "bitcart.local"
    script = ""
    if not root_password:
        script += "sudo su -"
    else:
        script += f'echo "{root_password}" | sudo -S sleep 1 && sudo su -'
    script += "\n"
    script += f"{install_package('git')}\n"
    script += (
        'if [ -d "bitcart-docker" ]; then echo "existing bitcart-docker folder found, pulling instead of cloning.";'
        " git pull; fi\n"
    )
    script += f'if [ ! -d "bitcart-docker" ]; then echo "cloning bitcart-docker"; git clone {git_repo} bitcart-docker; fi\n'
    if git_repo != DOCKER_REPO_URL:
        script += 'export BITCARTGEN_DOCKER_IMAGE="bitcartcc/docker-compose-generator:local"\n'
    script += f"export BITCART_HOST={domain}\n"
    if reverseproxy != "nginx-https":
        script += f"export BITCART_REVERSEPROXY={reverseproxy}\n"
    script += f"export BITCART_CRYPTOS={cryptos_str}\n"
    for symbol, coin in settings.coins.items():
        if coin.network != "mainnet":
            script += f"export {symbol.upper()}_NETWORK={coin.network}\n"
        if coin.lightning:
            script += f"export {symbol.upper()}_LIGHTNING={coin.lightning}\n"
    if installation_pack != "all":
        script += f"export BITCART_INSTALL={installation_pack}\n"
    if additional_components:
        script += f"export BITCART_ADDITIONAL_COMPONENTS={','.join(additional_components)}\n"
    script += "cd bitcart-docker\n"
    script += "./setup.sh\n"
    return script


def remove_intermediate_lines(output):
    newoutput = ""
    for line in output.splitlines():
        if BASH_INTERMEDIATE_COMMAND in line or INTERMEDIATE_OUTPUT in line:
            continue
        newoutput += line + "\n"
    return newoutput


def remove_colors(output):
    return "\n".join([COLOR_PATTERN.sub("", line) for line in output.split("\n")])


def send_command(channel, command):
    channel.sendall(command + "\n")
    channel.sendall(f"{BASH_INTERMEDIATE_COMMAND}\n")  # To find command end
    finished = False
    counter = 0
    output = ""
    while not finished:
        if counter > MAX_OUTPUT_WAIT:
            counter = 0
            channel.sendall(f"{BASH_INTERMEDIATE_COMMAND}\n")
        while channel.recv_ready():
            data = channel.recv(BUFFER_SIZE).decode()
            output += data
            if INTERMEDIATE_OUTPUT in data:
                finished = True
        time.sleep(OUTPUT_INTERVAL)
        counter += 1
    return output


def execute_ssh_commands(commands, ssh_settings):
    try:
        client = ssh_settings.create_ssh_client()
        channel = client.invoke_shell()
        output = ""
        for command in commands.splitlines():
            output += send_command(channel, command)
        output = remove_intermediate_lines(output)
        output = remove_colors(output)
        channel.close()
        client.close()
        return True, output
    except Exception as e:
        return False, str(e)


async def set_task(task_id, data):
    async with utils.redis.wait_for_redis():
        await settings.redis_pool.hmset_dict(REDIS_KEY, {task_id: json.dumps(data)})


async def create_new_task(script, ssh_settings, is_manual):
    deploy_id = utils.common.unique_id()
    data = {
        "id": deploy_id,
        "script": script,
        "ssh_settings": ssh_settings.dict(),
        "success": is_manual,
        "finished": is_manual,
        "created": utils.time.now().timestamp(),
        "output": script if is_manual else "",
    }
    await set_task(deploy_id, data)
    if not is_manual:
        await events.event_handler.publish("deploy_task", {"id": deploy_id})
    return data


async def get_task(task_id):
    async with utils.redis.wait_for_redis():
        data = await settings.redis_pool.hget(REDIS_KEY, task_id, encoding="utf-8")
        return json.loads(data) if data else data


async def deploy_task(event, event_data):
    task_id = event_data["id"]
    task = await get_task(task_id)
    if not task:
        return
    logger.debug(f"Started deployment {task_id}")
    success, output = await run_in_threadpool(execute_ssh_commands, task["script"], SSHSettings(**task["ssh_settings"]))
    logger.debug(f"Deployment {task_id} success: {success}")
    task["finished"] = True
    task["success"] = success
    task["output"] = output
    await set_task(task_id, task)


async def authenticate_request(request, scopes=[]):
    try:
        await utils.authorization.AuthDependency()(request, SecurityScopes(scopes))
    except HTTPException:
        if scopes:
            raise
        allow_anonymous_configurator = (await utils.policies.get_setting(schemes.Policy)).allow_anonymous_configurator
        if not allow_anonymous_configurator:
            raise HTTPException(422, "Anonymous configurator access disallowed")


async def refresh_pending_deployments():
    with log_errors():
        now = utils.time.now().timestamp()
        async with utils.redis.wait_for_redis():
            to_delete = []
            async for key, value in settings.redis_pool.ihscan(REDIS_KEY):
                with log_errors():
                    key = key.decode("utf-8")
                    value = value.decode("utf-8")
                    value = json.loads(value) if value else value
                    # Remove stale deployments
                    if "created" not in value or now - value["created"] >= KEY_TTL:
                        to_delete.append(key)
                    try:
                        ssh_settings = SSHSettings(**value["ssh_settings"])
                    except ValidationError:
                        continue
                    # Mark all current instance deployments as complete as we can't do it from the worker task
                    if ssh_settings == settings.SSH_SETTINGS:
                        value["finished"] = True
                        value["success"] = True
                        value["output"] = "No output available. Current instance has been restarted"
                        await set_task(key, value)
            if to_delete:
                await settings.redis_pool.hdel(REDIS_KEY, *to_delete)
