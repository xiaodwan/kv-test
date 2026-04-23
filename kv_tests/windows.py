from utils.kubevirt import KubeVirtTest
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class WindowsTest(KubeVirtTest):
    def setUp(self):
        self.template_file = "default_win_uefi.yml"
        self.load_template(self.template_file)
        self.create_namespace()

    def test_win_2025_uefi(self):
        """
        Test vm post migration
        """
        vm_dict = self.vm_template.vm_dict
        # The win image in use needs ~15min to be ready
        self.create_virtualmachine(vm_dict, timeout=1200)

        node_before_migration = self.virtualmachine_instance.vmi.node.name
        # do migration
        self.live_migration(timeout=900)
        # Check the node has changed
        self.assertTrue(
            node_before_migration != self.virtualmachine_instance.vmi.node.name
        )


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
