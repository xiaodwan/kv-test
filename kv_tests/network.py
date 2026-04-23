from utils.kubevirt import KubeVirtTest, get_output
from simple_logger.logger import get_logger

from ocp_resources.network_attachment_definition import NetworkAttachmentDefinition

LOGGER = get_logger(name=__name__)


class NetworkTest(KubeVirtTest):
    def setUp(self):
        # VM template file
        self.template_file = "default_uefi.yml"
        self.load_template(self.template_file)

        self.create_namespace()
        if "test_iface_sriov" in self._testMethodName:
            self.cordon_uncordon_unsupported_sriov_nodes(cordon=True)
            self.net_name = self.test_settings["network"]["net_name"]
            self.create_sriov_network(
                self.net_name, network_namespace=self.test_namespace
            )
        elif "test_iface_bridge" in self._testMethodName:
            self.net_name = self.create_bridge_network()
        # self.enable_featuregates()

    def tearDown(self):
        if "test_iface_sriov" in self._testMethodName:
            self.cordon_uncordon_unsupported_sriov_nodes(cordon=False)
        super().tearDown()

    def check_nad(self, net_name, namespace="default"):
        """
        check the sriov network is configured
        """
        for nad in NetworkAttachmentDefinition.get(namespace=namespace):
            if net_name in nad.name:
                return True
        return False

    def test_iface_sriov(self):
        """
        Hotplug a SRIOV interface and cold plug the interface
        Notes: The sriov operator must be configured by users in OCP.
        The script doesn't do that at the moment.
        """
        vm_dict = self.vm_template.vm_dict
        self.assertTrue(self.check_nad(self.net_name, namespace=self.test_namespace))
        self.create_virtualmachine(vm_dict)
        # hotplug sriov network
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {
                        "spec": {
                            "domain": {
                                "devices": {
                                    "interfaces": [
                                        {
                                            "model": "virtio",
                                            "name": "default",
                                            "masquerade": {},
                                        },
                                        {
                                            "model": "virtio",
                                            "name": "sriov-iface",
                                            "sriov": {},
                                        },
                                    ]
                                }
                            },
                            "networks": [
                                {"name": "default", "pod": {}},
                                {
                                    "name": "sriov-iface",
                                    "multus": {"networkName": self.net_name},
                                },
                            ],
                        }
                    }
                }
            }
        }
        self.apply_patch(p)
        # wait for migration automatically
        self.wait_hotplug_migration()
        session = self.login_vm(username="root", password="123456")
        cmd = "ip -br link | awk '$1 != \"lo\" {print $1}' | wc -l"
        self.assertEqual(int(get_output(session, cmd).strip()), 2)

        # hotunplug the interface
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {
                        "spec": {
                            "domain": {
                                "devices": {
                                    "interfaces": [
                                        {
                                            "model": "virtio",
                                            "name": "default",
                                            "masquerade": {},
                                        }
                                    ]
                                }
                            },
                            "networks": [{"name": "default", "pod": {}}],
                        }
                    }
                }
            }
        }
        self.apply_patch(p)
        # restart the VM
        self.restart_virtualmachine()
        session = self.login_vm(username="root", password="123456")
        cmd = "ip -br link | awk '$1 != \"lo\" {print $1}' | wc -l"
        self.assertEqual(int(get_output(session, cmd).strip()), 1)

    def test_iface_bridge(self):
        """
        Hotplug/Unplug a bridge interface
        Notes: Make sure the nodes have multiple interfaces, the interface used in
        this case won't break the connection to the nodes.

        The test script only supports ocp >= 4.20. In earlier ocp version, the behavior
        may be different.
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)

        # hotplug a bridge network
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {
                        "spec": {
                            "domain": {
                                "devices": {
                                    "interfaces": [
                                        {
                                            "model": "virtio",
                                            "name": "default",
                                            "masquerade": {},
                                        },
                                        {
                                            "model": "virtio",
                                            "name": "bridge-iface",
                                            "bridge": {},
                                        },
                                    ]
                                }
                            },
                            "networks": [
                                {"name": "default", "pod": {}},
                                {
                                    "name": "bridge-iface",
                                    "multus": {"networkName": self.net_name},
                                },
                            ],
                        }
                    }
                }
            }
        }
        self.apply_patch(p)

        self.wait_hotplug_migration()
        # Check the interface number
        session = self.login_vm(username="root", password="123456")
        cmd = "ip -br link | awk '$1 != \"lo\" {print $1}' | wc -l"
        self.assertEqual(int(get_output(session, cmd).strip()), 2)

        # hotunplug the interface by setting the 'state' to 'absent'
        p = {
            self.virtualmachine_instance: {
                "spec": {
                    "template": {
                        "spec": {
                            "domain": {
                                "devices": {
                                    "interfaces": [
                                        {
                                            "model": "virtio",
                                            "name": "default",
                                            "masquerade": {},
                                        },
                                        {
                                            "model": "virtio",
                                            "name": "bridge-iface",
                                            "bridge": {},
                                            "state": "absent",
                                        },
                                    ]
                                }
                            },
                        }
                    }
                }
            }
        }
        self.apply_patch(p)

        self.wait_hotplug_migration()

        session = self.login_vm(username="root", password="123456")
        cmd = "ip -br link | awk '$1 != \"lo\" {print $1}' | wc -l"
        self.assertEqual(int(get_output(session, cmd).strip()), 1)


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
