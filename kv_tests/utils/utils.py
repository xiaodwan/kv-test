import string
import re
import random
import aexpect

from utils.constants import VIRTCTL_CMD
from simple_logger.logger import get_logger
from aexpect.remote import handle_prompts
from shutil import which


LOGGER = get_logger(name=__name__)


class UtilityNotFoundError(Exception):
    """Exception raised when a utility for connecting to a VM is not found."""

    def __init__(self, msg=None):
        if not msg:
            msg = "No available utility for connecting to a VM"
        super().__init__(msg)
        self.msg = msg

    def __str__(self):
        return self.msg


class ArgumentsError(Exception):
    """Exception raised for invalid arguments."""

    def __init__(self, msg=None, reason=""):
        if not msg:
            msg = "invalid arguments: "
        super().__init__(msg)
        self.msg = msg + reason

    def __str__(self):
        return self.msg


class BaseConnect(object):
    """Base class for connecting to a VM."""

    def connect(self):
        raise NotImplementedError


class VirtctlSSHConnect(BaseConnect):
    """Connect to a VM using 'virtctl ssh'."""

    def __init__(
            self,
            vmname,
            username=None,
            password=None,
            namespace=None,
            cmd=None,
            kind="vm",
            sshopts="-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no",
            port=22):
        """Initializes the VirtctlSSHConnect object.

        Args:
            vmname: The name of the VM.
            username: The username to log in to the VM.
            password: The password to log in to the VM.
            namespace: The namespace of the VM.
            cmd: A custom command to connect to the VM. If not provided, a
                command will be generated automatically.
            kind: The resource type, either "vm" or "vmi".
            sshopts: SSH options to use when connecting.
            port: The SSH port to connect to.
        """

        if not cmd and (not username or not password):
            raise ArgumentsError(
                "username and password or cmd should be provided")
        if kind not in ["vm", "vmi"]:
            reason = f"kind '{kind}' should be 'vm' or 'vmi'."
            raise ArgumentsError(reason=reason)
        super().__init__()
        self.session = None
        self.username = username
        self.password = password
        self.vmname = vmname
        self.namespace = namespace
        self.kind = kind
        self.sshopts = sshopts
        self.port = port
        self.ssh_command = cmd

    @property
    def ssh_command(self):
        return self._command

    @ssh_command.setter
    def ssh_command(self, cmd=None):
        if cmd:
            self._command = cmd
            return

        cmd_parts = []
        if which("sshpass"):
            cmd_parts.append(f"sshpass -p {self.password}")

        cmd_parts.append(f"{VIRTCTL_CMD} ssh")

        if self.sshopts:
            cmd_parts.append(f"-t '{self.sshopts}'")
        if self.port != 22:
            cmd_parts.append(f"-p {self.port}")
        if self.namespace:
            cmd_parts.append(f"--namespace={self.namespace}")

        cmd_parts.append(f"{self.username}@{self.kind}/{self.vmname}")
        self._command = " ".join(cmd_parts)

    def connect(self):
        """Connects to the VM.

        Note that the connect may fail due to the vm is in booting stage.
        Users should take care of the situation.

        Returns:
            aexpect.ShellSession: A shell session to the VM.
        """
        def _connect():
            LOGGER.info(f"Logging with {self.ssh_command}")
            self.session = aexpect.ShellSession(self.ssh_command)
            handle_prompts(
                self.session,
                self.username,
                self.password,
                timeout=60)
            return self.session

        try:
            return _connect()
        except aexpect.remote.LoginProcessTerminatedError as e:
            # sshpass may fail and we try again without sshpass
            if "Host key verification failed" in e.output and 'sshpass' in self.ssh_command:
                self.ssh_command = ' '.join(self.ssh_command.split()[3:])
                LOGGER.info(f"Retry without sshpass")
                return _connect()
            else:
                raise
        except aexpect.ExpectError as e:
            LOGGER.error(f"Failed to connect to VM: {e}")
            raise


class VirtctlConsoleConnect(BaseConnect):
    """Connect to a VM using 'virtctl console'."""

    def __init__(self, vmname, username=None, password=None, namespace=None):
        """Initializes the VirtctlConsoleConnect object.

        Args:
            vmname: The name of the VM.
            username: The username to log in to the VM.
            password: The password to log in to the VM.
            namespace: The namespace of the VM.
        """
        super().__init__()
        self.vmname = vmname
        self.username = username
        self.password = password
        self.namespace = namespace if namespace else "default"
        self.session = None

    def connect(self):
        """Connects to the VM.

        Returns:
            aexpect.ShellSession: A shell session to the VM.
        """
        command = f"{VIRTCTL_CMD} console {self.vmname} -n {self.namespace}"
        LOGGER.info(f"Logging with {command}")
        PROMPT = r"\[.*[#$]\s*$"
        self.session = aexpect.ShellSession(command, prompt=PROMPT)
        handle_prompts(self.session, self.username,
                       self.password, prompt=PROMPT,
                       timeout=60)
        # without this line, funcs like cmd_output will fail
        self.session.set_prompt(PROMPT)


def escape_ansi(c):
    """Removes ANSI escape sequences from a string.

    Args:
        c: The string to remove ANSI escape sequences from.

    Returns:
        The string with ANSI escape sequences removed.
    """
    # https://stackoverflow.com/questions/14693701/how-can-i-remove-the-ansi-escape-sequences-from-a-string-in-python
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', c)


def get_clean_output(session, cmd):
    """Execute a command and return cleaned output without shell escape sequences.

    This function removes unexpected escape sequences that may appear in the output
    from both SSH and console sessions:
    - Bracketed paste mode sequences (\x1b[?2004l/h)
    - systemd OSC 3008/8003 context signalling sequences

    Args:
        session: An aexpect.ShellSession object (from SSH or console connection).
        cmd: The command to execute.

    Returns:
        The command output with escape sequences removed.
    """
    output = session.cmd_output(cmd)

    # Remove bracketed paste mode sequences
    output = re.sub(r'\x1b\[\?2004[lh]', '', output)

    # Remove OSC sequences (e.g., OSC 3008/8003 for systemd context signalling)
    # OSC sequences can be terminated with either \x1b\\ (ESC \) or \x07 (BEL)
    output = re.sub(r'\x1b\]\d+;[^\x1b\x07]*(?:\x1b\\|\x07)', '', output)

    return output


def random_rfc1123_string(s, n=5):
    """Generates a random RFC1123 compliant string.

    Args:
        s: The string to append a random string to.
        n: The length of the random string.

    Returns:
        A random RFC1123 compliant string.
    """
    s += '-' + \
        ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))
    return s.lower().replace("_", "-")
