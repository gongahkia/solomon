# Chromium Full Benchmark Runner

Manual-only Hetzner Cloud scaffolding for issue #6. It creates an Ubuntu runner plus a large ext4 volume so a full Chromium checkout can be cloned once and reused across benchmark runs.

Prerequisites:

- Terraform or OpenTofu.
- Hetzner Cloud API token.
- SSH public key for root login.

Usage:

```sh
cd bench/infra/hetzner
export TF_VAR_hcloud_token=...
terraform init
terraform apply \
  -var 'ssh_public_key_path=~/.ssh/id_ed25519.pub' \
  -var 'server_type=cx52' \
  -var 'volume_size_gb=512'
```

After provisioning:

```sh
ip=$(terraform output -raw ipv4_address)
device=$(terraform output -raw volume_device)
ssh root@$ip "mkdir -p /mnt/chromium && mountpoint -q /mnt/chromium || mount $device /mnt/chromium"
ssh root@$ip
cd /mnt/chromium
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH=/mnt/chromium/depot_tools:$PATH
fetch --nohooks chromium
git clone https://github.com/gongahkia/shisa.git
cd shisa
bench/chromium-full-bench.sh --repo /mnt/chromium/src
```

Copy results back:

```sh
scp root@$ip:/mnt/chromium/shisa/bench-results/chromium-full-* bench-results/
```

Destroy compute when done if the checkout is no longer needed:

```sh
terraform destroy
```

Do not commit Terraform state, tokens, or generated benchmark files unless they were produced from a real full Chromium checkout and reviewed.
