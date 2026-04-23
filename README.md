# Automation Testing for OpenShift Virtualization

This repository contains an automated test suite for OpenShift Virtualization. It uses the [Avocado Framework](https://avocado-framework.readthedocs.io/) to orchestrate tests that create, modify, and delete virtualized resources within an OpenShift cluster.

## Table of Contents

- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
  - [Listing Test Cases](#listing-test-cases)
  - [Running a Specific Test Case](#running-a-specific-test-case)
  - [Running Tests in Parallel](#running-tests-in-parallel)
- [Adding a New Test Case](#adding-a-new-test-case)
- [Configuration](#configuration)
  - [Enabling Feature Gates](#enabling-feature-gates)
- [Debugging](#debugging)
- [Code Style](#code-style)
- [Updating virt-launcher/handler Images](#updating-virt-launcherhandler-images)
- [License](#license)

## Getting Started

### Prerequisites

- An accessible OpenShift cluster with OpenShift Virtualization installed.
- Python 3.6+
- pip
- git

### Installation

1.  Clone the repository:

    ```bash
    git clone <your-git-repo-url>
    cd kv-test/
    ```

2.  Install the required dependencies:

    ```bash
    pip install -r requirements.txt
    ```

## Project Structure

The repository is organized into the following key directories:

-   `kv_tests/`: Contains all the test scripts, organized into modules by the feature they test (e.g., `storage.py`, `network.py`, `gpu.py`).
-   `templates/`: Contains Jinja2 templates used to generate the Kubernetes/OpenShift YAML manifests for the resources needed by the tests.
-   `bin/`: Contains command-line tools like `oc` (OpenShift CLI) and `virtctl` (KubeVirt CLI) for interacting with the cluster.
-   `kv_tests/configs/`: Contains configuration files for the tests, such as `default.yml`.

## Running Tests

### Listing Test Cases

To see a list of all available test cases, run the following command:

```bash
avocado list kv_tests/
```

### Running a Specific Test Case

Before running a test, make sure you have configured your `KUBECONFIG` environment variable or are logged into the OpenShift cluster using `oc`.

To run a specific test case, use the `avocado run` command, followed by the test case name.

For example:

```bash
export KUBECONFIG=<path_to_your_kubeconfig>
avocado run kv_tests/virtiofs_configvolumes.py:VirtiofsTest.test_secret
```

### Running Test Cases in Container
For some systems which doesn't support setting the envrionment directly on the host, you
can build a container image in the Dockerfile.

```bash
podman run -it \
-e KUBECONFIG=env/<ocp-server>/<cluster-name>/auth/kubeconfig \
--privileged --rm \
-v /root/avocado/:/root/avocado \
-v .:/kubevirt-test quay.io/wxdwindy/fedora_42:latest \
avocado run --max-parallel-tasks=1 kv_tests/vtpm.py:VTPMTest.test_vtpm_persistent_true
```

### Running Tests in Parallel

Avocado may run multiple tests in parallel if their names are similar. For example, running `avocado run xxx:test_fun` will also run `test_fun_1` and `test_fun_2`.

To avoid this, you can either:

-   **Disable parallel execution:**

    ```bash
    avocado run --max-parallel-tasks=1 <test_name>
    ```

-   **Use more specific test names.**

## Adding a New Test Case

The test cases in this project are based on Python's `unittest` framework. To add a new test case, you can create a new Python file in the `kv_tests/` directory and define a new test class that inherits from `unittest.TestCase`.

The VM templates are based on the Jinja2 templating engine. You can find more information about Jinja2 in the [official documentation](https://jinja.palletsprojects.com/en/latest/templates/#template-designer-documentation).

## Configuration

### Enabling Feature Gates

You can enable feature gates by adding them to the `kv_tests/configs/default.yml` file.

## Debugging

You can debug the test scripts using `pdb`.

### Method 1: Using `pdb` with a modified script

1.  Create a copy of the test script you want to debug.
2.  In the copied script, remove or comment out all test cases except the one you want to debug.
3.  Add the following code to the end of the script:

    ```python
    if __name__ == "__main__":
        import unittest
        unittest.main()
    ```

4.  Run the script with `pdb`:

    ```bash
    python -m pdb kv_tests/<your_test_script>.py
    ```

### Method 2: Using `breakpoint()`

1.  Add a `breakpoint()` call in your test script at the line where you want to start debugging.
2.  Run the specific test method using the following command:

    ```bash
    cd kv_tests
    python -m unittest <test_module>.<TestClass>.<test_method>
    ```

    For example:

    ```bash
    python -m unittest virtiofs_configvolumes.VirtiofsTest.test_secret
    ```

## Code Style

This project uses `autopep8` to enforce a consistent code style. To format your code, run the following command:

```bash
autopep8 --in-place --aggressive --aggressive -r --exclude templates --exclude README.md .
```

## Updating virt-launcher/handler Images

This section describes how to update the `virt-launcher` and `virt-handler` container images with new packages.

**Quick Start with Makefile:**

```bash
# Show all available options
make help

# Build both images
make build-both \
  VIRT_LAUNCHER_BASE="<registry>/kubevirt/virt-launcher-rhel9:<tag>" \
  VIRT_HANDLER_BASE="<registry>/kubevirt/virt-handler-rhel9:<tag>" \
  QEMU_VERSION="8.2.0-10.el9" \
  LIBVIRT_VERSION="10.0.0-6.el9"
```

See [REBUILD_IMAGES.md](REBUILD_IMAGES.md) for complete documentation.

**Manual Steps:**

1.  **Find the image URL:**

    -   virt-launcher-rhel9-container: <image-url>
    -   virt-handler-rhel9-container: <image-url>

2.  **Pull the image:**

    ```bash
    podman pull <image_url>
    ```

3.  **Run the image and get a shell:**

    ```bash
    podman run --entrypoint /bin/sh -it <image>
    ```

4.  **Create a `rhel.repo` file in `/etc/yum.repos.d/`** with the following content:

    ```repo
    [BaseOS]
    baseurl = <url>
    enabled = 1
    gpgcheck = 0
    name = <RHEL-9.7-BaseOS>

    [AppStream]
    baseurl = <url>
    enabled = 1
    gpgcheck = 0
    name = <RHEL-9.7-AppStream>
    ```

5.  **Upgrade the packages:**

    ```bash
    dnf upgrade --refresh --skip-broken
    ```

    If you encounter GPG key errors, identify and remove the problematic keys:

    ```bash
    # List all GPG keys to identify the problematic one
    rpm -q gpg-pubkey --qf '%{NAME}-%{VERSION}-%{RELEASE}\t%{SUMMARY}\n'
    
    # Remove the specific key mentioned in the error message
    rpm --erase gpg-pubkey-<version>-<release>
    ```

    If you see repository metadata download errors, disable the problematic repo:
    ```bash
    # Error: Failed to download metadata for repo 'rhel-9-for-x86_64-appstream-rpms'
    # Solution: Use dnf with --disablerepo option or remove the repo file
    ```

6.  **Update permissions (for virt-launcher image only):**

    ```bash
    chmod o+rx /etc/libvirt
    ```

7.  **Commit the changes to a new image:**

    ```bash
    # Get the container ID
    podman ps -a

    # Commit the changes
    podman commit -c 'ENTRYPOINT=["/usr/bin/virt-launcher-monitor"]' <container_id> quay.io/wxdwindy/virt-launcher-rhel9:<tag>

    # For virt-handler, the entrypoint is /usr/bin/virt-handler
    ```

8.  **Push the new image to a container registry:**

    ```bash
    podman push quay.io/wxdwindy/virt-launcher-rhel9:<tag>
    ```

Noted: You can find the official docker file in the kubevirt repository. If some steps changed in future, you should follow the new steps to modify your container.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
