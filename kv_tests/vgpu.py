# Managing Virtual GPUs documentation
from utils.kubevirt import KubeVirtTest
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class VGPUTest(KubeVirtTest):
    def setUp(self):
        # VM template file
        self.template_file = "gpu.yml"
        self.assertTrue(self.check_gpu_present, "not found gpu card")
        self.mediated_dev = self.test_settings["vgpu"]["mediated_dev"]
        self.resource_name = self.test_settings["vgpu"]["resource_name"]
        self.resource_name = self.expose_mediated_devs(
            self.mediated_dev, self.resource_name
        )

        self.load_template(self.template_file)
        self.create_namespace()

    def test_vgpu_passthrough(self):
        """
        Test Nvidia vGPU
        Note: The vgpu has to be configured in OCP first.
        The script does do that at the moment.

        steps:
        1) find the NVIDIA device
          sh-5.1#  lspci -nnk| grep NVIDIA
        2) find the nvidia device type
          sh-5.1# cat /sys/bus/pci/devices/0000\:b1\:00.5/mdev_supported_types/nvidia-746/name
          NVIDIA A2-4Q
        3) add the config into hco
        mediatedDevicesConfiguration:
          mediatedDeviceTypes:
          - nvidia-746
          nodeMediatedDeviceTypes:
          - mediatedDeviceTypes:
            - nvidia-746
            nodeSelector:
              kubernetes.io/hostname: ocp_node_1
        """
        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["template"]["spec"]["domain"]["devices"]["gpus"][0][
            "deviceName"
        ] = self.resource_name
        self.create_virtualmachine(vm_dict)
        session = self.login_vm(username="root", password="123456")
        cmd = "lspci"
        self.assertIn("NVIDIA", session.cmd_output(cmd))

        # Pause the vm
        self.pause_virtualmachine()
        # Resume the vm
        self.resume_virtualmachine()
        self.assertIn("NVIDIA", session.cmd_output(cmd))
        # restart the vm
        self.restart_virtualmachine()
        session = self.login_vm(username="root", password="123456")
        self.assertIn("NVIDIA", session.cmd_output(cmd))


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
