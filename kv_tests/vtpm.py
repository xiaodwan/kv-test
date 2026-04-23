import xml.etree.ElementTree as ET

from utils.kubevirt import KubeVirtTest, get_output
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class VTPMTest(KubeVirtTest):
    def setUp(self):
        super().setUp()
        # VM template file
        self.template_file = "vtpm.yml"
        self.load_template(self.template_file)

        self.create_namespace()
        self.enable_featuregates()

    def check_tpm(self, session):
        vm_dict = self.vm_template.vm_dict
        persistent = vm_dict["spec"]["template"]["spec"]["domain"]["devices"][
            "tpm"
        ].get("persistent")
        xml = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=["virsh", "dumpxml", "1"]
        )
        root = ET.fromstring(xml)
        tpm_model = root.find(".//tpm").get("model")

        expected_tpm_model = "tpm-tis"
        if persistent:
            expected_tpm_model = "tpm-crb"
        self.assertEqual(tpm_model, expected_tpm_model)

        # the command does not return a newline which will
        # make the cmd_output gets nothing.
        cmd = "sudo tpm2_getrandom 10 --hex;echo"
        output = get_output(session, cmd)
        LOGGER.info(output)
        # (10 is the size in the cmd) 10 * 2 = 20
        self.assertEqual(len(output.strip()), 20)

    def test_vtpm_persistent_false(self):
        """
        Test default vtpm device
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()
        self.check_tpm(session)

        # migrate the VM
        self.live_migration()
        # Relogin after live migration
        session = self.login_vm()
        self.check_tpm(session)

    def test_vtpm_persistent_true(self):
        """
        Test vtpm with persistent true
        """
        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["template"]["spec"]["domain"]["devices"]["tpm"][
            "persistent"
        ] = True
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()
        self.check_tpm(session)

        # migrate the VM
        self.live_migration()
        # Relogin after live migration
        session = self.login_vm()
        self.check_tpm(session)

    def test_vtpm_fips_enabled(self):
        """
        Test vtpm on fips mode
        FIPS mode is enabled by default when installing OCP.
        In this case, we only check the fips is enabled but
        won't do any actual testing.
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        output = int(
            self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
                command=["cat", "/proc/sys/crypto/fips_enabled"]
            ).strip()
        )
        self.assertEqual(1, output)


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
