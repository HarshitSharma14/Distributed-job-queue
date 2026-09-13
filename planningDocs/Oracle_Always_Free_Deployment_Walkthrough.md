# Oracle Always Free Deployment Walkthrough

This document records the steps used to deploy the Distributed Job Queue control plane to an Oracle Cloud Infrastructure (OCI) Always Free VM. It is both an execution checklist and a study guide explaining why each choice was made.

## Target architecture

The Oracle VM hosts the control plane:

```text
Oracle VM
├── HTTPS reverse proxy
├── FastAPI API and React dashboard
├── PostgreSQL
├── Redis
├── MinIO
├── Prometheus
├── Outbox publisher
├── Retry scheduler
└── Recovery monitor

Worker Owner's computer
└── Worker runtime
    └── Isolated Docker handler containers
```

Workers remain user-operated. They connect to the public HTTPS API but do not receive database, Redis, object-storage, signing, or Admin credentials.

## Always Free limits used

The instance must be created in the OCI account's home region and every selected resource must display **Always Free eligible**.

Selected compute configuration:

```text
Shape: VM.Standard.A1.Flex
Architecture: Arm / aarch64
Capacity type: On-demand
OCPUs: 1
Memory: 6 GB
```

The shape initially offered 1 OCPU. This is sufficient for the project, although image builds and service startup will be slower than with 2 OCPUs.

Do not select preemptible capacity: OCI can reclaim and permanently terminate a preemptible instance. Reserved capacity is unnecessary and is not available to Free Tier accounts.

## Operating-system selection

Selected image:

```text
Canonical Ubuntu 24.04 Minimal aarch64
```

This matches the Ampere ARM shape. The project's Docker base images support ARM.

## Instance security selection

Selected settings:

```text
Shielded instance: ON
Confidential computing: OFF
Other advanced security options: OFF/default
```

Confidential computing is incompatible with the selected Ubuntu ARM image and `VM.Standard.A1.Flex`, so OCI correctly prevents enabling it.

## Virtual Cloud Network

The instance creation form could not assign a public IPv4 address because a public subnet did not exist. A VCN and subnet were therefore created first from the Networking pages.

Created VCN:

```text
Name: relay-vcn
IPv4 CIDR: 10.0.0.0/16
DNS resolution: ON
DNS label: relayvcn
IPv6: OFF
```

### What a VCN is

A Virtual Cloud Network is the project's isolated private network inside OCI. The `/16` CIDR provides private addresses from `10.0.0.0` through `10.0.255.255`. Only a small part of that range is assigned to the public subnet.

## Public subnet

Created subnet:

```text
Name: relay-public-subnet
Type: Regional
IPv4 CIDR: 10.0.0.0/24
Route table: Default Route Table for relay-vcn
Access: Public subnet
DNS resolution: ON
DNS label: relaypublic
DHCP options: Default DHCP Options for relay-vcn
Security list: Default Security List for relay-vcn
IPv6: OFF
```

The option that prohibits public IP addresses on VNICs was left **OFF**. This allows the VM's virtual network interface to receive a public IPv4 address.

### What a subnet is

A subnet allocates part of the VCN address range to a group of resources. A public subnet permits public IP assignment, but it still needs an Internet Gateway and a route before traffic can reach the internet.

## Internet Gateway

Created Internet Gateway:

```text
Name: relay-internet-gateway
Enabled: ON
```

### What an Internet Gateway does

The gateway provides a path between the VCN and the public internet. Creating it alone is not enough: the subnet's route table must explicitly send internet-bound traffic to this gateway.

## Public internet route

Added the following rule to `Default Route Table for relay-vcn`:

```text
Target type: Internet Gateway
Destination type: CIDR Block
Destination: 0.0.0.0/0
Target: relay-internet-gateway
Description: Public internet route
```

`0.0.0.0/0` represents every IPv4 destination. Resources in the public subnet can now send internet-bound traffic through the Internet Gateway. Inbound access remains controlled separately by security-list rules and the operating-system firewall.

## Compute instance networking

The Compute instance creation form was restarted after creating the network resources. The existing resources were selected:

