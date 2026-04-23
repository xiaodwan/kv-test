import json
import os
import os.path
import re
import subprocess
import tarfile
import time
import yaml

from utils.utils import random_rfc1123_string, get_clean_output
from utils.utils import VirtctlSSHConnect, VirtctlConsoleConnect
from utils.template import VMTemplate
from utils.constants import (
    VIRTCTL_CMD,
    BIN_DIR,
    OC_CMD,
    DEFAULT_TEST_CONFIG,
    BRIDGE_NNCP,
)
from timeout_sampler import TimeoutSampler
from simple_logger.logger import get_logger
from ocp_resources.utils.constants import (
    TIMEOUT_1SEC,
    TIMEOUT_4MINUTES,
    TIMEOUT_10MINUTES,
)
from ocp_resources.virtual_machine_instance_migration import (
    VirtualMachineInstanceMigration,
)
from ocp_resources.hyperconverged import HyperConverged
from ocp_resources.resource import ResourceEditor
from ocp_resources.namespace import Namespace
from ocp_resources.virtual_machine import VirtualMachine
from ocp_resources.virtual_machine_restore import VirtualMachineRestore
from ocp_resources.virtual_machine_snapshot import VirtualMachineSnapshot
from ocp_resources.console_cli_download import ConsoleCLIDownload
from ocp_resources.sriov_network import SriovNetwork
from ocp_resources.sriov_network_node_policy import SriovNetworkNodePolicy
from ocp_resources.node_network_configuration_policy import (
    NodeNetworkConfigurationPolicy,
)
from ocp_resources.network_attachment_definition import NetworkAttachmentDefinition
from avocado import Test
from avocado.utils import process

LOGGER = get_logger(name=__name__)


class PatchHCO(object):
    def __init__(self):
        self.hco = self.get_hco()
        self.inst_dict = self.hco.instance.to_dict()
        self.backup_patches = self.original_patch()
        self.patches = []
        # ResourceEditor
        self.rc = None

    @staticmethod
    def get_hco():
        for inst in HyperConverged.get():
            if inst.name == "kubevirt-hyperconverged" and inst.namespace == "kubevirt":
                return inst

    def original_patch(self):
        try:
            backup_patches = json.loads(
                self.inst_dict["metadata"]["annotations"][
                    "kubevirt.kubevirt.io/jsonpatch"
                ]
            )
        except KeyError:
            backup_patches = []
        return backup_patches

    def make_patch(
        self,
        featuregates=[],
        customize_images=False,
        virt_launcher="",
        virt_handler="",
        overwrite=False,
    ):
        """
        overwrite false means customizeComponents patch, featuregate patch will not overwrite each other when only
        one of them is set.
        """

        def prepare_customize_patch():
            patches = customize_patches[0]["value"]
            for i in patches:
                if i["resourceType"] == "Deployment":
                    i["patch"] = i["patch"] % virt_launcher
                if i["resourceType"] == "DaemonSet":
                    i["patch"] = i["patch"] % (virt_launcher, virt_handler)
                    pl = json.loads(i["patch"])
                    [pl.remove(p) for p in pl if not p["value"]]
                    i["patch"] = json.dumps(pl)

        def append_patch_by_path(path):
            for p in self.backup_patches:
                if p["path"] == path:
                    all_patches.append(p)
                    break

        customize_patches = [
            {
                "op": "add",
                "path": "/spec/customizeComponents/patches",
                "value": [
                    {
                        "patch": '[{"op":"replace","path":"/spec/template/spec/containers/0/args/1","value":"%s"}]',
                        "resourceName": "virt-controller",
                        "resourceType": "Deployment",
                        "type": "json",
                    },
                    {
                        "patch": '[{"op":"add","path":"/spec/template/spec/initContainers/0/image","value":"%s"},{"op":"add","path":"/spec/template/spec/containers/0/image","value":"%s"}]',
                        "resourceName": "virt-handler",
                        "resourceType": "DaemonSet",
                        "type": "json",
                    },
                ],
            }
        ]
        featuregate_patch = [
            {
                "op": "add",
                "path": "/spec/configuration/developerConfiguration/featureGates",
                "value": featuregates,
            }
        ]
        rollout_strategy_patch = [
            {
                "op": "add",
                "path": "/spec/configuration/vmRolloutStrategy",
                "value": "LiveUpdate",
            }
        ]

        all_patches = []
        if customize_images:
            prepare_customize_patch()
            all_patches.extend(customize_patches)
        elif not overwrite:
            append_patch_by_path("/spec/customizeComponents/patches")

        if len(featuregates) > 0:
            all_patches.extend(featuregate_patch)
        elif not overwrite:
            append_patch_by_path(
                "/spec/configuration/developerConfiguration/featureGates"
            )

        if "VMLiveUpdateFeatures" in featuregates:
            all_patches.extend(rollout_strategy_patch)
        elif not overwrite:
            append_patch_by_path("/spec/configuration/vmRolloutStrategy")
        return all_patches

    def apply(self, p):
        """
        restore by self.rc.restore()
        """
        if not p:
            LOGGER.info("Nothing to do for empty patches")
            return
        hco_patch = {
            self.hco: {
                "metadata": {
                    "annotations": {"kubevirt.kubevirt.io/jsonpatch": json.dumps(p)}
                }
            }
        }
        self.rc = ResourceEditor(hco_patch, user_backups=True)
        self.rc.update()


