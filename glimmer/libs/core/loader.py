"""
Reference: https://github.com/knownsec/pocsuite3
"""

import importlib
from importlib.abc import Loader

from libs.core.config import CONFIG
from libs.core.parser import parse_path
from libs.core.exceptions import ModuleLoadExceptions
from utils import get_md5, print_traceback


def load_string_to_module(code_string, fullname=None):
    try:
        module_name = 'pocs_{0}'.format(
            get_md5(code_string)) if fullname is None else fullname
        file_path = 'glimmer://{0}'.format(module_name)
        module_loader = PocLoader(module_name, file_path, code_string)
        spec = importlib.util.spec_from_file_location(
            module_name, file_path, loader=module_loader)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except ImportError as exc:
        raise ModuleLoadExceptions.Base(exc) from exc


def load_module(module_path: str, fullname=None, verify_func=None):
    fullname = fullname if fullname else module_path
    data = parse_path(module_path)
    if not data:
        raise ModuleLoadExceptions.Base("parse data error / no data")
    module = load_string_to_module(data, fullname)
    if callable(verify_func):
        verify_func(module)
    return module


class PocLoader(Loader):
    def __init__(self, fullname, module_path, data):
        self.fullname = fullname
        self.path = module_path
        self.data = data

    def set_data(self, data):
        self.data = data

    def get_filename(self, fullname):
        return self.path

    def get_data(self, filename):
        data = ""
        if filename.startswith('glimmer://') and self.data:
            data = self.data
        return data

    def exec_module(self, module):
        filename = self.get_filename(self.fullname)
        poc_code = self.get_data(filename)
        try:
            obj = compile(poc_code, filename, 'exec',
                          dont_inherit=True, optimize=-1)
            exec(obj, module.__dict__)
        except Exception as exc:
            raise ModuleLoadExceptions.ModuleCompileError(
                "compile module failed") from exc
