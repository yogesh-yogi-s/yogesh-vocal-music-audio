# Small VM deploy pack

Use a single Oracle Always Free Linux VM with enough **disk** space for an 8 GiB
temporary filesystem plus the OS, image, and Caddy data. Obtain a domain and
point its A record at the VM's public IPv4 address before starting Caddy.
Oracle resources and domain registration remain subject to provider availability.

## Open inbound ports

In the Oracle Cloud VCN security list (or network security group attached to the
VM), allow inbound TCP 80 and 443 from the Internet. Also allow them in the VM's
OS firewall. For example, on Ubuntu with UFW:

```sh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

Keep port 8000 private; Compose publishes only Caddy's ports.

## Install Docker

Install Docker Engine and the Compose plugin using the instructions for the VM's
distribution at https://docs.docker.com/engine/install/. Verify both commands:

```sh
sudo docker version
sudo docker compose version
```

## Copy and configure

Copy this repository, including `deploy/`, onto the VM. In `deploy/`, copy
`.env.example` to `.env` and replace `audio.example.com` in `DOMAIN`,
`VMA_TRUSTED_HOSTS`, `VMA_ALLOWED_ORIGINS`, and `VMA_HEALTHCHECK_HOST` with the
real hostname. Keep `VMA_TRUSTED_PROXIES=172.30.80.2`, Caddy's fixed private
address on the Compose network. If that subnet conflicts with a local network,
change the Compose subnet, both fixed addresses, and this setting together.
The `.env` file is ignored by Git. It contains no required secrets.

```sh
cd /path/to/repository/deploy
cp .env.example .env
editor .env
```

## Create disk-backed capped temp storage

Create an 8 GiB filesystem image on the VM's persistent disk. This is an actual
disk allocation, not RAM or a Docker tmpfs. `fallocate` fails early if there is
insufficient space. Mount it at the path in `VMA_TEMP_DIR` and make it writable
only by the container's fixed UID/GID 10001. The loop filesystem caps all files
at 8 GiB even if the host disk is larger.

```sh
sudo mkdir -p /srv/vma/temp
sudo fallocate -l 8G /srv/vma/vma-temp.img
sudo mkfs.ext4 -F /srv/vma/vma-temp.img
echo '/srv/vma/vma-temp.img /srv/vma/temp ext4 loop,nosuid,nodev,noexec 0 0' | sudo tee -a /etc/fstab
sudo mount /srv/vma/temp
sudo chown 10001:10001 /srv/vma/temp
sudo chmod 700 /srv/vma/temp
df -h /srv/vma/temp
```

Run the filesystem creation commands once only, before any live data is stored.
The example sets `VMA_MAX_PROCESS_TEMP_BYTES` to 7 GiB, below the 8 GiB volume
capacity; the remaining 1 GiB leaves room for filesystem overhead and writes
already in flight. Keep this process budget below the mounted volume's size if
you resize it. Expiring application sessions are stored here; plan to monitor
free space and remove stale data only when the stack is stopped.

## Small Render Free preview

Render Free can build the root `Dockerfile` from the release branch with the
repository root directory left blank. It does not provide the VM deployment's
8 GiB capped volume, so use it only for a small-file preview. Set
`VMA_TEMP_ROOT=/tmp` and `TMPDIR=/tmp` if `/tmp/vma` is absent at runtime. Set
`VMA_MAX_UPLOAD_BYTES=10485760` (10 MiB) with
`VMA_MAX_PROCESS_TEMP_BYTES=209715200` (200 MiB); request and extraction
reservations then fit within that application budget. Keep the production host,
HTTPS origin, and health-check host set to the exact Render hostname. Free
instance storage and sessions disappear on restart or spin-down. The full
500 MiB file limit and durable session availability require a suitable host.

## Start and check

```sh
sudo docker compose --env-file .env config
sudo docker compose --env-file .env up -d --build
sudo docker compose ps
python3 ../scripts/smoke_live.py "https://$(sed -n 's/^DOMAIN=//p' .env)"
```

Caddy obtains and renews HTTPS certificates automatically when DNS and ports
80/443 work. Its body limit is 1002 MiB, and the server allows a two-hour body
read and response window with a ten-minute idle read limit. The app remains a
single process and Compose runs one container of each service. Before upgrades,
back up any data you intend to retain. The VMA image stores sessions on the
bounded temp filesystem; Caddy stores certificates in its named volume.
