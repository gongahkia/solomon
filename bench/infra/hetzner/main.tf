terraform {
  required_version = ">= 1.6.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.50"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_ssh_key" "bench" {
  name       = "${var.name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "hcloud_volume" "chromium" {
  name      = "${var.name}-chromium"
  size      = var.volume_size_gb
  location  = var.location
  format    = "ext4"
  labels    = var.labels
}

resource "hcloud_server" "bench" {
  name        = var.name
  image       = var.image
  server_type = var.server_type
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.bench.id]
  user_data   = templatefile("${path.module}/user-data.yaml.tftpl", {
    mountpoint = var.mountpoint
    zig_version = var.zig_version
  })
  labels = var.labels
}

resource "hcloud_volume_attachment" "chromium" {
  volume_id = hcloud_volume.chromium.id
  server_id = hcloud_server.bench.id
  automount = false
}
