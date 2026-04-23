from utils.utils import escape_ansi
from utils.kubevirt import PreIntegrationTest, wait, get_output
from simple_logger.logger import get_logger
from ocp_resources.secret import Secret
from ocp_resources.config_map import ConfigMap
from ocp_resources.service_account import ServiceAccount

LOGGER = get_logger(name=__name__)


def auto_update_check(session, cmd, expected_value):
    actual_val = escape_ansi(get_output(session, cmd).strip())
    return actual_val == expected_value


class VirtiofsTest(PreIntegrationTest):
    def setUp(self):
        # VM template file
        if "test_secret" in self._testMethodName:
            self.template_file = "virtiofs_secret.yml"
        elif "test_configmap" in self._testMethodName:
            self.template_file = "virtiofs_cm.yml"
        elif "test_serviceaccount" in self._testMethodName:
            self.template_file = "virtiofs_sa.yml"
        elif "test_downwardapi" in self._testMethodName:
            self.template_file = "virtiofs_downwardapi.yml"

        self.load_template(self.template_file)
        self.create_namespace()
        self.enable_featuregates()

    def create_secret(self, vm_dict):
        """
        Create a secret

        Return:
        --------
        Return a CNVTest with secret resource
        """
        # Get secret name from tempalte file
        vol_name, secret_name = [
            (i["name"], i["secret"].get("secretName"))
            for i in vm_dict["spec"]["template"]["spec"]["volumes"]
            if "secret" in i.keys()
        ][0]

        # Prepare secret
        data = {"user": "autotest", "pwd": "123"}
        self.create_ocp_resource(
            Secret, name=secret_name, string_data=data, namespace=self.test_namespace
        )
        self.secret_instance.vol_name = vol_name
        self.secret_instance.res_name = secret_name

    def create_configmap(self, vm_dict):
        """
        Create a configmap

        Return:
        --------
        Return a CNVTest with configmap resource
        """
        vol_name, configmap_name = [
            (i["name"], i["configMap"].get("name"))
            for i in vm_dict["spec"]["template"]["spec"]["volumes"]
            if "configMap" in i.keys()
        ][0]

        # Prepare configmap
        data = {"updated": "false", "text": "This is a text"}
        self.create_ocp_resource(
            ConfigMap, name=configmap_name, data=data, namespace=self.test_namespace
        )
        self.configmap_instance.vol_name = vol_name
        self.configmap_instance.res_name = configmap_name

    def create_serviceaccount(self, vm_dict):
        """
        Create a service account

        Return:
        --------
        Return a CNVTest with service account resource
        """
        vol_name, sa_name = [
            (i["name"], i["serviceAccount"].get("serviceAccountName"))
            for i in vm_dict["spec"]["template"]["spec"]["volumes"]
            if "serviceAccount" in i.keys()
        ][0]

        # Prepare service account
        self.create_ocp_resource(
            ServiceAccount, name=sa_name, namespace=self.test_namespace
        )
        self.serviceaccount_instance.vol_name = vol_name
        self.serviceaccount_instance.res_name = sa_name

    def test_configmap(self):
        """
        Test virtiofs configmap
        """
        vm_dict = self.vm_template.vm_dict
        self.create_configmap(vm_dict)
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()

        get_output(
            session, "sudo mount -t virtiofs %s /mnt" % self.configmap_instance.vol_name
        )
        LOGGER.info(get_output(session, "ls -l /mnt"))
        actual_val = escape_ansi(get_output(session, "cat /mnt/updated;echo").strip())

        self.assertEqual(actual_val, "false")

        # migrate the VM
        self.live_migration(
            vmi_name=self.virtualmachine_instance.name,
            namespace=self.virtualmachine_instance.namespace,
        )
        # Relogin after live migration
        session = self.login_vm()
        # update the configmap
        p = {self.configmap_instance: {"data": {"updated": "true"}}}
        self.apply_patch(p)

        cmd = "cat /mnt/updated;echo"
        wait(auto_update_check, func_args=(session, cmd, "true"))
        # umount manually to make the delete process be faster
        session.cmd_output("sudo umount /mnt")

    def test_secret(self):
        """
        Test virtiofs secret
        """
        vm_dict = self.vm_template.vm_dict
        self.create_secret(vm_dict)
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()

        session.cmd_output(
            "sudo mount -t virtiofs %s /mnt" % self.secret_instance.vol_name
        )
        LOGGER.info(get_output(session, "ls -l /mnt"))
        actual_val = escape_ansi(get_output(session, "cat /mnt/pwd;echo").strip())

        self.assertEqual(actual_val, "123")

        # migrate the VM
        self.live_migration(
            vmi_name=self.virtualmachine_instance.name,
            namespace=self.virtualmachine_instance.namespace,
        )
        # Relogin after live migration
        session = self.login_vm()
        # update the secret
        p = {self.secret_instance: {"stringData": {"pwd": "456"}}}
        self.apply_patch(p)

        cmd = "cat /mnt/pwd;echo"
        wait(auto_update_check, func_args=(session, cmd, "456"))
        # umount manually to make the delete process be faster
        session.cmd_output("sudo umount /mnt")

    def test_serviceaccount(self):
        """
        Test virtiofs service account
        """
        vm_dict = self.vm_template.vm_dict
        self.create_serviceaccount(vm_dict)
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()

        session.cmd_output(
            "sudo mount -t virtiofs %s /mnt" % self.serviceaccount_instance.vol_name
        )
        LOGGER.info(get_output(session, "ls -l /mnt"))

        cmd = "sudo sha256sum /mnt/token | cut -d' ' -f1"
        token_sum = escape_ansi(get_output(session, cmd).strip())

        # migrate the VM
        self.live_migration(
            vmi_name=self.virtualmachine_instance.name,
            namespace=self.virtualmachine_instance.namespace,
        )
        # Relogin after live migration
        session = self.login_vm()

        wait(
            lambda x, y, z: not auto_update_check(x, y, z),
            func_args=(session, cmd, token_sum),
        )
        # umount manually to make the delete process be faster
        session.cmd_output("sudo umount /mnt")

    def test_downwardapi(self):
        """
        Test virtiofs downwardapi
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        session = self.login_vm()

        vol_name = [
            i["name"]
            for i in vm_dict["spec"]["template"]["spec"]["volumes"]
            if "downwardAPI" in i.keys()
        ][0]
        session.cmd_output("sudo mount -t virtiofs %s /mnt" % vol_name)
        LOGGER.info(session.cmd_output("ls -l /mnt"))

        cmd = "sha256sum /mnt/labels | cut -d' ' -f1"
        label_sum = escape_ansi(get_output(session, cmd).strip())

        # relabel the pod
        p = {
            self.virtualmachine_instance.vmi.virt_launcher_pod: {
                "metadata": {"labels": {"mylabel": "mytest-label"}}
            }
        }
        self.apply_patch(p)

        # Check the label is updated in vm
        wait(
            lambda x, y, z: not auto_update_check(x, y, z),
            func_args=(session, cmd, label_sum),
        )

        # umount manually to make the delete process be faster
        session.cmd_output("sudo umount /mnt")


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
