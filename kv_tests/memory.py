import xml.etree.ElementTree as ET

from utils.kubevirt import PreIntegrationTest
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class MemoryTest(PreIntegrationTest):
    def setUp(self):
        LOGGER.setLevel("DEBUG")
        # VM template file
        if "test_hugepages_size_1Gi" in self._testMethodName:
            self.template_file = "hugepages.yml"
        elif "test_cpu_memory_overcommit" in self._testMethodName:
            self.template_file = "overcommit.yml"
        self.load_template(self.template_file)

        self.create_namespace()

    def test_hugepages_size_1Gi(self):
        """
        Test hugepage size
        Note that hugepage should be configured by CI first
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        root = ET.fromstring(self.vm_xml)
        self.assertTrue(root.find(".//memoryBacking/hugepages") is not None)

    def test_cpu_memory_overcommit(self):
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        root = ET.fromstring(self.vm_xml)
        self.assertEqual(root.find("./currentMemory").text, "2097152")
        self.assertEqual(root.find("./vcpu").get("current"), "4")


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