```text
VCN: relay-vcn
Subnet: relay-public-subnet
VNIC name: relay-vnic
Private IPv4: Automatically assigned
Public IPv4: Automatically assigned
IPv6: OFF
Private DNS: ON
Hostname: relay-server
Network Security Group: OFF
```

## SSH key

OCI generated a new SSH key pair for the instance. The private key was downloaded to a safe local folder.

Security rules for the key:

- Never share the private key.
- Never commit it to Git.
- Keep filesystem permissions restricted (`chmod 600 <private-key>` on macOS/Linux).
- The public key can be shared and is installed on the VM; the private key stays on the administrator's computer.

## Final instance configuration

The reviewed instance configuration was:

```text
Name: relay-server
Compartment: harshitsharma14 (root)
Availability domain: AD-1
Capacity type: On-demand
Fault domain: Oracle-selected
Image: Canonical Ubuntu 24.04 Minimal aarch64
Shape: VM.Standard.A1.Flex
OCPUs: 1
Memory: 6 GB
Network bandwidth: 1 Gbps
Live migration: Oracle-selected
Restart after infrastructure maintenance: ON
Instance metadata authorization header: ON
Compute Instance Monitoring: ON
Custom Logs Monitoring: OFF
Cloud Guard Workload Protection agent: OFF
Other optional Oracle Cloud Agent plugins: OFF
Secure Boot: OFF
Measured Boot: OFF
Trusted Platform Module: OFF
Confidential computing: OFF
Boot volume: Default size and performance
In-transit volume encryption: ON
Customer-managed master key: OFF
```

Only Custom Logs Monitoring and Cloud Guard Workload Protection needed to be changed from the reviewed defaults. The other settings were retained.

## First SSH connection

The instance was created and reached the `Running` state with a public IPv4 address. The first connection was made from macOS using the downloaded private key:

```bash
chmod 600 "/path/to/ssh-key-2026-09-11.key"
ssh -i "/path/to/ssh-key-2026-09-11.key" ubuntu@PUBLIC_IP
```

SSH displayed the host's ED25519 fingerprint because the Mac had never connected to this VM before. After confirming that the IP matched the OCI Console, the host was accepted with `yes`. This stored the host key in the local `~/.ssh/known_hosts` file so unexpected future key changes can be detected.

### Verified VM resources

The following read-only checks were run:

```bash
hostname
uname -m
df -h /
free -h
```

Observed configuration:

```text
Hostname: relay-server
Architecture: aarch64
Root filesystem: 45 GB total, 44 GB available
Memory: 5.8 GiB total, approximately 5.4 GiB available
Swap: none
```

This confirms that OCI provisioned the intended ARM VM. The available disk and memory are sufficient for the project. Swap is not required initially and can be added later if container builds show memory pressure.

## Ubuntu package update

The base operating system was updated before installing application software:

```bash
sudo apt update
sudo apt upgrade -y
```

The reboot check was:

```bash
test -f /var/run/reboot-required && echo "Reboot required" || echo "No reboot required"
```

Result: `No reboot required`.

## Deployment prerequisites

Installed the small set of host tools required before Docker deployment:

```bash
sudo apt install -y ca-certificates curl git
```

Purposes:

- `ca-certificates` validates HTTPS certificates.
- `curl` downloads signed repository metadata and performs health checks.
- `git` clones and updates the application repository.

Verified Git version: `2.43.0`.

## Docker package trust

Created the APT keyring directory and downloaded Docker's official repository signing key:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Verification showed `/etc/apt/keyrings/docker.asc` owned by `root`, readable by APT, and 3817 bytes in size. The signing key lets APT verify that Docker packages came from Docker's repository and were not modified in transit.

## Docker APT repository

Added Docker's stable ARM64 repository for Ubuntu 24.04 (`noble`):

```bash
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
apt-cache policy docker-ce
```

APT reported Docker CE `29.8.0` as the candidate and showed `https://download.docker.com/linux/ubuntu noble/stable arm64` as its source. This confirms that the package will come from Docker's official repository rather than an unrelated Ubuntu package.

## Docker Engine installation

Installed Docker Engine, containerd, Buildx, and Docker Compose:

```bash
sudo apt install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
```

Installed versions included:

