# LXD Cross-Node Ops, Shared Storage, and Hang Traps

Field notes from operating a two-node LXD cluster (4090 / v100) with an NFS share. Covers
cross-node container configuration, LXD command hangs, device-node mount confusion, NFS
location discovery, and mounting shared storage into containers.

## Known environment

- LXD cluster: `4090` (192.168.5.160, database-leader) and `v100` (192.168.5.161,
  database-standby). Both mount the same NFS share.
- NFS server: `storage` (192.168.5.115), exports `/data/share` (2.5TB disk) to `*`.
  Mounted at `/file` on both 4090 and v100 (`fstab`: `192.168.5.115:/data/share /file nfs`).
- Container `ft3` lives on `4090`; container `ft3-v100` lives on `v100`.

## Cross-node container operations

- An instance belongs to exactly one node. Discover it with:

  ```sh
  lxc list -c nsL
  ```

- `lxc stop` / `lxc delete` / `lxc restart` route by instance name; no `--target` flag
  (and they do NOT accept one — adding `--target` errors with `unknown flag`).
- `lxc config device add` also has **no `--target`**. Configure a device from the shell of
  the node that owns the instance (or run it on that node), not from the cluster leader.
- `lxc init` / `lxc create` / `lxc image` DO support `--target <node>`.

## LXD command hangs (timeouts that are not failures)

- Large image create/restart often exceeds the MCP tool's 30s timeout, but the operation
  keeps running server-side. When a command times out:
  1. Check pending work: `lxc operation list` (a `TASK ... Creating instance` still
     `RUNNING` means it is just slow).
  2. Check the instance: `lxc list <name> -c nsL` — it may already be STOPPED/created.
  3. Re-issue the slow command alone with a larger tool timeout, not chained with others.
- `lxc exec <ct> -- <cmd>` can hang for a long time on some containers. Wrap with
  `timeout 15 lxc exec ...` and run one command at a time. If it still hangs, verify the
  instance is alive via `lxc info <ct>` before retrying.

## Device-node mount confusion (privileged containers)

- In a privileged LXD container with GPU passthrough, `df -hT` may show the **host's**
  data disk (e.g. btrfs `1007G`) mounted at GPU device-node paths such as `/dev/nvidia0`,
  `/dev/nvidiactl`, `/dev/dri/card0`. This is a bind/overlay artifact of the `gpu` device —
  those paths are still character devices, NOT directories.
- Consequence: you cannot `cd /dev/nvidia0` or write files there, and the host disk is NOT a
  usable storage location inside the container even though `df` lists it.
- Do not assume storage from `df` alone in a privileged container. Verify with:

  ```sh
  ls -ld /dev/nvidia0                 # shows crw-rw-rw- (char device), not drwx
  touch /dev/nvidia0/.t && echo writable || echo not-writable
  ```

- The container's real writable storage is its root disk (e.g. `/dev/loop10` btrfs 30G).
  For large models use an NFS share or a properly configured LXD disk device instead.

## NFS share location discovery

1. On the client: `mount | grep nfs` and `grep nfs /etc/fstab` reveal `server:/export`.
2. Confirm the export: `showmount -e <server>`.
3. Identify the server node via `ssh_connect` (host + user + password from saved config or
   the user). Do NOT pipe the password into `ssh` on the remote shell —
   `echo pwd | ssh ...` hangs at the interactive password prompt. Use the mcpterminal
   `ssh_connect(host=..., user=..., password=...)` tool instead.
4. On the storage host, `df -hT /data` and `lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT` show the
   physical disk and free space.

## Mount an NFS subdir into containers (LXD disk device)

Bind the host's already-mounted NFS path into the container:

```sh
# run on the node that owns the container
lxc config device add <ct> <name> disk source=/file/fuzihan path=/file/fuzihan
lxc restart <ct>          # device mounts apply on restart
lxc exec <ct> -- df -hT /file/fuzihan
lxc exec <ct> -- touch /file/fuzihan/.write_test   # confirm writable
```

- One device per node: `ft3` on 4090 and `ft3-v100` on v100 each need their own device
  added from their own node's shell.
- The device persists across container restarts (it is part of the container config).

## Interactive installer traps (example: 1Panel)

- Non-TTY `echo "x" | installer` often fails with `inappropriate ioctl for device` because
  the prompt reads from the terminal. Feed input through a PTY:

  ```sh
  printf "answer1\nanswer2\n" | script -qec "/path/to/installer" /dev/null
  ```

  Match the exact number of inputs to the prompts (extra/missing lines cause
  "mismatch" errors).
- For 1Panel specifically:
  - Username and security entrance are stored as plaintext in the SQLite
    `settings` table (`1Panel.db`): keys `UserName`, `SecurityEntrance`. The user-facing
    password is an encrypted ciphertext and must NOT be edited directly.
  - Change the password via `1pctl update password` (interactive, uses a PTY), or
    `1pctl update username` for the username.
  - `1pctl restart` afterwards, then verify the new security entrance returns the app
    loading page while an old/wrong entrance returns a "temporarily unavailable" page
    (raw HTTP 200 is NOT enough to distinguish them).
- 1Panel's install script only skips Docker Compose download if `docker-compose` (dash
  form) resolves; `docker compose` (space form) does not satisfy it. Install
  `docker-compose-v2` and symlink it to `/usr/local/bin/docker-compose` before installing
  1Panel to avoid a hung GitHub download.

## Remote access reminders

- Restarting the GUI drops all SSH sessions; re-run `launch_gui` then `ssh_connect`
  / `ssh_connect_from_config` afterwards. Config aliases: `workstation`
  (fuzihan@100.64.0.13), `workstation-root`, `v100` (user@100.64.0.42), `v100-root`.
- `ssh_exec` with a `password`-style prompt needs the password fed via
  `echo 'password' | sudo -S -k -p '' <cmd>`; `sudo` without `-S` hangs waiting on a tty.
