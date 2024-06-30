import os
import sys
import time
import yaml
import utils
import clash
import random
import workflow
import itertools
import executable
import subprocess
from logger import logger
from workflow import TaskConfig
from collections import defaultdict
from scripts.gitforks import collect_subs

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DATA_BASE = os.path.join(PATH, "data")


def rename_duplicates(yaml_path):
    # 以UTF-8编码读取YAML文件
    with open(yaml_path, 'r', encoding='utf-8') as file:
        data = yaml.safe_load(file)

    # 记录每个名称出现的次数
    name_count = defaultdict(int)
    # 存储要重命名的索引
    to_rename = []

    # 遍历每个代理配置
    for idx, proxy in enumerate(data['proxies']):
        name = proxy['name']
        name_count[name] += 1
        if name_count[name] > 1:
            to_rename.append((idx, f"{name}_{name_count[name]}"))

    # 重命名重复的名称
    for idx, new_name in to_rename:
        data['proxies'][idx]['name'] = new_name

    # 以UTF-8编码写回修改后的数据到文件
    with open(yaml_path, 'w', encoding='utf-8') as file:
        yaml.safe_dump(data, file)


def filter_proxies(proxies):
    workspace = os.path.join(PATH, "clash")
    clash_bin, _ = executable.which_bin()
    binpath = os.path.join(workspace, clash_bin)
    filename = "config.yaml"
    proxies = clash.generate_config(workspace, list(proxies), filename)

    # 可执行权限
    utils.chmod(binpath)

    logger.info(f"startup clash now, workspace: {workspace}, config: {filename}")
    process = subprocess.Popen(
        [
            binpath,
            "-d",
            workspace,
            "-f",
            os.path.join(workspace, filename),
        ]
    )
    logger.info(f"clash start success, begin check proxies, num: {len(proxies)}")

    time.sleep(random.randint(3, 6))
    params = [
        [p, clash.EXTERNAL_CONTROLLER, 2500, "https://www.google.com/generate_204", 2500, False]
        for p in proxies
        if isinstance(p, dict)
    ]

    masks = utils.multi_thread_run(
        func=clash.check,
        tasks=params,
        num_threads=64,
        show_progress=True,
    )

    # 关闭clash
    try:
        process.terminate()
    except:
        logger.error(f"terminate clash process error")

    nodes = [proxies[i] for i in range(len(proxies)) if masks[i]]
    if len(nodes) <= 0:
        logger.error(f"cannot fetch any proxy")
        sys.exit(0)

    return nodes


if __name__ == "__main__":
    nodes = collect_subs({"config": {"push_to": ["crawledproxies"]}})
    filename = "fork_proxies.yaml"
    _, subconverter_bin = executable.which_bin()
    tasks = []
    for sub in nodes:
        conf = TaskConfig(name=utils.random_chars(length=8), sub=sub.get("sub"), bin_name=subconverter_bin)
        tasks.append(conf)

    logger.info(f"start generate subscribes information, tasks: {len(tasks)}")
    generate_conf = os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(__file__))), "subconverter",
                                 "generate.ini")
    if os.path.exists(generate_conf) and os.path.isfile(generate_conf):
        os.remove(generate_conf)

    results = utils.multi_thread_run(func=workflow.execute, tasks=tasks, num_threads=64)
    proxies = list(itertools.chain.from_iterable(results))

    if len(proxies) == 0:
        logger.error("exit because cannot fetch any proxy node")
        sys.exit(0)

    os.makedirs(DATA_BASE, exist_ok=True)
    proxies_file = os.path.join(DATA_BASE, filename)
    proxies = filter_proxies(proxies)
    # remove unused key
    nodes = []
    for p in proxies:
        if not isinstance(p, dict):
            continue

        for k in ["sub", "chatgpt", "liveness"]:
            p.pop(k, None)

        nodes.append(p)

    data = {"proxies": nodes}
    with open(proxies_file, "w+", encoding="utf8") as f:
        yaml.dump(data, f, allow_unicode=True)
        logger.info(f"found {len(nodes)} proxies, save it to {proxies_file}")

    rename_duplicates(proxies_file)
