#!/usr/bin/env python3
"""Log and validate the address this ROS process advertises."""

import ipaddress
import os

import rosgraph.network
import rospy


def main():
    rospy.init_node("network_config_check")
    configured = os.environ.get("ROS_IP", "")
    advertised = rosgraph.network.get_host_name()
    master_uri = os.environ.get("ROS_MASTER_URI", "")

    rospy.loginfo(
        "ROS networking: advertised address=%s, ROS_IP=%s, Master=%s",
        advertised,
        configured or "<unset>",
        master_uri or "<unset>",
    )

    try:
        address = ipaddress.ip_address(advertised)
    except ValueError:
        rospy.logerr(
            "NETWORK CONFIGURATION WARNING: advertised ROS address '%s' is a "
            "hostname, not a literal IPv4 address. Native subscribers may "
            "register but receive no data.",
            advertised,
        )
        return

    if address.version != 4:
        rospy.logerr(
            "NETWORK CONFIGURATION WARNING: advertised ROS address '%s' is "
            "not IPv4; this deployment requires a literal IPv4 address.",
            advertised,
        )
    elif address.is_loopback:
        rospy.logerr(
            "NETWORK CONFIGURATION WARNING: advertised ROS address '%s' is "
            "loopback. Remote TCPROS subscribers cannot connect to it.",
            advertised,
        )
    elif advertised not in rosgraph.network.get_local_addresses():
        rospy.logerr(
            "NETWORK CONFIGURATION WARNING: advertised ROS address '%s' is "
            "not assigned to a local interface. Check the static address or "
            "DHCP reservation.",
            advertised,
        )


if __name__ == "__main__":
    main()
