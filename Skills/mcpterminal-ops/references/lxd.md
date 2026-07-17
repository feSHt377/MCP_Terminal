# LXD Operations

Use this workflow to prevent repeated malformed commands and guessed image references.

## Discover the environment

Run each command separately and wait for its result:

1. Confirm that the client exists:

   ```sh
   command -v lxc && lxc version
   ```

2. Discover configured remotes:

   ```sh
   lxc remote list
   ```

3. Select only a remote name present in that output. Do not assume that `images`, `ubuntu`, or `ubuntu-minimal` is configured.

## Find an image

Use the remote followed by a colon:

```sh
lxc image list <remote>:
```

Add a separate filter only after confirming the remote:

```sh
lxc image list <remote>: <filter>
```

Inspect a selected alias or fingerprint before launch:

```sh
lxc image info <remote>:<alias-or-fingerprint>
```

An image reference has the form `<remote>:<alias-or-fingerprint>`. The colon separates the remote from the image. Shell pipelines such as `tail`, `grep`, or redirection do not repair an invalid remote or image reference; first obtain the exact reference from structured command output.

## Launch an instance

1. Choose an explicit instance name.
2. Check whether it already exists:

   ```sh
   lxc list <instance-name>
   ```

3. Confirm the image with `lxc image info`.
4. Form one complete launch command:

   ```sh
   lxc launch <remote>:<image> <instance-name>
   ```

5. Use `autocomplete_command` unless the user has explicitly authorized this exact launch.
6. After execution completes, verify it:

   ```sh
   lxc list <instance-name>
   ```

   ```sh
   lxc info <instance-name>
   ```

Do not send another launch command while the first launch may still be running.

## Respond to common failures

- **Unknown remote:** run `lxc remote list` once and use only a returned remote. Stop if the needed remote is absent.
- **Image not found:** run `lxc image list <confirmed-remote>: <filter>` and select an exact returned alias or fingerprint. Do not invent variations.
- **Instance name already exists:** report the conflict. Do not delete or rename the existing instance without approval.
- **Launch timeout or uncertain completion:** inspect `lxc operation list` and `lxc list <instance-name>` before considering a retry. Never launch the same instance blindly.
- **Operation is `CANCELING`:** treat it as a normal slow transitional state caused by delayed I/O or other environmental load. Leave it alone: do not cancel it again, delete it, retry the original operation, or repeatedly poll it. Record the state and stop handling that operation unless the user later asks to revisit it.
- **Permission or daemon error:** report the exact stderr. Use read-only identity and server checks before proposing a privilege or service change.

## Destructive actions

For delete, storage, network, profile, or remote changes:

1. Discover and display the exact target.
2. Place the proposed command in autocomplete for human review unless the user explicitly requested that exact action.
3. Execute one action at a time.
4. Verify the resulting state with a read-only command.

## Authoritative syntax

- Remote images: <https://documentation.ubuntu.com/lxd/latest/howto/images_remote/>
- Image listing: <https://documentation.ubuntu.com/lxd/latest/reference/manpages/lxc/image/list/>
- Instance launch: <https://documentation.ubuntu.com/lxd/latest/reference/manpages/lxc/launch/>
- Instance listing: <https://documentation.ubuntu.com/lxd/latest/reference/manpages/lxc/list/>
