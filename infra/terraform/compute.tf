# ---------- Compute Engine VM ----------

resource "google_compute_instance" "app" {
  name         = var.vm_name
  machine_type = "e2-small"
  zone         = var.zone

  tags = ["occdesk"]

  boot_disk {
    initialize_params {
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = 30
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = data.google_compute_network.default.name
    access_config {
      # Ephemeral public IP
    }
  }

  service_account {
    email  = var.service_account_email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  allow_stopping_for_update = true

  lifecycle {
    ignore_changes = [
      # Boot disk image updates are managed by COS auto-update
      boot_disk[0].initialize_params[0].image,
      # Metadata changes from gcloud SSH
      metadata["ssh-keys"],
    ]
  }
}
