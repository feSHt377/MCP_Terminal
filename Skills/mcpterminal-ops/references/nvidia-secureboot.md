# NVIDIA GPU Driver Fails to Load Under Secure Boot

Recovery for a Secure Boot host where the NVIDIA kernel module is signed with an un-enrolled
MOK key, so the kernel rejects it and `nvidia-smi` cannot talk to the driver. Remote-only
(no MOK blue-screen access): fix is purely software, no reboot, by switching to Ubuntu's
prebuilt Canonical-signed modules.

## Known environment

- Host: Ubuntu 22.04, HWE kernel `6.8.0-136-generic`, Secure Boot enabled (e.g. a VMware
  Workstation VM, `VMware20,1`). Example: `v100` (Tesla V100-PCIE-16GB).
- Symptom: `nvidia-smi` reports
  `NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver`.
- Root cause: DKMS compiled the module and signed it with the host-local MOK key
  (`/var/lib/shim-signed/mok/MOK.der`), but that key was never enrolled through the MOK
  management screen. Secure Boot therefore rejects the module:
  `modprobe: ERROR: could not insert 'nvidia': Key was rejected by service`
  (older kernels: `Operation not permitted`).

## Discovery sequence

Run each command separately and wait for its result.

1. Confirm Secure Boot is on and we are in EFI mode:

   ```sh
   mokutil --sb-state
   [ -d /sys/firmware/efi ] && echo EFI
   ```

2. Find which signature signed the loaded candidate module:

   ```sh
   MOD=/lib/modules/$(uname -r)/updates/dkms/nvidia.ko
   modinfo "$MOD" | grep -E "signer|vermagic"
   ```

   - `signer: <hostname> Secure Boot Module Signature key` → DKMS/MOK signed, the failing case.
   - `signer: Canonical Ltd. Kernel Module Signing` → Ubuntu official, Secure Boot trusts it.

3. Check whether the MOK key is actually enrolled:

   ```sh
   sudo mokutil --test-key /var/lib/shim-signed/mok/MOK.der
   # "is not enrolled" -> the failing case; "is already in the enrollment request" -> pending
   ```

4. Confirm the Canonical CA is already trusted, which is what makes the official modules usable:

   ```sh
   sudo mokutil --list-enrolled | grep -i canonical
   ```

5. Verify the target driver version supports the GPU, and that an official signed module
   package exists for the running kernel:

   ```sh
   apt-cache search linux-modules-nvidia-580 | grep 6.8.0-136
   # Tesla V100-PCIE-16GB is supported by 580.173.02 (PCI ID 1DB4).
   ```

## Fix procedure (remote, no reboot)

1. Install the driver and the official prebuilt module package. Do NOT use
   `--no-install-recommends`, it skips selection of the signed modules:

   ```sh
   sudo apt-get update
   sudo apt-get install -y nvidia-driver-580 linux-modules-nvidia-580-$(uname -r | sed 's/-generic//')
   ```

2. Remove the DKMS-built MOK-signed modules so they no longer shadow the official ones:

   ```sh
   sudo dkms remove nvidia/580.173.02 -k $(uname -r)
   sudo depmod -a
   ```

   After removal, `modinfo nvidia` must point at the official module
   (`.../kernel/nvidia-580/nvidia.ko`, signer `Canonical Ltd. Kernel Module Signing`).

3. Load and verify:

   ```sh
   sudo modprobe nvidia
   nvidia-smi
   ```

   Expected: driver loads, GPU (e.g. `Tesla V100-PCIE-16GB`) listed with correct memory.

## Response to failures

- **`modprobe` still reports `Key was rejected by service`:** the MOK-signed module is still
  being selected. Re-run `dkms remove` for that driver/version/kernel and `depmod -a`, then
  confirm `modinfo nvidia` shows the Canonical signer before loading.
- **`modprobe /path/to/nvidia.ko` → `FATAL ... not found`:** modprobe does not accept a .ko
  path. Fix `modules.dep` (via the `dkms remove` + `depmod -a` step above) and use bare
  `modprobe nvidia`.
- **MOK import appears to succeed but nothing changes after reboot:** `mokutil --import`
  only queues the key; it must be confirmed in the MOK management screen during reboot.
  With no console access this path is a dead end — use the Canonical-signed modules instead.
- **Official module package missing for the running kernel:** check the HWE flavor or
  consider a kernel already covered by `linux-modules-nvidia-<ver>-<kernel>`. Do not guess a
  package name; read it from `apt-cache search`.
