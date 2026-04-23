import yaml
import os.path
import re

from utils.constants import TEST_CONFIG_DIR
from jinja2 import pass_context, Undefined
from jinja2 import FileSystemLoader, Environment


def parse(context, attribute_chain):
    attrs = attribute_chain.split(".")
    current = context.get(attrs[0], Undefined(name=attrs[0]))

    if not current or isinstance(current, Undefined):
        return True, ""

    for attr in attrs[1:]:
        if isinstance(current, dict):
            current = current.get(attr, Undefined(name=attr))
        else:
            current = getattr(current, attr, Undefined(name=attr))

        if not current or isinstance(current, Undefined):
            return True, ""

    return False, current


@pass_context
def test_unknown(context, attribute_chain):
    """
    A customize jinjia2 test for testing a chain in a dict is broken or
    the final value is empty or None.
    Note that the element may be a list, you can specify which element
    of the list to be checked. If the index is not specified, 0 will be
    default.

    Parameters
    ----------
    context: A dict includes all data for testing
    attribute_chain: the attr chain to be tested

    Returns:
    ---------
    True: if an attr doesn't not exist or the final val is empty or None.
    False: If all the attrs in the chain exist and the final val is not
           empty.

    Examples
    --------
    1. Return True because 'd' doesn't exist.
      context={'a':{'b':{'e':{'a':1}}}}, attribute_chain='a.b.e.a.d'
    2. Return False
      context={'a':{'b':{'e':{'a':1}}}}, attribute_chain='a.b.e'
    3. Return False
      context={'a':{'b':[{'e':{'a':1}}, 'd': 1]}}, attribute_chain='a.b[1].d'
    4. Return True because 'd' doesn't exist in a['b'][0].
      context={'a':{'b':[{'e':{'a':1}}, 'd': 1]}}, attribute_chain='a.b[].d'
    """
    chain_list = [i.lstrip(".") for i in re.split(r"\[\d*]", attribute_chain)]
    idx_list = [int(i) if i else 0 for i in re.findall(r"\[(\d*)]", attribute_chain)]
    ctx = context
    for i, v in enumerate(chain_list):
        res, ctx = parse(ctx, v)
        if not idx_list or not isinstance(ctx, list):
            return res
        ctx = ctx[idx_list[i]]


class VMTemplate(object):
    def __init__(self, template_file, template_metadata_file=None):
        """
        Load the VM template and read the VM or OCP configuration file.

        Parameters
        ----------
        template_file: The vm template file in templates directory.
        template_metadata_file: The file in kv_tests/configs directory.
        """
        self.template_metadata_file = os.path.join(
            TEST_CONFIG_DIR,
            template_metadata_file if template_metadata_file else "default.yml",
        )

        with open(self.template_metadata_file) as fd:
            self.template_metadata = yaml.safe_load(fd)

        env = Environment(
            loader=FileSystemLoader("templates"),
            lstrip_blocks=True,
            trim_blocks=True,
            undefined=Undefined,
        )
        env.tests["unknown"] = test_unknown

        self.template = env.get_template(template_file)
        self.vm_dict = self.vm_to_dict()

    def vm_to_dict(self):
        """
        return a vm dict
        """
        return yaml.safe_load(self.template.render(self.template_metadata))
