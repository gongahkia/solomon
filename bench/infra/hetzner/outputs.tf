output "ipv4_address" {
  value = hcloud_server.bench.ipv4_address
}

output "ipv6_address" {
  value = hcloud_server.bench.ipv6_address
}

output "mountpoint" {
  value = var.mountpoint
}

output "volume_device" {
  value = hcloud_volume.chromium.linux_device
}
