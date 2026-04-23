import json
import xml.etree.ElementTree as ET

from utils.utils import escape_ansi, random_rfc1123_string
from utils.kubevirt import KubeVirtTest, wait, run_command
from utils.constants import VIRTCTL_CMD
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class RegularOperationTest(KubeVirtTest):
    def setUp(self):
        LOGGER.setLevel("DEBUG")
        # VM template file
        if "test_versioned_cpu" in self._testMethodName:
            self.template_file = "versioned_cpu.yml"
        if "test_dedicated_cpu" in self._testMethodName:
            self.template_file = "dedicated_cpu.yml"
        if "test_snapshot" in self._testMethodName:
            self.template_file = "hotplug.yml"
        if "test_rhel_hyperv" in self._testMethodName:
            self.template_file = "hyperv.yml"
        if (
            "test_vm_clone" in self._testMethodName
            or "test_service_expose" in self._testMethodName
        ):
            self.template_file = "default_uefi.yml"
        self.load_template(self.template_file)

        self.create_namespace()
        if "test_snapshot" in self._testMethodName:
            self.enable_featuregates()

    def test_versioned_cpu(self):
        """
        Test versioned cpu
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()
        output = escape_ansi(session.cmd_output("cat /proc/cpuinfo"))
        LOGGER.info(output)
        self.assertIn("Skylake", output)

        # migrate the VM
        self.live_migration()
        # Relogin after live migration
        session = self.login_vm()
        output = escape_ansi(session.cmd_output("cat /proc/cpuinfo"))
        LOGGER.info(output)
        self.assertIn("Skylake", output)

    def test_dedicated_cpu(self):
        """
        Test dedicated cpu and dedicated CPU for QEMU emulator
        """

        def check_xml():
            root = ET.fromstring(
                self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
                    command=["virsh", "dumpxml", "1"]
                )
            )
            self.assertTrue(root.find(".//cputune/vcpupin").get("cpuset"))
            self.assertTrue(root.find(".//cputune/emulatorpin").get("cpuset"))

        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        check_xml()

        # migrate the VM
        self.live_migration()

        # Check again after migration
        check_xml()

    def test_snapshot(self):
        """
        Test VM with snapshot and live migration
        """

        def file_exists(session, filename):
            cmd = f"ls {filename}"
            return session.cmd_status(cmd) == 0

        vm_dict = self.vm_template.vm_dict
        vm_name = vm_dict["metadata"]["name"]
        self.create_virtualmachine(vm_dict)
        session = self.login_vm(username="root", password="123456")
        # create a test file
        cmd = "touch testfile"
        session.cmd_output(cmd)
        vm_snapshot = random_rfc1123_string("auto_vmsnapshot")
        self.create_vm_snapshot(vm_snapshot, vm_name)
        # do live migration
        self.live_migration()
        # relogin the vm
        session = self.login_vm(username="root", password="123456")
        # check the test file still exists
        self.assertTrue(file_exists(session, "testfile"))
        # delete the test file
        cmd = "rm -f testfile"
        session.cmd_output(cmd)
        self.assertFalse(file_exists(session, "testfile"))
        # must stop the vm for snapshotrestore
        self.stop_virtualmachine()
        # restore from snapshot
        vm_restore = random_rfc1123_string("auto_vmrestore")
        self.restore_from_snapshot(vm_restore, vm_name, vm_snapshot)
        # start the VM
        self.start_virtualmachine()
        session = self.login_vm(username="root", password="123456")
        # check the test file still exists
        self.assertTrue(file_exists(session, "testfile"))

    def test_virtctl(self):
        """
        Test getting VM information by virtctl
        """

        vm_dict = self.vm_template.vm_dict
        vm_name = vm_dict["metadata"]["name"]
        self.create_virtualmachine(vm_dict)
        # virtctl userlist return logged in users
        self.login_vm()

        cmd = f"{VIRTCTL_CMD} guestosinfo {vm_name} -n {self.test_namespace}"
        output = run_command(cmd).stdout
        self.assertIn("Linux", json.loads(output)["os"]["name"])

        cmd = f"{VIRTCTL_CMD} fslist {vm_name} -n {self.test_namespace}"
        output = run_command(cmd).stdout
        self.assertTrue(len(json.loads(output)["items"]) > 0)

        cmd = f"{VIRTCTL_CMD} userlist {vm_name} -n {self.test_namespace}"
        wait(lambda: len(json.loads(run_command(cmd).stdout)["items"]) > 0)

    def test_vm_clone(self):
        """
        Test VM clone
        """
        vm_dict = self.vm_template.vm_dict
        vm_name = vm_dict["metadata"]["name"]
        self.create_virtualmachine(vm_dict)
        # login the vm
        session = self.login_vm(username="root", password="123456")
        # create a file in the vm
        cmd = "echo hello > testfile"
        session.cmd_status(cmd)

        # clone the vm
        target_name = vm_name + "-clone"
        clone_vm = self.clone_vm(
            vm_name,
            target_name,
            random_rfc1123_string("auto-vmclone"),
            self.test_namespace,
        )
        self.start_virtualmachine(clone_vm)

        # check the cloned vm has the same file
        session = self.login_vm(username="root", password="123456")
        cmd = "cat testfile"
        self.assertIn("hello", session.cmd_output(cmd).strip())

    def test_rhel_hyperv(self):
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        xml = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=["virsh", "dumpxml", "1"]
        )
        root = ET.fromstring(xml)
        self.assertEqual(
            root.find(".//features/hyperv/vendor_id").get("value"), "KVM Hv"
        )

    def test_service_expose(self):
        import time
        from ocp_resources.service import Service
        from utils.utils import VirtctlSSHConnect

        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["template"]["metadata"]["labels"]["special"] = (
            "service-expose-test"
        )
        self.create_virtualmachine(vm_dict)

        service_name = random_rfc1123_string("myservice")
        service = {
            "name": service_name,
            "namespace": self.test_namespace,
            "external_traffic_policy": "Cluster",
            "selector": {"special": "service-expose-test"},
            "type": "NodePort",
            "ports": [{"port": 27017, "protocol": "TCP", "targetPort": 22}],
        }
        self.create_ocp_resource(Service, **service)
        myservice = self.get_ocp_resource(Service, service_name, self.test_namespace)
        # wait a little time to avoid connection failure
        time.sleep(30)

        ssh_port = myservice.instance["spec"]["ports"][0]["nodePort"]
        ssh_host = self.virtualmachine_instance.vmi.node.name
        cmd = f"ssh root@{ssh_host} -p {ssh_port}"
        ssh_client = VirtctlSSHConnect(
            self.virtualmachine_instance.name,
            cmd=cmd,
            username="root",
            password="123456",
        )
        ssh_client.connect()

        self.assertEqual("root", ssh_client.session.cmd_output("whoami").strip())

    def test_cpu_stats(self):
        vm_dict = self.vm_template.vm_dict
        vm_name = vm_dict["metadata"]["name"]
        self.create_virtualmachine(vm_dict)

        domstats_output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            ["virsh", "domstats", "1"]
        )
        self.assertIn("cpu.time", domstats_output)
        self.assertIn("cpu.user", domstats_output)
        self.assertIn("cpu.system", domstats_output)

        cpustats_output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            ["virsh", "cpu-stats", "1", "--total"]
        )
        self.assertIn("cpu_time", cpustats_output)
        self.assertIn("user_time", cpustats_output)
        self.assertIn("system_time", cpustats_output)

    def test_dev_with_virtio_non_transitional(self):
        import time

        def is_model_virtio_non_transitional(xpath):
            return ET.fromstring(self.vm_xml).find(xpath) is not None

        vm_dict = self.vm_template.vm_dict
        vm_name = vm_dict["metadata"]["name"]
        self.create_virtualmachine(vm_dict)

        # wait for vm boots up
        time.sleep(60)

        self.assertTrue(
            is_model_virtio_non_transitional(
                ".//memballoon[@model='virtio-non-transitional']"
            )
        )
        output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            ["virsh", "dommemstat", "1"]
        )
        self.assertRegex(output, r"available\s\d+")

        self.assertTrue(
            is_model_virtio_non_transitional(
                ".//disk[@model='virtio-non-transitional']"
            )
        )
        output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            ["virsh", "domblkstat", "1"]
        )
        self.assertRegex(output, r"rd_bytes\s\d+")

        self.assertTrue(
            is_model_virtio_non_transitional(
                ".//interface/model[@type='virtio-non-transitional']"
            )
        )
        output = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            ["virsh", "domifstat", "1", "tap0"]
        )
        self.assertRegex(output, "tap0 rx_bytes\\s\\d+")


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
