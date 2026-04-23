import re
import xml.etree.ElementTree as ET
from utils.utils import escape_ansi
from utils.kubevirt import KubeVirtTest, wait, run_command
from utils.constants import VIRTCTL_CMD
from simple_logger.logger import get_logger
from ocp_resources.datavolume import DataVolume


LOGGER = get_logger(name=__name__)


class HotplugTest(KubeVirtTest):
    TEST_DISK_NAME = "myemptydisk"
    TEST_DISK_SERIAL = "123456"

    def setUp(self):
        # fedora guest doesn't include hotplug rules.
        # so the memory doesn't take effect in the VM.
        # we use rhel guest to do the test.
        self.template_file = "hotplug.yml"
        self.load_template(self.template_file)

        self.create_namespace()
        self.enable_featuregates()

    def test_memory(self):
        """
        Test memory hotplug
        """
        vm_dict = self.vm_template.vm_dict
        # Store the initial memory for later use
        init_memory_raw = vm_dict["spec"]["template"]["spec"]["domain"]["memory"][
            "guest"
        ]
        # we assume the memory is always end with Gi.
        self.assertRegex(init_memory_raw, r"\s*\d+Gi\s*", "memory needs end with Gi")
        init_memory = int(init_memory_raw[:-2])

        self.create_virtualmachine(vm_dict)
        # At the moment, the images do not have
        # cloud-init rpm, so the config in cloudInitNoCloud does not work.
        session = self.login_vm(username="root", password="123456")
        output = escape_ansi(session.cmd_output("cat /proc/meminfo;lsmem"))
        LOGGER.info(output)

        mem_before = int(re.search(r"MemTotal:\s+(\d+)\s*", output).group(1))
        node_before_migration = self.virtualmachine_instance.vmi.node.name
        # hotplug the memory (+2Gi)
        new_memory = str(init_memory + 2) + "Gi"
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {"spec": {"domain": {"memory": {"guest": new_memory}}}}
                }
            }
        }
        self.apply_patch(p)
        self.wait_hotplug_migration()

        # Relogin after live migration
        session = self.login_vm(username="root", password="123456")
        output = escape_ansi(session.cmd_output("cat /proc/meminfo;lsmem"))
        LOGGER.info(output)
        mem_after = int(re.search(r"MemTotal:\s+(\d+)\s*", output).group(1))
        # 2Gi = 2 * 1024 * 1024 Ki
        self.assertEqual(mem_before + 2 * 1024 * 1024, mem_after)

        # hotunplug the memory (-1Gi)
        new_memory = str(init_memory + 2 - 1) + "Gi"
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {"spec": {"domain": {"memory": {"guest": new_memory}}}}
                }
            }
        }
        self.apply_patch(p)
        self.wait_hotplug_migration()
        # Relogin after live migration
        session = self.login_vm(username="root", password="123456")
        output = escape_ansi(session.cmd_output("cat /proc/meminfo;lsmem"))
        LOGGER.info(output)
        mem_after = int(re.search(r"MemTotal:\s+(\d+)\s*", output).group(1))
        self.assertEqual(mem_before + 1 * 1024 * 1024, mem_after)

    def test_vcpu_hotplug(self):
        """
        Test vcpu hotplug

        hotunplug will report "Reduction of CPU socket count requires a restart".

        We assume the cores and thread are 1 and only update sockets in the
        test.
        """

        def check_cpu_number(session, expect_val):
            """
            Check the cpu number in VM
            """
            output = escape_ansi(session.cmd_output("lscpu"))
            LOGGER.info(output)
            vm_vcpu_num = int(re.search(r"CPU\(s\):\s*(\d+)", output).group(1))
            self.assertEqual(expect_val, vm_vcpu_num)

            # Bug CNV-62851
            output = escape_ansi(session.cmd_output("cat /proc/cpuinfo"))
            vm_vcpu_num = len(re.findall(r"processor", output))
            self.assertEqual(expect_val, vm_vcpu_num)

        vm_dict = self.vm_template.vm_dict
        # Store the initial cpu number for later use
        init_vcpu_num = int(
            vm_dict["spec"]["template"]["spec"]["domain"]["cpu"]["sockets"]
        )
        self.create_virtualmachine(vm_dict)
        # At the moment, the images do not have
        # cloud-init rpm, so the config in cloudInitNoCloud does not work.
        session = self.login_vm(username="root", password="123456")
        check_cpu_number(session, init_vcpu_num)

        node_before_migration = self.virtualmachine_instance.vmi.node.name
        # hotplug the vpuc (+1)
        new_vcpu_num = init_vcpu_num + 1
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {"spec": {"domain": {"cpu": {"sockets": new_vcpu_num}}}}
                }
            }
        }
        self.apply_patch(p)
        # Wait and check the VM is migrated successfully.
        self.wait_hotplug_migration()

        # Relogin the VM
        session = self.login_vm(username="root", password="123456")
        check_cpu_number(session, new_vcpu_num)

        max_vcpu_num = self.virtualmachine_instance.vmi.instance.to_dict()["spec"][
            "domain"
        ]["cpu"]["maxSockets"]
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {"spec": {"domain": {"cpu": {"sockets": max_vcpu_num}}}}
                }
            }
        }
        self.apply_patch(p)
        # Wait and check the VM is migrated successfully.
        self.wait_hotplug_migration()
        # Relogin the VM
        session = self.login_vm(username="root", password="123456")
        check_cpu_number(session, max_vcpu_num)

        # Pause the vm
        self.pause_virtualmachine()
        # Resume the vm
        self.resume_virtualmachine()
        # Do not need relogin the VM after pause and resume
        check_cpu_number(session, max_vcpu_num)

        # restart the vm
        self.restart_virtualmachine()
        # Relogin the VM
        session = self.login_vm(username="root", password="123456")
        check_cpu_number(session, max_vcpu_num)

    def test_vcpu_gt_max(self):
        """
        Test vcpu greater than the max number.
        """

        def check_msg():
            """
            Check the condition message
            """
            expect_msg = "CPU sockets updated in template spec to a value higher than what's available"
            return (
                self.virtualmachine_instance.get_condition_message("RestartRequired")
                == expect_msg
            )

        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)

        max_vcpu_num = self.virtualmachine_instance.vmi.instance.to_dict()["spec"][
            "domain"
        ]["cpu"]["maxSockets"]
        target_vcpu_num = max_vcpu_num + 1
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {
                        "spec": {"domain": {"cpu": {"sockets": target_vcpu_num}}}
                    }
                }
            }
        }
        self.apply_patch(p)

        wait(check_msg)

    def test_vcpu_unhotplug(self):
        """
        Test vcpu unhotplug. unhotplug will trigger "Reduction of
        CPU socket count requires a restart"
        """

        def check_msg():
            """
            Check the condition message
            """
            expect_msg = "Reduction of CPU socket count requires a restart"
            return (
                self.virtualmachine_instance.get_condition_message("RestartRequired")
                == expect_msg
            )

        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)

        target_vcpu_num = 1
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {
                        "spec": {"domain": {"cpu": {"sockets": target_vcpu_num}}}
                    }
                }
            }
        }
        self.apply_patch(p)

        wait(check_msg)

    def _add_volume(self, persist=False):
        """Adds a volume using virtctl."""
        cmd = (
            f"{VIRTCTL_CMD} addvolume {self.virtualmachine_instance.name} "
            f"--volume-name={self.TEST_DISK_NAME} "
            f"--serial={self.TEST_DISK_SERIAL} -n {self.test_namespace}"
        )
        if persist:
            cmd += " --persist"
        run_command(cmd, check=True, timeout=300)

    def _remove_volume(self, persist=False):
        """Removes a volume using virtctl."""
        cmd = (
            f"{VIRTCTL_CMD} removevolume {self.virtualmachine_instance.name} "
            f"--volume-name={self.TEST_DISK_NAME} "
            f"-n {self.test_namespace}"
        )
        if persist:
            cmd += " --persist"
        run_command(cmd, check=True, timeout=300)

    def _get_disk_device_by_serial(self, serial):
        """Gets the disk device path by its serial number from virsh dumpxml."""
        xml = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=["virsh", "dumpxml", "1"]
        )
        # LOGGER.info(xml)
        root = ET.fromstring(xml)
        disk = root.find(f"./devices/disk[serial='{serial}']")
        if disk is not None:
            target = disk.find("target")
            if target is not None:
                return f"/dev/{target.get('dev')}"
        return None

    def test_disk_hotplug(self):
        """
        disk hotplug/unplug
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)

        test_storage_class = self.test_settings["storage"]["cephfs_storage_class"]
        kwargs = {
            "source": "blank",
            "name": self.TEST_DISK_NAME,
            "namespace": self.test_namespace,
            "size": "200Mi",
            "storage_class": test_storage_class,
            "access_modes": DataVolume.AccessMode.RWX,
        }
        self.create_ocp_resource(DataVolume, **kwargs)

        # hotplug an empty disk (non-persistent)
        self._add_volume(persist=False)
        wait(lambda: self._get_disk_device_by_serial(self.TEST_DISK_SERIAL) is not None)
        target_disk = self._get_disk_device_by_serial(self.TEST_DISK_SERIAL)

        check_disk_cmd = f"ls -l {target_disk}"

        session = self.login_vm(username="root", password="123456")
        wait(lambda: session.cmd_status(check_disk_cmd) == 0)

        # hotunplug the empty disk (non-persistent)
        self._remove_volume(persist=False)
        wait(lambda: session.cmd_status(check_disk_cmd) != 0)

        # hotplug an empty disk (persistent)
        self._add_volume(persist=True)
        wait(lambda: self._get_disk_device_by_serial(self.TEST_DISK_SERIAL) is not None)
        target_disk = self._get_disk_device_by_serial(self.TEST_DISK_SERIAL)

        session = self.login_vm(username="root", password="123456")
        wait(lambda: session.cmd_status(check_disk_cmd) == 0)

        # hotunplug the empty disk (persistent)
        self._remove_volume(persist=True)
        wait(lambda: session.cmd_status(check_disk_cmd) != 0)


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
