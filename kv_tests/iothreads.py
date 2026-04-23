import xml.etree.ElementTree as ET
import shlex
import re

from utils.utils import escape_ansi
from utils.kubevirt import KubeVirtTest
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class IOThreadsTest(KubeVirtTest):
    def check_vm_xml_shared(self, xml):
        root = ET.fromstring(xml)
        # iothread 2 should match emptydisk
        disk = root.findall(".//disk/driver[@iothread='2']/../source")[0].get("file")
        self.assertIn("emptydisk", disk)

        # iothread 3 should match emptydisk2
        disk = root.findall(".//disk/driver[@iothread='3']/../source")[0].get("file")
        self.assertIn("emptydisk2", disk)

        # iothread 1 should match left disks
        disk_num = len(root.findall(".//disk/driver[@iothread='1']/../source"))
        self.assertEqual(disk_num, 6)

    def check_vm_xml_auto(self, xml):
        root = ET.fromstring(xml)
        # iothread 3 should match emptydisk
        disk = root.findall(".//disk/driver[@iothread='3']/../source")[0].get("file")
        self.assertIn("emptydisk", disk)

        # iothread 4 should match emptydisk2
        disk = root.findall(".//disk/driver[@iothread='4']/../source")[0].get("file")
        self.assertIn("emptydisk2", disk)

        # For other disks, they should match 1 and 2 in a round-robin fashion
        disk_num = len(root.findall(".//disk/driver[@iothread='1']/../source"))
        self.assertEqual(disk_num, 3)
        disk_num = len(root.findall(".//disk/driver[@iothread='2']/../source"))
        self.assertEqual(disk_num, 3)

        # queue should match the number of cpu
        queue = int(root.find(".//disk/driver").get("queues"))
        self.assertEqual(queue, 2)

    def check_domifstat(self, s1, s2):
        vm_output = s1
        pod_output = s2

        keys = ["rx_bytes", "rx_packets", "tx_bytes", "tx_packets"]
        data = []
        for line in vm_output.split("\n"):
            output = re.findall(r"\d+\s+", line)
            if len(output) > 0:
                data.extend([output[0].strip(), output[1].strip()])
        vm_stats = dict(zip(keys, data))
        LOGGER.info("VM output: %s", vm_stats)

        re.findall(r"[rx|tx]_.*\s+(\d+)", pod_output)
        data = [i for i in re.findall(r"[rx|tx]_.*\s+(\d+)", pod_output) if i != "0"]
        pod_stats = dict(zip(keys, data))
        LOGGER.info("POD output: %s", pod_stats)

        for i in zip(vm_stats.values(), pod_stats.values()):
            self.assertTrue(int(min(i)) / int(max(i)) > 0.99)

    def setUp(self):
        # VM template file
        if "test_shared" in self._testMethodName:
            self.template_file = "iothreads_shared.yml"
        elif "test_auto" in self._testMethodName:
            self.template_file = "iothreads_auto.yml"
        self.load_template(self.template_file)

        self.create_namespace()

    def test_shared(self):
        """
        Test iothreads shared.
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        command_output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=["virsh", "dumpxml", "1"]
        )
        self.check_vm_xml_shared(command_output)

    def test_auto(self):
        """
        Test iothreads auto and virt block multi queue.
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        command_output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=["virsh", "dumpxml", "1"]
        )
        self.check_vm_xml_auto(command_output)

    def test_domifstat(self):
        """
        Test domifstat for VIRT-298114
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()
        # set a big timeout for the command to execute
        session.cmd_output(
            "curl -s http://example-server/RHEL-9.6-x86_64-latest-ovmf.qcow2 -o /dev/null",
            timeout=300,
        )

        iface_name = escape_ansi(
            session.cmd_output(
                "ip link | awk -F': ' '!/lo/ && /^[0-9]+:/{print $2}'"
            ).strip()
        )
        output = escape_ansi(
            session.cmd_output(f"ip stats show dev {iface_name} group link").strip()
        )
        LOGGER.info(output)

        cmd = shlex.split("virsh domifstat 1 tap0")
        pod_output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=cmd
        )
        self.check_domifstat(output, pod_output)


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
