# Use the official Fedora 42 image as the base.
# The 'latest' tag often points to the latest stable release (currently 42).
FROM fedora:42

# Set the maintainer/author of the image (optional but recommended)
LABEL maintainer="xiaodwan@example.com"

# Update the package repository and install a sample package (e.g., 'git')
# The 'dnf clean all' step reduces the final image size by removing cached files.
# The \ at the end of a line is used for line continuation in Dockerfile.
RUN dnf update -y && \
    dnf install -y ssh python3 python3-pip && \
    dnf clean all

WORKDIR /pre-integration
COPY requirements.txt .

RUN pip3 install --no-cache-dir -r requirements.txt

# Define the default command to run when the container starts.
# This example simply starts a shell. Replace with your application's entry point.
CMD ["/bin/bash"]
