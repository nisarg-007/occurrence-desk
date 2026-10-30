# ---------- VPC (default network, already exists) ----------

data "google_compute_network" "default" {
  name = "default"
}

# ---------- Private services access for Cloud SQL ----------

resource "google_compute_global_address" "private_services" {
  name          = "google-managed-services-default"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = data.google_compute_network.default.id
}

resource "google_service_networking_connection" "private_vpc" {
  network                 = data.google_compute_network.default.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# ---------- Firewall rules ----------

resource "google_compute_firewall" "allow_http" {
  name    = "occdesk-allow-http"
  network = data.google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["80", "8000"]
  }

  source_ranges = length(var.team_ips) > 0 ? var.team_ips : ["0.0.0.0/0"]
  target_tags   = ["occdesk"]
}

resource "google_compute_firewall" "allow_https" {
  name    = "occdesk-allow-https"
  network = data.google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  source_ranges = length(var.team_ips) > 0 ? var.team_ips : ["0.0.0.0/0"]
  target_tags   = ["occdesk"]
}

resource "google_compute_firewall" "allow_ssh" {
  name    = "occdesk-allow-ssh"
  network = data.google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = length(var.team_ips) > 0 ? var.team_ips : ["0.0.0.0/0"]
  target_tags   = ["occdesk"]
}