class OCPResource(object):
    RESOURCE_LIST = []

    def __init__(self, cls_name):
        """
        Params:
        cls_name: the class name of an OCP Resouce
        """
        self.ocp_resource_cls = cls_name
        # instance of the ocp resource
        self.ocp_resource = None
        # For patch restore manually.
        self.hco_patch = None

    def create(self, **kwargs):
        """
        Create and deploy the OCP resource
        """
        try:
            LOGGER.info(f"Creating {self.ocp_resource_cls} with kwargs: {kwargs}")
            self.ocp_resource = self.ocp_resource_cls(**kwargs)
            # if 'name' is set in kwargs, the check may be wrong
            if not self.ocp_resource.exists:
                self.ocp_resource.deploy(wait=True)
            OCPResource.RESOURCE_LIST.append(self.ocp_resource)

            return self.ocp_resource
        except Exception as e:
            LOGGER.error(f"Failed to create {self.ocp_resource_cls}: {e}")
            import traceback

            LOGGER.error(traceback.format_exc())
            raise

    @classmethod
    def clean_up(cls):
        for i in reversed(cls.RESOURCE_LIST):
            # cleanup_up of NodeNetworkConfigurationPolicy has no arguments.
            if isinstance(i, NodeNetworkConfigurationPolicy):
                i.clean_up()
            else:
                i.clean_up(wait=True)


def wait(func, timeout=TIMEOUT_4MINUTES, sleep=5, func_args=None, **kwargs):
    """
    A function can be used to keep checking something.

    Parameters
    ----------
    func: The function to do the check, it should return a Boolean value.
    func_args: The arguments of the function. It should be a tuple.
               For example, (arg1, arg2, arg3).
    """
    LOGGER.info(f"Wait {timeout} for {func} to be true")
    samples = TimeoutSampler(
        wait_timeout=timeout,
        sleep=sleep,
        func=func,
        func_args=func_args,
        **kwargs,
    )
    for sample in samples:
        if sample:
            return


