from glob import glob
from os import path
from sys import path as sys_path
from pathlib import Path
from queue import Queue, Empty
from time import strftime
from itertools import chain
from concurrent.futures import ThreadPoolExecutor

from click import UsageError
from rich.progress import Progress, SpinnerColumn, BarColumn

from glimmer.libs.core.parser import parse_path
from glimmer.utils import cprint, header, CONSOLE, print_traceback
from glimmer.libs.request import patch_request
from glimmer.libs.logger import init_logger, logger
from glimmer.libs.core.loader import load_modules
from glimmer.libs.core.config import CONFIG, PLUGINS, POCS, ConfigHandler
from glimmer.libs.core.exceptions import ModuleLoadExceptions


def _verify_poc(module):
    """Verify poc module"""
    if not hasattr(module, "Poc"):
        raise ModuleLoadExceptions.VerifyError("non-existent class: Poc")
    module_class_poc = getattr(module, "Poc")
    if not isinstance(module_class_poc, object):
        raise ModuleLoadExceptions.VerifyError("error attribute type: Poc")
    if not hasattr(module_class_poc, "check"):
        raise ModuleLoadExceptions.VerifyError(
            "non-existent method: Poc.check")


def _set_config(root_path, verbose, very_verbose, debug):
    # set root_path
    logger.info("_set_config: set root_path")
    sys_path.insert(0, root_path)
    CONFIG.base.root_path = Path(root_path)
    # set verbose flag
    logger.info("_set_config: set verbose flag")
    if very_verbose:
        verbose = True
    if debug:
        very_verbose = False
        verbose = False
    CONFIG.option.verbose = verbose
    CONFIG.option.very_verbose = very_verbose
    CONFIG.option.debug = debug


def _load_poc(poc_path, fullname=None, msgType="", verify_func=None):
    try:
        modules = load_modules(poc_path, fullname, verify_func)
    except ModuleLoadExceptions.Base as e:
        msg = header(msgType, "-", "load poc(s) %s error: " %
                     fullname + str(e) + "\n")
        return None, msg
    else:
        msg = header(msgType, "+", "load poc(s) %s\n" % fullname)
        return modules, msg


def _work(tasks_queue, results_queue):
    while not tasks_queue.empty():
        target, poc = tasks_queue.get()
        try:
            res = poc.check(target)
        except Exception as err:
            res = {"url": "",
                   "status": -1,
                   "msg": "work error: " + str(err),
                   "extra": {}
                   }
            if CONFIG.option.debug:
                print_traceback()
        results_queue.put((target, poc, res))


def _run(threads, tasks_queue, results, timeout, output_handlers):
    results_queue = Queue()
    finish_tasks_num = 0
    tasks_num = tasks_queue.qsize()
    with ThreadPoolExecutor(threads) as pool, Progress(SpinnerColumn(), "{task.description}", BarColumn(), "{task.completed} / {task.total}",  transient=True, console=CONSOLE) as bar:
        def _update_progress_bar():
            # update bar
            if not CONFIG.option.debug:
                bar.update(bar_task, advance=1)

        # create bar_task
        if not CONFIG.option.debug:
            bar_task = bar.add_task("[cyan]testing", total=tasks_queue.qsize())
        # create futures
        _ = [pool.submit(_work, tasks_queue, results_queue)
             for _ in range(threads)]
        # get result as completed
        while finish_tasks_num < tasks_num:
            try:
                target, poc, poc_result = results_queue.get(True, timeout)
            except Empty:
                finish_tasks_num += 1
                _update_progress_bar()
                continue
            if target and poc and poc_result:
                finish_tasks_num += 1
                _update_progress_bar()

                status = poc_result.get("status", -1)
                if status == 0:
                    logger_func = logger.info
                else:
                    logger_func = logger.error
                logger_func("_run: done poc: %s for %s" % (poc.name, target))

                results[target][poc.name] = poc_result
                # handle result
                _output(output_handlers, poc, poc_result)
    return results


def _output(output_handlers, poc, poc_result):
    for handler in output_handlers:
        handler(poc, poc_result)


def _load_from_links_and_files(links, files):
    results = []
    if links:  # load from links
        results.extend(links)
    if files:  # load from files
        for file in files:
            if not path.isfile(file):
                raise UsageError("non-existent path: %s" % file)
            with open(file, "r") as f:
                results.extend([line.strip()
                               for line in f.readlines() if line])
    return results


def load_config(config_path):
    if config_path and path.isfile(config_path):
        logger.info("load_config: load configuration from " + config_path)
    else:
        logger.warning(
            "load_config: config_path [%s] not found, use default config" % config_path)
        config_path = path.abspath(
            path.join(CONFIG.base.root_path, "data", "default_config.ini"))

    config = ConfigHandler(config_path)
    CONFIG.base.configuration = config
    request_config = config.request
    CONFIG.base.request = request_config


def load_targets(urls, files):
    if not any((urls, files)):
        raise UsageError("option url/file is required")
    targets = _load_from_links_and_files(
        urls, files)
    # parse targets
    targets = [parse_path(target, ("parser.url",)) for target in targets]
    # list expand
    if targets:
        targets = tuple(chain.from_iterable(targets))

    CONFIG.base.targets = targets

    detail_msgs = ""
    for target in targets:
        temp_msg = header("Load target", "*", target)
        logger.info(temp_msg, extra={"markup": True})
        detail_msgs += temp_msg

    if CONFIG.option.get("very_verbose", False):
        cprint(detail_msgs)

    count_msg = header("Load targets", "+",
                       "Loaded [%d] targets" % len(targets))
    logger.info(count_msg, extra={"markup": True})

    if CONFIG.option.get("verbose", False):
        cprint(count_msg)


