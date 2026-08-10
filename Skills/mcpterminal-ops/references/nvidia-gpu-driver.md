# NVIDIA GPU Driver Version Alignment (LXD Container)

Align the NVIDIA user-space driver inside an LXD container with the host kernel driver version. A mismatch shows up as `Failed to initialize NVML: Driver/library version mismatch` inside the container even though `nvidia-smi` works on the host.

## Known environment

- Host: NVIDIA driver installed via Ubuntu kernel module, version e.g. `580.173.02`, CUDA `13.0`.
- Container: Ubuntu 24.04, GPU passed through, NVIDIA user-space packages installed from Ubuntu noble repositories (`noble-updates` / `noble-security`).
- Symptom: `lxc exec <container> -- nvidia-smi` reports
  `Failed to initialize NVML: Driver/library version mismatch` and `NVML library version: <old-version>`.

## Discovery sequence

Run each command separately and wait for its result.

1. Get the host driver version (the target version):

   ```sh
   nvidia-smi
   ```

2. Confirm the container exists and its current status:

   ```sh
   lxc list
   ```

3. Confirm the mismatch inside the container:

   ```sh
   lxc exec <container> -- nvidia-smi
   ```

4. Inspect installed NVIDIA packages and versions:

   ```sh
   lxc exec <container> -- bash -c 'dpkg -l | grep -i nvidia'
   ```

   A container may have mixed generations (e.g. `535` and `580`). The generation that matters is the one matching the host major version (e.g. `580`).

5. Check the available candidate version from apt. The candidate must match the host driver version exactly:

   ```sh
   lxc exec <container> -- bash -c 'apt-cache policy nvidia-utils-580 | head -20'
   ```

   If the candidate equals the host version, upgrade in place is sufficient. Do not guess the package version; read it from `apt-cache policy`.

## Upgrade procedure (interactive, visible to the user)

Run inside the container so the user can watch progress in the GUI terminal.

1. Enter the container shell in interactive mode:

   ```
   lxc exec <container> -- bash
   ```

2. Refresh package lists:

   ```sh
   apt-get update
   ```

3. List upgradable NVIDIA packages to confirm the exact target version:

   ```sh
   apt list --upgradable | grep -i nvidia
   ```

4. Upgrade the packages matching the host driver generation (e.g. `580`):

   ```sh
   apt-get install --only-upgrade nvidia-utils-580 libnvidia-compute-580 nvidia-kernel-common-580 -y
   ```

   Notes:
   - Do NOT include a bare `nvidia-firmware-580` in the package list; the firmware package name carries the version suffix (e.g. `nvidia-firmware-580-580.173.02`) and is pulled in automatically as a new dependency.
   - Leave the old-generation packages (e.g. `535`) untouched; only align the generation that matches the host.
   - `apt-get install --only-upgrade` is preferable to `apt-get upgrade` because it upgrades only the named packages without dragging in unrelated updates.

5. Verify the alignment:

   ```sh
   nvidia-smi
   ```

   Expected result inside the container: `Driver Version` matches the host version, GPU (e.g. RTX 4090) is listed, and no NVML mismatch error remains.

6. Exit the container shell:

   ```sh
   exit
   ```

## Response to failures

- **`E: Unable to locate package`:** the package name is wrong or carries a version suffix. Re-run `apt list --upgradable | grep -i nvidia` and use only names printed there.
- **Candidate version differs from host:** do not install. Stop and report the version gap; the host module may need to be upgraded first or the apt mirror may be stale.
- **`Driver/library version mismatch` persists after upgrade:** verify the upgraded `.deb` actually unpacked (compare the installed `libnvidia-ml.so.*` file version), then check for a pending container restart or a stray second NVIDIA installation.
