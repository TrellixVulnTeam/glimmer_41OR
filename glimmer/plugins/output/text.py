from api import PluginOutputBase, register_plugin, cprint
from utils.printer import header


class Plugin(PluginOutputBase):
    def construct(self):
        self._handler = open("result.txt", "w+")

    def handle(self, poc, result, **kwargs):
        status = result.get('status', 1)
        if status == 0:
            sign = "+"
        elif status == 1:
            sign = "-"
        elif status == -1:
            sign = "!"
        extra = result.get('extra', {})
        msg = '%s %s (%s)' % (poc.name,
                              result.get("msg", ""), result.get("url"))
        if extra:
            msg += " extra: "
            msg += " ".join("%s:%s" % (k, v) for k, v in extra.items())
        self._handler.write("[Poc] %s %s\n" % (sign, msg))
        self._handler.flush()

    def destruct(self):
        self._handler.close()
        del self._handler

        cprint(header("Poc", "*", "Result save in ./result.txt"))


register_plugin(Plugin)
