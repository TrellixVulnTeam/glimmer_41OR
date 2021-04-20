from os import path

import click

from libs.controller import init, init_output_plugins, load_plugins, load_pocs, load_targets, start, load_config, end, init_plugins, enable_plugins, end_plugins
from libs.core.config import POCS, CONFIG
from utils import banner, cprint, header, print_traceback, get_full_exception_name


@click.group(invoke_without_command=True)
@click.pass_context
@click.option("--url", "-u", type=str, multiple=True, help="Load targets from {parser}.")
@click.option("--file", "-f", type=str, multiple=True, help="Load targets from file and parse each line with {parser}.")
@click.option("--poc", "-p", multiple=True, help="Load pocs from {parser}.")
@click.option("--poc-file", "-pf", multiple=True, help="Load pocs from file and parse each line with {parser}.")
@click.option("--pocs_path", help="User custom poc dir.")
@click.option("--out", "-o", default=["console", ], multiple=True, help="Use output plugins. default is console")
@click.option("--plugins_path", help="User custom output plugin dir.")
@click.option("--threads", type=int, default=10)
@click.option("--config", "-c", type=str, help="Load config from a configuration toml file.")
@click.option("--timeout", "-t", default=300, help="Max program runtime.")
@click.option("--verbose", "-v", count=True, help="display verbose information.")
@click.option("-vv", count=True, help="display more verbose information.")
@click.option("--debug", count=True, help="setup debug mode.")
def main(ctx, verbose: int = 0, vv: bool = False, threads: int = 10, config: str = "", url: str = "", file: str = "", poc=[], poc_file=[], pocs_path: str = "", out=[], plugins_path: str = "", debug: int = 0, timeout: int = 300):
    """
    A poc framework base on python.

    Tips:
    {parser} are plugins in plugins/parser which parse user input by protocol and get data for poc and target, you can write yourself parser.
    """
    run_in_main = not ctx.invoked_subcommand
    root_path = path.dirname(path.realpath(__file__))

    if run_in_main:
        banner()
    try:
        init(root_path, verbose, vv, debug)
        load_config(config)
        load_plugins(plugins_path)
        load_pocs(poc, poc_file, pocs_path)

        if run_in_main:
            enable_plugins(out)
            try:
                init_plugins()
                init_output_plugins(out)
                load_targets(url, file)
                start(threads, timeout)
            finally:
                end_plugins()
                end()
    except Exception as e:
        if CONFIG.option.debug:
            print_traceback()
        else:
            cprint(header("Base", "-", "Main breakout: %s: %s\n" %
                   (get_full_exception_name(e), str(e))))

    ...


@main.command()
@click.option("--type", "-t", type=str, help="search pocs by input string.")
@click.argument("pocs", nargs=-1)
def show_poc_info(pocs, type=""):
    if type:
        result = ", ".join(poc_name for poc_name,
                           poc in POCS.instances.items() if type in poc.type)
        result = "[cyan]%s[/]" % result if result else "[red]No result[/]"
        cprint("[yellow]Search result:[/]\n    " + result)
        return
    for poc_name in pocs:
        if poc_name in POCS.instances:
            poc = POCS.instances[poc_name]
            poc.show_info()
        else:
            cprint(header("", "-", "can't find %s" % poc_name))


if __name__ == "__main__":
    main()