class PreIntegrationTest(Test):
    """
    A derived Test class includes some public operations when
    executing a test. By this class, we can avoid duplicating
    codes.
    """

    def __init__(self, *args, **kwargs):
        self.vm_template = None
        self.test_namespace = random_rfc1123_string("autotest")
        self.template_file = "default.yml"
        self.patch_editor = None
        # aexpect sessions
        self.sessions = []
        super().__init__(*args, **kwargs)

        with open(DEFAULT_TEST_CONFIG) as fd:
            self.test_settings = yaml.safe_load(fd)

        download_cli_tools()

    def tearDown(self):
        """
        Clean up resources
        """
        for i in self.sessions:
            LOGGER.info(f"closing {i}")
            i.close()

        OCPResource.clean_up()

        if self.patch_editor:
            self.patch_editor.restore()

    def enable_featuregates(self):
        """
        Apply a patch to hco to enable feature_gates or customize virt-launcher or
        virt-handler images.
        """
        if "feature_gates" in self.vm_template.template_metadata["hco"]:
            fg_list = self.vm_template.template_metadata["hco"]["feature_gates"]
        if "customize_images" in self.vm_template.template_metadata["hco"]:
            virt_launcher = self.vm_template.template_metadata["hco"][
                "customize_images"
            ]["virt_launcher"]
            virt_handler = self.vm_template.template_metadata["hco"][
                "customize_images"
            ]["virt_handler"]
        customize_images = any([virt_launcher, virt_handler])
        self.hco_patch = PatchHCO()
        self.hco_patch.apply(
            self.hco_patch.make_patch(
                fg_list, customize_images, virt_launcher, virt_handler
            )
        )

    def load_template(self, template_file, template_metadata_file=None):
        """
        Load and parse vm template
        """
        LOGGER.info(f"Using VM template {self.template_file}")
        self.vm_template = VMTemplate(template_file, template_metadata_file)

    def create_ocp_resource(self, resource_cls, **kwargs):
        setattr(
            self,
            resource_cls.kind.lower() + "_instance",
            OCPResource(resource_cls).create(**kwargs),
        )

    def get_ocp_resource(self, resource_cls, name, namespace="default"):
        """
        Get a specified resource.
        """
        for res in resource_cls.get():
            if res.name == name and res.namespace == namespace:
                return res
        return None

    def live_migration(self, timeout=300, **kwargs):
        """
        Live migration a VM
        """
        if "vmi_name" not in kwargs or "namespace" not in kwargs:
            kwargs.update(
                {
                    "vmi_name": self.virtualmachine_instance.name,
                    "namespace": self.virtualmachine_instance.namespace,
                }
            )
        self.create_ocp_resource(
            VirtualMachineInstanceMigration,
            vmi_name=kwargs["vmi_name"],
            name=random_rfc1123_string("vmim"),
            namespace=kwargs["namespace"],
        )
        self.virtualmachineinstancemigration_instance.wait_for_status(
            status=VirtualMachineInstanceMigration.Status.SUCCEEDED, timeout=timeout
        )

    def login_vm(self, **kwargs):
        """
        Login a VM
        """

        def find_login_info():
            """
            Get login information from cloudInitNoCloud of the template.
            """
            username = password = ""
            reg = r"user:\s*(.*)\s*password:\s*(.*)"
            vols = self.vm_template.vm_dict["spec"]["template"]["spec"]["volumes"]
            for vol in vols:
                if "cloudInitNoCloud" in vol:
                    cloud_vol = vol
                    break
            found = re.search(reg, cloud_vol["cloudInitNoCloud"]["userData"])
            if found:
                username = found.group(1)
                password = found.group(2)
            return username, password

        conn = None
        vm_name = self.vm_template.vm_dict["metadata"]["name"]

        if "username" not in kwargs or "password" not in kwargs:
            username, password = find_login_info()
            kwargs.update({"username": username, "password": password})
        if "namespace" not in kwargs:
            kwargs.update({"namespace": self.test_namespace})

        for idx in range(1, 4):
            LOGGER.info(f"Trying time: {idx}")
            try:
                conn = VirtctlSSHConnect(vm_name, **kwargs)
                conn.connect()
                self.sessions.append(conn.session)
                return conn.session
            except Exception as e:
                LOGGER.info("Connect failed with VirtctlSSHConnect")
                LOGGER.warning(e)
                time.sleep(10)
        else:
            LOGGER.info("Try to use VirtctlConsoleConnect")
            conn = VirtctlConsoleConnect(vm_name, **kwargs)
            conn.connect()
            self.sessions.append(conn.session)
            return conn.session

    def cordon_uncordon_unsupported_sriov_nodes(self, cordon=None):
        """
        cordon/uncordon nodes which do not have sriov cards.
        When the VM is scheduled on node does not have sriov cards,
        it will fail when hotplug an sriov interface.
        """
        if cordon is None:
            return

        _cordon = "uncordon"
        if cordon is True:
            _cordon = "cordon"

        cmd = f"{OC_CMD} get nodes -l '!feature.node.kubernetes.io/network-sriov.configured' -o name | xargs -I {{}} oc adm {_cordon} {{}}"
        run_command(cmd, check=True)

    def create_namespace(self):
        """
        create Namespace
        """
        LOGGER.info(f"Creating namespace {self.test_namespace}")
        self.create_ocp_resource(Namespace, name=self.test_namespace)

    def create_virtualmachine(self, vm_dict, timeout=300):
        """
        Create the VM

        timeout: The value of waiting for VM creation. Default is 300s.
        """
        try:
            LOGGER.info(f"Creating VM with dict: {vm_dict}")
            self.create_ocp_resource(
                VirtualMachine,
                name=vm_dict["metadata"]["name"],
                kind_dict=vm_dict,
                namespace=self.test_namespace,
            )
            # Wait the VM to be Ready (datavolume import needs time to be ready)
            time.sleep(5)
            wait(
                lambda: self.virtualmachine_instance.printable_status == "Stopped",
                timeout=TIMEOUT_1SEC * timeout,
            )
            # Start the VM
            self.virtualmachine_instance.start(wait=True)

            # Dumpxml the XML (For Debug)
            self.virtualmachine_instance.vmi.wait_until_running()
            self.vm_xml = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
                command=["virsh", "dumpxml", "1"]
            )
            LOGGER.info(self.vm_xml)
        except Exception as e:
            LOGGER.error(f"Failed to create VM: {e}")
            import traceback

            LOGGER.error(traceback.format_exc())
            raise

    def stop_virtualmachine(self, vm=None):
        """
        Stop the VM
        """
        if not vm:
            vm = self.virtualmachine_instance
        vm.stop(wait=True)

    def start_virtualmachine(self, vm=None):
        """
        start the VM
        If no vm is provided, it uses default VM.
        """
        if not vm:
            vm = self.virtualmachine_instance
        vm.start(wait=True)

    def pause_virtualmachine(self, vm=None):
        """
        pause the VM
        """
        if not vm:
            vm = self.virtualmachine_instance
        vm.vmi.pause(wait=True)

    def resume_virtualmachine(self, vm=None):
        """
        resume the VM
        """
        if not vm:
            vm = self.virtualmachine_instance
        vm.vmi.unpause(wait=True)

    def restart_virtualmachine(self, vm=None):
        """
        restart the VM
        """
        if not vm:
            vm = self.virtualmachine_instance
        vm.restart(wait=True)

    def create_vm_snapshot(self, name, vm_name):
        """
        Create a VM Snapshot
        """
        LOGGER.info(
            f"Creating vmsnapshot {name} for VM {vm_name} in {self.test_namespace}"
        )
        self.create_ocp_resource(
            VirtualMachineSnapshot,
            name=name,
            vm_name=vm_name,
            namespace=self.test_namespace,
        )

    def restore_from_snapshot(self, name, vm_name, snapshot_name):
        self.create_ocp_resource(
            VirtualMachineRestore,
            name=name,
            vm_name=vm_name,
            snapshot_name=snapshot_name,
            namespace=self.test_namespace,
        )
        self.virtualmachinerestore_instance.wait_restore_done(timeout=TIMEOUT_10MINUTES)

    def apply_patch(self, p, backup_resources=False):
        """
        Apply the patch

        If the patch needs to be reverted after the test, you can save the return
        value to self.patch_editor. In the tearDown progress, the changes will be
        retored.
        """
        patch_editor = ResourceEditor(p)
        patch_editor.update(backup_resources=backup_resources)
        return patch_editor if backup_resources else None

    def wait_hotplug_migration(self):
        """
        Wait all vmim complete for the same vmi name because we
        are not sure which is the correct vmim for current migration.
        """
        node_before_migration = self.virtualmachine_instance.vmi.node.name
        # Wait the vmi node has changed.
        wait(
            lambda: node_before_migration != self.virtualmachine_instance.vmi.node.name
        )
        # The src and dst pod may be both running, need to wait the src
        # pod is completed.
        vmi_name = self.virtualmachine_instance.vmi.name
        vmi_namespace = self.virtualmachine_instance.vmi.namespace
        for vmim in VirtualMachineInstanceMigration.get(namespace=vmi_namespace):
            label = vmim.labels["kubevirt.io/vmi-name"]
            if vmi_name == label:
                vmim.wait_for_status(
                    status=VirtualMachineInstanceMigration.Status.SUCCEEDED
                )

    def set_default_storage_class(self):
        """
        some test scenarios require default storage class to be configrued
        e.g. vtpm persistent true
        """
        pass

    def check_contion_msg(self, msg, msg_type="RestartRequired"):
        """
        Check the contional message
        """
        return self.virtualmachine_instance.get_condition_message(msg_type) == msg

    def create_sriov_network(
        self,
        name,
        resource_name=None,
        namespace="openshift-sriov-network-operator",
        network_namespace="default",
    ):
        if not resource_name:
            sriov_net_node_policy = list(SriovNetworkNodePolicy.get())[0]
            resource_name = sriov_net_node_policy.instance.to_dict()["spec"][
                "resourceName"
            ]
        self.create_ocp_resource(
            SriovNetwork,
            name=name,
            resource_name=resource_name,
            namespace=namespace,
            network_namespace=network_namespace,
        )

    def create_bridge_network(self, nncp_name="br-net-policy", nad_name="br-nad"):
        """
        Set up a bridge network. If the NNCP or the NAD exists, it will pick them instead
        of creating a new one.
        """

        def _get_node_network_conf_policy(iface_name):
            """
            Find existing nncp policy using the target interface
            """
            for net_policy in NodeNetworkConfigurationPolicy.get():
                ifaces = net_policy.instance.to_dict()["spec"]["desiredState"][
                    "interfaces"
                ]
                if len(ifaces) == 0:
                    break
                for i in ifaces:
                    if i["type"] != "linux-bridge":
                        continue
                    for port in i["bridge"]["port"]:
                        if port["name"] == iface_name:
                            LOGGER.info(
                                f"Found existing NodeNetworkConfigurationPolicy {net_policy.name}"
                            )
                            return net_policy, i["name"]
            return None, None

        def _get_nad(br_name):
            """
            Find the nad which includes the target interface.
            """
            for nad in NetworkAttachmentDefinition.get(namespace=self.test_namespace):
                conf_dict = json.loads(nad.instance.to_dict()["spec"]["config"])
                if br_name and conf_dict.get("bridge", "") == br_name:
                    LOGGER.info(
                        f"Found existing NetworkAttachmentDefinition {nad.name}"
                    )
                    return nad.name
            return None

        iface_map = {"ocp-cluster-1": "eno3", "ocp-cluster-2": "eno8403"}

        # Check the current ocp server
        cmd = f"{OC_CMD} whoami --show-server"
        api_server_url = run_command(cmd).stdout
        if "ocp-cluster-1" in api_server_url:
            iface_name = iface_map["ocp-cluster-1"]
        elif "ocp-cluster-2" in api_server_url:
            iface_name = iface_map["ocp-cluster-2"]
        else:
            LOGGER.error(f"This case is not supported to be run on {api_server_url}")
            raise RuntimeError("unsupported ocp server")

        node_policy, br_name = _get_node_network_conf_policy(iface_name)
        if not node_policy:
            # create node_policy
            with open(BRIDGE_NNCP) as fd:
                node_policy_dict = yaml.safe_load(fd)
            node_policy_dict["metadata"]["name"] = nncp_name
            node_policy_dict["spec"]["desiredState"]["interfaces"][0]["name"] = (
                "br-test"
            )
            node_policy_dict["spec"]["desiredState"]["interfaces"][0]["bridge"]["port"][
                0
            ]["name"] = iface_name
            self.create_ocp_resource(
                NodeNetworkConfigurationPolicy,
                name=nncp_name,
                kind_dict=node_policy_dict,
            )

        target_nad_name = _get_nad(br_name)
        if not target_nad_name:
            target_nad_name = nad_name
            config_str = f'{{"cniVersion": "0.3.1", "name": "{target_nad_name}", "bridge": "{br_name}", "type": "bridge"}}'
            self.create_ocp_resource(
                NetworkAttachmentDefinition,
                name=target_nad_name,
                namespace=self.test_namespace,
                config=config_str,
            )
        return target_nad_name

    def clone_vm(self, source_name, target_name, name, namespace="default"):
        """
        Clone the VM and return the new vm object.
        """
        from ocp_resources.virtual_machine_clone import VirtualMachineClone

        self.create_ocp_resource(
            VirtualMachineClone,
            source_name=source_name,
            target_name=target_name,
            name=name,
            namespace=namespace,
        )
        self.virtualmachineclone_instance.wait_for_status(
            status=VirtualMachineClone.Status.SUCCEEDED, timeout=TIMEOUT_10MINUTES * 3
        )

        for vm in VirtualMachine.get():
            if vm.name == target_name:
                return vm

    @staticmethod
    def expose_pci_host_devs(dev_selector, resource_name):
        """
        Expose the pci device in hco
        """
        hco = list(HyperConverged.get())[0]
        try:
            pci_devs = hco.instance.to_dict()["spec"]["permittedHostDevices"][
                "pciHostDevices"
            ]
        except KeyError as e:
            LOGGER.info(f"Not found {e}")
            pci_devs = []
        for dev in pci_devs:
            if dev["pciDeviceSelector"] == dev_selector:
                LOGGER.info(
                    f"Found same device with resource name {dev['resourceName']}"
                )
                return dev["resourceName"]

        new_dev = {"pciDeviceSelector": dev_selector, "resourceName": resource_name}
        pci_devs.append(new_dev)
        p = {hco: {"spec": {"permittedHostDevices": {"pciHostDevices": pci_devs}}}}
        rc = ResourceEditor(p)
        rc.update()

    @staticmethod
    def expose_mediated_devs(dev_selector, resource_name):
        """
        Expose the mediated device in hco
        """
        hco = list(HyperConverged.get())[0]

        try:
            mediated_devs = hco.instance.to_dict()["spec"]["permittedHostDevices"][
                "mediatedDevices"
            ]
        except KeyError as e:
            LOGGER.info(f"Not found {e}")
            mediated_devs = []

        for dev in mediated_devs:
            if dev["mdevNameSelector"] == dev_selector:
                LOGGER.info(
                    f"Found same device with resource name {dev['resourceName']}"
                )
                return dev["resourceName"]

        new_dev = {"mdevNameSelector": dev_selector, "resourceName": resource_name}
        mediated_devs.append(new_dev)
        p = {
            hco: {"spec": {"permittedHostDevices": {"mediatedDevices": mediated_devs}}}
        }
        rc = ResourceEditor(p)
        rc.update()

    @staticmethod
    def check_gpu_present():
        """
        Check if GPU is present in current nodes.
        """
        from ocp_resources.node import Node

        for node in Node.get():
            if node.labels["nvidia.com/gpu.present"] == "true":
                return True
        return False


