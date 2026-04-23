import os
import os.path

ROOT_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), "../.."))
BIN_DIR = os.path.join(ROOT_PATH, "bin")
OC_CMD = os.path.join(BIN_DIR, "oc")
VIRTCTL_CMD = os.path.join(BIN_DIR, "virtctl")

TEST_CONFIG_DIR = os.path.join(ROOT_PATH, "kv_tests/configs")
DEFAULT_TEST_CONFIG = os.path.join(TEST_CONFIG_DIR, "default.yml")
BRIDGE_NNCP = os.path.join(TEST_CONFIG_DIR, "bridge_NodeNetworkConfigurationPolicy.yml")