```text
Docker Engine and CLI: 29.8.0
containerd.io: 2.3.5
Docker Buildx: 0.37.0
Docker Compose plugin: 5.5.1
```

The command `sudo systemctl status docker --no-pager` reported `active (running)`, and systemd enabled both Docker and containerd to start automatically after a VM reboot.

Docker logged nftables-rule cleanup warnings during its first empty startup, then successfully loaded containers, initialized BuildKit, and opened `/run/docker.sock`. A real test container is used next to verify the complete installation and network path.

## Non-root Docker access and validation

Added the regular `ubuntu` account to the `docker` group, then ended and recreated the SSH session so the new group membership took effect:

```bash
sudo usermod -aG docker ubuntu
exit
```

After reconnecting, verified the installation without using `sudo`:

```bash
groups
docker version
docker compose version
docker run --rm hello-world
```

Results:

- The `ubuntu` account belongs to the `docker` group.
- Docker client and server version `29.8.0` communicate successfully.
- The server is running on `linux/arm64`.
- Docker Compose version `v5.5.1` is available.
- Docker Hub connectivity, DNS, image download, container creation, and execution were confirmed by the ARM64 `hello-world` container.

The `docker` group effectively grants root-level control over the host. Only trusted administrator accounts should be added to it.

## Host firewall installation

Ubuntu Minimal did not include UFW, so it was installed explicitly:

```bash
sudo apt install -y ufw
```

APT removed `iptables-persistent` and `netfilter-persistent` because they are alternative firewall-rule managers, then installed UFW `0.36.2-6`. The message about falling back from the Dialog frontend to Readline is harmless on a minimal, non-GUI server.

UFW was not enabled immediately. SSH access must be allowed first to avoid locking the administrator out of the VM.

Allowed only the required public services, applied restrictive defaults, and enabled the firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
sudo ufw status verbose
```

Verified state:

- UFW is active, with low-level logging enabled.
- Incoming traffic is denied by default.
- Outgoing traffic is allowed by default.
- Routed traffic is denied by default.
- TCP ports `22` (SSH), `80` (HTTP), and `443` (HTTPS) are allowed.
- Matching IPv6 rules exist but are currently unused because IPv6 was not enabled in OCI.

A fresh SSH connection was opened from a second local terminal while the original session remained connected. This confirmed that new inbound SSH sessions still work through the enabled UFW rules.

## OCI public web ingress

In `relay-vcn` → **Security Lists** → **Default Security List for relay-vcn**, added two stateful ingress rules:

| Source | Protocol | Destination port | Purpose |
|---|---|---:|---|
| `0.0.0.0/0` | TCP | `80` | Public HTTP and HTTPS-certificate redirects/challenges |
| `0.0.0.0/0` | TCP | `443` | Public HTTPS application access |

Source port ranges were left empty, and the rules were described as `Public HTTP` and `Public HTTPS`. Traffic must pass both this OCI security list and the VM's UFW rules before reaching the host.

Docker-published ports can interact with firewall rules differently from ordinary host processes. The production Compose configuration must therefore publish only the reverse proxy's required ports; databases, Redis, object-storage administration, and monitoring services must remain on private Docker networks.

## Next action

- [x] Add `0.0.0.0/0` to the default route table with `relay-internet-gateway` as its target.
- [x] Return to Compute instance creation and select the existing VCN and public subnet.
- [x] Assign the VM a public IPv4 address (`140.238.241.160`).
- [x] Configure and preserve the SSH key.
- [x] Create the VM.
- [x] Connect to the VM over SSH.
- [x] Install and validate Docker Engine and Docker Compose.
- [x] Restrict ingress with the OCI security list and host firewall.
- [x] Prepare the production Compose stack and TLS reverse proxy.
- [x] Point the application and storage DNS names at the VM.
  - Used wildcard/IP DNS via `sslip.io`:
    - Application Domain: `relay.140-238-241-160.sslip.io`
    - Object Storage Domain: `storage.relay.140-238-241-160.sslip.io`
- [x] Create the private production environment file (`deploy/.env.production`) on the VM.
- [x] Deploy the production Compose stack and complete acceptance checks.
  - Verification complete: Caddy HTTPS is active, and the application is live at `https://relay.140-238-241-160.sslip.io/app/login`.

