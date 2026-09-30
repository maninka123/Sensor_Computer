# Spinnaker SDK for this workspace

The ROCK 5A used to develop and benchmark this repository runs **Spinnaker
4.2.0.46, ARM64, Ubuntu 20.04**. Install the matching SDK **before** running
`setup_workspace.sh`; the build checks both `libspinnaker` and
`libspinnaker-dev` and refuses a different version. Do not copy `build/` or
`devel/` from another computer.

The SDK is Teledyne software, not project source code. Download the
architecture-matched **4.2.0.46** package from the
[official Spinnaker SDK page](https://www.teledynevisionsolutions.com/products/spinnaker-sdk/)
under its own licence. SDK archives and unpacked vendor packages are not kept
in this repository. On a ROCK 5A, obtain the ARM64 Ubuntu 20.04 archive named
`spinnaker-4.2.0.46-arm64-20.04-pkg.tar.gz` and install it as follows:

```bash
cd ~/Downloads
tar -xzf spinnaker-4.2.0.46-arm64-20.04-pkg.tar.gz
cd spinnaker-4.2.0.46-arm64
sudo ./install_spinnaker_arm.sh
dpkg-query -W -f='${Package} ${Version} ${Architecture}\n' libspinnaker libspinnaker-dev
```

The original archive used on this ROCK 5A has SHA-256
`eecb76b88c645daf1b61d7e763da4d8d766f68e536e709e4c1ccb590d21bce8c`.
Check your download with `sha256sum` if it is the same vendor archive. For an
AMD64 sensor computer, obtain the **AMD64 4.2.0.46** package from Teledyne and
follow its included installer instructions; never install an AMD64 package on
the ROCK 5A.

The repository's camera changes are in the ROS driver at
`src/flir_camera_driver/spinnaker_camera_driver/` and the pipeline's launch and
configuration files. **No vendor SDK source code was modified.** The ROS
driver now requires an installed SDK and will not fetch a mismatched fallback.
See [LOCAL_SETUP.md](../LOCAL_SETUP.md) and the
[multi-device guide](../docs/MULTI_DEVICE_DEPLOYMENT.md) for sensor IP and
serial-number setup.
