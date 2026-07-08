variable "hcloud_token" {
  type        = string
  description = "Hetzner Cloud API token. Prefer TF_VAR_hcloud_token."
  sensitive   = true
}

variable "name" {
  type        = string
  description = "Server and volume name prefix."
  default     = "shisa-chromium-bench"
}

variable "location" {
  type        = string
  description = "Hetzner Cloud location."
  default     = "hel1"
}

variable "image" {
  type        = string
  description = "Server image."
  default     = "ubuntu-24.04"
}

variable "server_type" {
  type        = string
  description = "Hetzner Cloud server type. Pick x86_64 for parity with common developer hosts."
  default     = "cx52"
}

variable "volume_size_gb" {
  type        = number
  description = "Chromium checkout volume size in GiB."
  default     = 512
}

variable "mountpoint" {
  type        = string
  description = "Expected mountpoint for the attached Chromium volume."
  default     = "/mnt/chromium"
}

variable "ssh_public_key_path" {
  type        = string
  description = "Path to an SSH public key to install for root login."
}

variable "zig_version" {
  type        = string
  description = "Zig version used by this repo."
  default     = "0.15.2"
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to Hetzner Cloud resources."
  default = {
    project = "shisa"
    purpose = "chromium-full-bench"
  }
}