def download_cli_tools():
    """
    Download virtctl, oc.
    """
    if os.path.exists(OC_CMD) and os.path.exists(VIRTCTL_CMD):
        return

    download_urls = []
    for obj in ConsoleCLIDownload.get():
        if "oc" not in obj.name and "virtctl" not in obj.name:
            continue
        for link in obj.instance.to_dict()["spec"]["links"]:
            if "Linux for x86_64" in link["text"]:
                download_urls.append(link["href"])

    LOGGER.info("Downloading cli tools(oc, virtctl)")
    for url in download_urls:
        cmd = f"curl -k -sSL {url} -O"
        process.run(cmd, shell=True, timeout=TIMEOUT_4MINUTES)

    for pkg in ["oc.tar", "virtctl.tar.gz"]:
        with tarfile.open(pkg) as tar:
            tar.extractall(path=BIN_DIR, filter="data")


def run_command(cmd, timeout=None, check=False, capture_output=True, shell=True):
    """
    Run a local command
    """
    try:
        LOGGER.info(f"Run command:\n{cmd}")
        cmd_result = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=capture_output,
            check=check,
            shell=shell,
            text=True,
        )
        return cmd_result
    except subprocess.CalledProcessError as e:
        LOGGER.error(f"Command '{e.cmd}' returned non-zero exit status {e.returncode}")
        LOGGER.error(f"Stdout: {e.stdout}")
        LOGGER.error(f"Stderr: {e.stderr}")
        return subprocess.CompletedProcess(
            e.cmd, e.returncode, stdout="", stderr=e.stderr
        )
    except Exception as e:
        LOGGER.error(f"An unexpected error occurred: {e}")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=str(e))


def get_output(session, cmd):
    """
    Get output from an aexpect.ShellSession object (from SSH or console connection).
    """
    return get_clean_output(session, cmd)
