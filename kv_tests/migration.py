from utils.kubevirt import PreIntegrationTest, run_command
from utils.constants import VIRTCTL_CMD
from simple_logger.logger import get_logger
from ocp_resources.hyperconverged import HyperConverged

LOGGER = get_logger(name=__name__)


class MigrationTest(PreIntegrationTest):
    def setUp(self):
        self.load_template(self.template_file)
        self.create_namespace()

    def test_post_migration(self):
        """
        Test vm post migration
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)

        hypercon = self.get_ocp_resource(
            HyperConverged, "kubevirt-hyperconverged", namespace="kubevirt"
        )
        p = {
            hypercon: {
                "spec": {
                    "liveMigrationConfig": {
                        "allowPostCopy": True,
                        "bandwidthPerMigration": "5Mi",
                        "completionTimeoutPerGiB": 3,
                    }
                }
            }
        }
        self.patch_editor = self.apply_patch(p, backup_resources=True)

        source_pod = self.virtualmachine_instance.vmi.virt_launcher_pod
        cmd = f"{VIRTCTL_CMD} migrate {self.virtualmachine_instance.name} -n {self.test_namespace}"
        run_command(cmd, check=True, timeout=300)
        self.wait_hotplug_migration()

        source_pod_log = source_pod.log(container="compute")
        self.assertIn("Migrated(Postcopy)", source_pod_log)


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
