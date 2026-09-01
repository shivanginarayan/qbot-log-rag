"""Read the shared ROS domain ID without duplicating its value in Python."""

from pathlib import Path


CONSTANTS_FILE = Path(__file__).with_name("ros_domain_constants.sh")
CONSTANT_NAME = "QBOT_ROS_DOMAIN_ID"


def get_ros_domain_id() -> int:
    """Return the ROS domain ID configured in ``ros_domain_constants.sh``."""
    prefix = f"{CONSTANT_NAME}="
    for line in CONSTANTS_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return int(line[len(prefix):])
    raise RuntimeError(f"{CONSTANT_NAME} is missing from {CONSTANTS_FILE}")
