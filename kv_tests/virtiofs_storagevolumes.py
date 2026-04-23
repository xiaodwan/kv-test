from utils.utils import escape_ansi
from utils.kubevirt import PreIntegrationTest, wait, get_output
from simple_logger.logger import get_logger
from ocp_resources.datavolume import DataVolume
from ocp_resources.persistent_volume_claim import PersistentVolumeClaim

LOGGER = get_logger(name=__name__)


def auto_update_check(session, cmd, expected_value):
    actual_val = escape_ansi(get_output(session, cmd).strip())
    return actual_val == expected_value


class VirtiofsTest(PreIntegrationTest):
    def setUp(self):
        self.test_storage_class = self.test_settings["storage"]["cephfs_storage_class"]
        # VM template file
        if "test_pvc" in self._testMethodName:
            self.template_file = "virtiofs_pvc.yml"
        elif "test_datavolume" in self._testMethodName:
            self.template_file = "virtiofs_datavolume.yml"
        self.load_template(self.template_file)

        self.create_namespace()
        self.enable_featuregates()

    def create_pvc(self, vm_dict):
        """
        Create a RWX pvc
        """

        vol_name, pvc_name = [
            (i["name"], i["persistentVolumeClaim"].get("claimName"))
            for i in vm_dict["spec"]["template"]["spec"]["volumes"]
            if "persistentVolumeClaim" in i.keys()
        ][0]

        self.create_ocp_resource(
            PersistentVolumeClaim,
            name=pvc_name,
            namespace=self.test_namespace,
            size="1Gi",
            accessmodes=PersistentVolumeClaim.AccessMode.RWX,
            storage_class=self.test_storage_class,
        )

        self.persistentvolumeclaim_instance.vol_name = vol_name

    def create_dv(self, vm_dict):
        """
        Create a RWX dv
        """

        vol_name, dv_name = [
            (i["name"], i["dataVolume"].get("name"))
            for i in vm_dict["spec"]["template"]["spec"]["volumes"]
            if "dataVolume" in i.keys()
        ][0]

        self.create_ocp_resource(
            DataVolume,
            name=dv_name,
            namespace=self.test_namespace,
            source="blank",
            size="1Gi",
            access_modes=DataVolume.AccessMode.RWX,
            storage_class=self.test_storage_class,
        )

        self.datavolume_instance.vol_name = vol_name

    def test_pvc(self):
        """
        Test virtiofs pvc

        Note: We don't test the pvc sharing in multi VMs.
        Only do a basis verification.
        """
        vm_dict = self.vm_template.vm_dict
        self.create_pvc(vm_dict)
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()

        session.cmd_output(
            "sudo mount -t virtiofs %s /mnt"
            % self.persistentvolumeclaim_instance.vol_name
        )
        LOGGER.info(session.cmd_output("sudo touch /mnt/file"))
        LOGGER.info(session.cmd_output("sudo chmod o+w /mnt/file"))
        LOGGER.info(session.cmd_output("ls -l /mnt"))
        session.cmd_output("echo hello > /mnt/file").strip()

        # migrate the VM
        self.live_migration()
        # Relogin after live migration
        session = self.login_vm()

        cmd = "cat /mnt/file;echo"
        wait(auto_update_check, func_args=(session, cmd, "hello"))
        # umount manually to make the delete process be faster
        session.cmd_output("sudo umount /mnt")

    def test_datavolume(self):
        """
        Test virtiofs datavolume

        Note: We don't test the dv sharing in multi VMs.
        Only do a basis verification.
        """
        vm_dict = self.vm_template.vm_dict
        self.create_dv(vm_dict)
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()

        session.cmd_output(
            "sudo mount -t virtiofs %s /mnt" % self.datavolume_instance.vol_name
        )
        LOGGER.info(session.cmd_output("ls -l /mnt"))

        # migrate the VM
        self.live_migration()
        # Relogin after live migration
        session = self.login_vm()

        cmd = "ls -l /mnt"
        output = session.cmd_output("ls -l /mnt")
        self.assertIn("disk.img", output)
        # umount manually to make the delete process be faster
        session.cmd_output("sudo umount /mnt")


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
