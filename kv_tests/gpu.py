from utils.kubevirt import KubeVirtTest
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class GPUTest(KubeVirtTest):
    def setUp(self):
        # VM template file
        self.template_file = "gpu.yml"
        self.assertTrue(self.check_gpu_present, "not found gpu card")
        # lspci -nnv | grep -i nvidia
        self.pci_dev = self.test_settings["gpu"]["pci_dev"]
        self.resource_name = self.test_settings["gpu"]["resource_name"]
        self.resource_name = self.expose_pci_host_devs(self.pci_dev, self.resource_name)

        self.load_template(self.template_file)
        self.create_namespace()

    def test_gpu_passthrough(self):
        """
        Test Nvidia GPU Passthrough
        Note: GPU Passthrough must be configured correctly in OCP first.
        The script does do that at the moment.
        """
        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["template"]["spec"]["domain"]["devices"]["gpus"][0][
            "deviceName"
        ] = self.resource_name
        self.create_virtualmachine(vm_dict)
        session = self.login_vm(username="root", password="123456")
        cmd = "lspci"
        self.assertIn("NVIDIA", session.cmd_output(cmd))


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