def load_pocs(pocs=[], poc_files=[], pocs_path=""):
    pocs_path = Path(CONFIG.base.root_path /
                     "pocs") if not pocs_path else Path(pocs_path)
    detail_msgs = ""
    instances = POCS.instances
    count_dict = {}
    if not pocs and not poc_files:
        pocs = [poc for poc in glob(str(pocs_path / "**" / "*.py"))]
    else:
        pocs = _load_from_links_and_files(pocs, poc_files)
    for poc in pocs:
        if not poc:
            continue
        poc_path = poc
        fname = poc
        logger_func = logger.info
        if "://" not in poc:  # choose a poc from poc dir
            poc_path = str(pocs_path / poc)
            if not poc_path.endswith(".py"):
                poc_path += ".py"
            if not path.isfile(poc_path):
                raise ModuleLoadExceptions.FileNotFound(
                    "%s not found" % poc_path)
            poc_type_dir = path.basename(path.dirname(poc))
            fname, _ = path.splitext(path.basename(poc))
            fname = "%s/%s" % (poc_type_dir, fname)
            poc_path = "file://" + poc_path
        else:
            poc_type_dir = "_" + poc[:poc.index("://")]

        modules, load_msg = _load_poc(
            poc_path, fname, "Load %s poc" % poc_type_dir, _verify_poc)
        if modules:
            if poc_type_dir not in count_dict:
                count_dict[poc_type_dir] = 0
            count_dict[poc_type_dir] += len(modules)
            instances[fname] = [module.Poc() for module in modules]
        else:
            detail_msgs += load_msg
            logger_func = logger.error
        if CONFIG.option.get("very_verbose", False):
            cprint(load_msg)
        logger_func(load_msg, extra={"markup": True})

    count_msg = "\n".join(header("Load %s pocs" % k, "+",
                                 "Loaded [%d] pocs" % v) for k, v in count_dict.items()) + "\n"
    POCS.messages = detail_msgs

    logger.info(count_msg, extra={"markup": True})

    if CONFIG.option.get("verbose", False):
        cprint(count_msg)


def load_plugins(plugins_path):
    from importlib import import_module
    plugins_path = Path(CONFIG.base.root_path /
                        "plugins") if not plugins_path else Path(plugins_path)
    detail_msgs = ""
    count_dict = {}

    for f in glob(str(plugins_path / "**" / "*.py")):
        filename = path.basename(f)
        fname, _ = path.splitext(filename)
        plugin_type_dir = path.basename(path.dirname(f))
        try:
            import_module("plugins.%s.%s" % (plugin_type_dir, fname))
            temp_msg = header("Load plugin", "+", "load plugin %s.%s \n" %
                              (plugin_type_dir, fname))
            if plugin_type_dir not in count_dict:
                count_dict[plugin_type_dir] = 0
            count_dict[plugin_type_dir] += 1

            logger.info(temp_msg, extra={"markup": True})
        except ImportError as e:
            temp_msg = header("Load plugin", "-", "load plugin %s.%s error: " %
                              (plugin_type_dir, fname) + str(e) + "\n")
            detail_msgs += temp_msg

            logger.error(temp_msg, extra={"markup": True})
        if CONFIG.option.get("very_verbose", False):
            cprint(temp_msg)

    count_msg = "\n".join(header("Load %s plugin" % k, "+",
                                 "Loaded [%d] plugins" % v) for k, v in count_dict.items()) + "\n"
    PLUGINS.messages = detail_msgs

    logger.info(count_msg, extra={"markup": True})

    if CONFIG.option.get("verbose", False):
        cprint(count_msg)


def enable_plugins(outs, *args):
    enable_plugins_name = []
    outs = ["output/%s" % out for out in outs]
    enable_plugins_name.extend(outs)
    if args:
        for arg in args:
            if isinstance(arg, (tuple, list)):
                enable_plugins_name.extend(arg)
            else:
                enable_plugins_name.append(arg)
    PLUGINS.enable_plugins_name = enable_plugins_name


def init_plugins():
    logger.info("init_plugins: construct plugins")
    for plg_name, plg in PLUGINS.instances.items():
        if plg_name in PLUGINS.enable_plugins_name:
            plg.construct()


def init_output_plugins(outs):
    output_handlers = [instance.handle for plg_name,
                       instance in PLUGINS.output.items() if plg_name in outs]
    PLUGINS.output_handlers = output_handlers


def end_plugins():
    logger.info("end_plugins: destruct plugins")
    for plg_name, plg in PLUGINS.instances.items():
        if plg_name in PLUGINS.enable_plugins_name:
            plg.destruct()


def init(root_path, verbose, very_verbose, debug):
    init_logger(debug)

    _set_config(root_path, verbose, very_verbose, debug)

    patch_request()

    ...


def start(threads, timeout):
    logger.info("start: start program")
    targets = CONFIG.base.targets
    tasks_queue = Queue()
    results = {}
    pocs = [poc_s for poc_s in POCS.instances.values()]
    pocs = tuple(chain.from_iterable(pocs))
    for target in targets:
        results[target] = {}
        for poc in pocs:
            tasks_queue.put((target, poc))
    return _run(threads, tasks_queue, results, timeout, PLUGINS.output_handlers)


def end():
    cprint("\n" + header("End", "*", "shutting down at %s" % strftime("%X")))
    ...
