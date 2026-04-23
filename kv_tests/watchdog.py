import aexpect
import xml.etree.ElementTree as ET

from utils.kubevirt import PreIntegrationTest, wait
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)


class WatchdogTest(PreIntegrationTest):
    def setUp(self):
        super().setUp()
        # VM template file
        self.template_file = "watchdog.yml"
        self.load_template(self.template_file)

        self.create_namespace()

    def trigger_watchdog(self, session):
        """
        trigger watchdog event
        """
        cmd = "sudo echo 1 > /dev/watchdog"
        session.cmd_status(cmd)

    def check_watchdog(self):
        xml = self.virtualmachine_instance.vmi.virt_launcher_pod.execute(
            command=["virsh", "dumpxml", "1"]
        )
        root = ET.fromstring(xml)
        self.assertTrue(root.find(".//watchdog[@model='i6300esb']") is not None)

    def test_watchdog_poweroff(self):
        """
        Test watchdog with action 'poweroff'
        """
        vm_dict = self.vm_template.vm_dict
        self.create_virtualmachine(vm_dict)
        self.check_watchdog()

        session = self.login_vm(username="root", password="123456")
        self.trigger_watchdog(session)

        # check vm is stop status
        wait(
            lambda: (
                self.virtualmachine_instance.instance.status["printableStatus"]
                == "Stopped"
            )
        )

    def test_watchdog_reset(self):
        """
        Test watchdog with action 'reset'
        """

        def _wait_reset(session):
            """
            when the VM has been reset, the session command will raise
            ShellTimeoutError because the PROMPT can not be matched.
            """
            if not session.is_alive():
                return True
            try:
                session.cmd_output("pwd", timeout=5)
            except aexpect.exceptions.ShellTimeoutError:
                return True
            return False

        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["template"]["spec"]["domain"]["devices"]["watchdog"][
            "i6300esb"
        ]["action"] = "reset"
        self.create_virtualmachine(vm_dict)
        self.check_watchdog()

        session = self.login_vm(username="root", password="123456")
        uptime_before_reset = session.cmd_output("uptime -s").strip()
        self.assertTrue(uptime_before_reset)

        self.trigger_watchdog(session)
        # wait the vm reboots
        wait(_wait_reset, sleep=10, func_args=(session,))
        # relogin the vm
        session = self.login_vm(username="root", password="123456")
        # check the uptime has changed after reset
        wait(lambda: session.cmd_output("uptime -s").strip() != uptime_before_reset)

    def test_watchdog_shutdown(self):
        """
        Test watchdog with action 'shutdown'
        """
        vm_dict = self.vm_template.vm_dict
        vm_dict["spec"]["template"]["spec"]["domain"]["devices"]["watchdog"][
            "i6300esb"
        ]["action"] = "shutdown"
        self.create_virtualmachine(vm_dict)
        self.check_watchdog()

        session = self.login_vm(username="root", password="123456")
        self.trigger_watchdog(session)

        # check vm is stop status
        wait(
            lambda: (
                self.virtualmachine_instance.instance.status["printableStatus"]
                == "Stopped"
            )
        )


# For debugging
if __name__ == "__main__":
    import unittest

    unittest.main()
