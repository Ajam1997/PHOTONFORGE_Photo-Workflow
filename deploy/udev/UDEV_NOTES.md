# PHOTONForge udev — Field Notes

Lessons learned during hardware testing on the Yoga 920 Star Wars Edition
(Ubuntu 24.04, kernel 6.x, systemd-udevd 255). Preserved here so the next
person doesn't spend three hours rediscovering them.

---

## 1. `ENV{DEVTYPE}` is required — bare `DEVTYPE` silently fails on Ubuntu 24.04

On Ubuntu 24.04 with systemd-udevd ≥ 252, bare key syntax (`DEVTYPE=="partition"`)
is not guaranteed to match on synthetic or replayed events. The correct syntax is
always the namespaced form:

```
# Wrong — works on older kernels, silently skips on Ubuntu 24.04
DEVTYPE=="partition"

# Correct
ENV{DEVTYPE}=="partition"
```

This was the root cause of the SSD rule never firing after initial install.
The same applies to any other device-attribute key — prefer `ENV{...}` always.

---

## 2. `RUN+=` values must invoke wrapper scripts, not inline shell

udev's `RUN+=` executes in a minimal environment with no tty, no login shell,
and a stripped PATH. Complex inline shell (`&&` chains, loops, variable
assignment with `$(...)`) is fragile: quoting errors are silent, stderr is
swallowed, and `set -e` is not in effect.

**Rule**: the `RUN+=` value should call one wrapper script with the device and
label as arguments. The wrapper owns all logic — mount, guard, pipeline launch,
cleanup. Reserve inline shell in `RUN+=` only for the log `echo` and the single
script invocation.

```
# Wrong — brittle, untestable, no error handling
RUN+="/bin/sh -c 'mkdir -p /mnt/x && mount /dev/%k /mnt/x && do_thing ...'"

# Correct — script owns mount + logic, udev just fires it
RUN+="/bin/sh -c 'echo \"[$(date -Iseconds)] add %k\" >> /var/log/photonforge.log \
    && /opt/photonforge/scripts/manage_ssd.sh /dev/%k %E{ID_FS_LABEL} >> /var/log/photonforge.log 2>&1'"
```

The inline `sed` in the SSD `remove` rule (`echo %E{ID_FS_LABEL} | sed s/^PHOTON-//`)
is a documented exception: udev substitutes `%E{...}` before the shell sees the
string, so the sed runs against a literal value (e.g. `PHOTON-001`), not a variable.
It is safe for the controlled `PHOTON-[0-9]+` label namespace.

---

## 3. SSD mounts via `systemd-mount`, not plain `mount`

`mount` called from a udev `RUN+=` handler runs in the udev worker's cgroup, which
can be killed by systemd when the worker times out (default 180 s). Long-running
mounts or mounts that block on a slow device can be reaped mid-operation.

The correct approach for production is to emit a `.mount` unit or call
`systemd-mount --no-block`:

```sh
systemd-mount --no-block --automount=no \
    --options ro,noatime "$DEVICE" "$MOUNT_POINT"
```

`--no-block` returns immediately; systemd tracks the mount lifetime outside the
udev worker. Our scripts currently use plain `mount` for simplicity, which is
acceptable for short-lived CI and lab use but should be migrated before
high-volume production use.

---

## 4. `wipefs -a` required before first format to clear stale signatures

A drive previously used with ZFS, NTFS, or another filesystem retains superblock
signatures in its first few sectors. `mkfs.ext4` will refuse to proceed (or
silently write a corrupt superblock on older versions) unless stale signatures are
cleared first.

```sh
# Always run before formatting a new cartridge
sudo wipefs -a /dev/sdX        # clear partition-table superblock
sudo wipefs -a /dev/sdX1       # clear filesystem signature on the partition
```

Omitting `wipefs` was the cause of `blkid` reporting `TYPE="zfs_member"` on a
freshly formatted PHOTON-* drive, which prevented `ID_FS_TYPE=="ext4"` from
matching in the udev rule.

---

## 5. Cartridge provisioning procedure

One-time setup for each new PHOTON cartridge. Run on a Linux host (not inside
the container). Replace `sdX` with the actual device node (`lsblk` to confirm)
and `XXX` with the zero-padded three-digit cartridge ID (e.g. `001`, `042`).

```sh
# 1. Identify the device
lsblk -o NAME,SIZE,VENDOR,MODEL,TRAN

# 2. Create a single partition filling the disk (skip if partition already exists)
sudo parted /dev/sdX --script mklabel gpt mkpart primary ext4 0% 100%

# 3. Clear any stale signatures (ZFS, NTFS, old ext4, etc.)
sudo wipefs -a /dev/sdX
sudo wipefs -a /dev/sdX1

# 4. Format with the PHOTON label
sudo mkfs.ext4 -L PHOTON-XXX /dev/sdX1

# 5. Verify
sudo blkid /dev/sdX1
# Expected output:
# /dev/sdX1: LABEL="PHOTON-XXX" UUID="..." TYPE="ext4" ...
```

The udev rule matches `ENV{ID_FS_LABEL}=="PHOTON-*"` and `ENV{ID_FS_TYPE}=="ext4"`,
so both the label prefix and filesystem type must be exactly right.

---

## 6. `blkid` confusion from stale signatures — known gotcha

`blkid` probes all known signature types and reports whichever it finds first.
After formatting without `wipefs`, it commonly reports the *old* type (e.g.
`TYPE="zfs_member"`) rather than the new `ext4`, because ZFS writes its label at
a fixed offset that overlaps with `blkid`'s probe order.

Symptoms:
- `udevadm test` shows `ID_FS_TYPE=zfs_member` despite `mkfs.ext4` completing without error
- Rule does not fire on insertion even though the label is correct
- `mount /dev/sdX1 /mnt/test` succeeds (kernel ignores `blkid` cache) but udev never triggers the pipeline

Diagnosis:
```sh
sudo wipefs /dev/sdX1          # list all detected signatures without removing them
sudo blkid -p /dev/sdX1        # low-level probe, shows all superblocks
```

Fix: `sudo wipefs -a /dev/sdX1 && sudo mkfs.ext4 -L PHOTON-XXX /dev/sdX1` then
`sudo udevadm trigger --action=add /dev/sdX1` to replay the add event with clean
metadata.
