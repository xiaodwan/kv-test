# Test VM with different storage classes
# cephfs has been covered in other cases, it's not tested here.
from utils.kubevirt import PreIntegrationTest
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class StorageTest(PreIntegrationTest):
    def setUp(self):
        super().setUp()
        # VM template file
        self.template_file = "default_uefi.yml"
        self.load_template(self.template_file)

        self.create_namespace()

    def test_ceph_rbd(self):
        """
        Test a VM with storage class ocs-storagecluster-ceph-rbd.
        It is created by Jenkins CI of CNV QE.
        """
        test_storage_class = self.test_settings["storage"]["rbd_storage_class"]
        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["dataVolumeTemplates"][0]["spec"]["pvc"].update(
            {"volumeMode": "Block", "storageClassName": test_storage_class}
        )
        self.create_virtualmachine(vm_dict)
        session = self.login_vm(username="root", password="123456")
        cmd = "whoami"
        self.assertEqual("root", session.cmd_output(cmd).strip())

        # Pause the vm
        self.pause_virtualmachine()
        # Resume the vm
        self.resume_virtualmachine()
        self.assertEqual("root", session.cmd_output(cmd).strip())
        # restart the vm
        self.restart_virtualmachine()
        session = self.login_vm(username="root", password="123456")
        self.assertEqual("root", session.cmd_output(cmd).strip())

        self.live_migration()
        session = self.login_vm(username="root", password="123456")
        self.assertEqual("root", session.cmd_output(cmd).strip())


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
