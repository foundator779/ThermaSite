locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtrace.googleapis.com",
    "monitoring.googleapis.com",
  ])
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "required" {
  for_each           = local.services
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "api" {
  account_id   = "terraforge-api"
  display_name = "ThermaSite API and screening coordinator"
}

resource "google_service_account" "analysis" {
  account_id   = "terraforge-analysis"
  display_name = "ThermaSite compatibility analysis job"
}

resource "google_service_account" "worker" {
  account_id   = "terraforge-worker"
  display_name = "ThermaSite compatibility workflow worker"
}

resource "google_service_account" "media_worker" {
  account_id   = "terraforge-media-worker"
  display_name = "ThermaSite dormant compatibility media worker"
}

resource "google_service_account" "internal_invoker" {
  account_id   = "terraforge-internal-invoker"
  display_name = "ThermaSite internal task invoker"
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-terraforge-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  soft_delete_policy {
    retention_duration_seconds = 0
  }
  lifecycle_rule {
    condition {
      age = var.artifact_retention_days
    }
    action {
      type = "Delete"
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "events" {
  name       = "terraforge-run-events"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "workflow" {
  name       = "terraforge-workflow-tasks"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "workflow_dead_letter" {
  name       = "terraforge-workflow-dead-letter"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "media" {
  name       = "terraforge-media-tasks"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "media_dead_letter" {
  name       = "terraforge-media-dead-letter"
  depends_on = [google_project_service.required]
}

resource "google_firestore_database" "runs" {
  name                              = "terraforge"
  location_id                       = var.region
  type                              = "FIRESTORE_NATIVE"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_DISABLED"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  deletion_policy                   = "ABANDON"
  depends_on                        = [google_project_service.required]
}

resource "google_project_iam_member" "api_roles" {
  for_each = toset([
    "roles/datastore.user",
    "roles/pubsub.publisher",
    "roles/storage.objectAdmin",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_roles" {
  for_each = toset([
    "roles/datastore.user",
    "roles/pubsub.publisher",
    "roles/storage.objectAdmin",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "media_worker_roles" {
  for_each = toset([
    "roles/datastore.user",
    "roles/pubsub.publisher",
    "roles/storage.objectAdmin",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.media_worker.email}"
}

resource "google_secret_manager_secret_iam_member" "api_google_key" {
  project   = var.project_id
  secret_id = var.google_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "api_fortyguard_key" {
  project   = var.project_id
  secret_id = var.fortyguard_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_google_key" {
  project   = var.project_id
  secret_id = var.google_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_secret_manager_secret_iam_member" "media_worker_google_key" {
  project   = var.project_id
  secret_id = var.google_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.media_worker.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_webhook" {
  count     = var.monitoring_webhook_secret == "" ? 0 : 1
  project   = var.project_id
  secret_id = var.monitoring_webhook_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_firms_key" {
  count     = var.firms_map_key_secret == "" ? 0 : 1
  project   = var.project_id
  secret_id = var.firms_map_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "analysis_roles" {
  for_each = toset(["roles/storage.objectAdmin", "roles/logging.logWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.analysis.email}"
}

resource "google_cloud_run_v2_job" "analysis" {
  name                = "terraforge-analysis-job"
  location            = var.region
  deletion_protection = false
  template {
    template {
      service_account = google_service_account.analysis.email
      timeout         = "180s"
      max_retries     = 0
      containers {
        image = var.analysis_image
        resources {
          limits = { cpu = "1", memory = "2Gi" }
        }
      }
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_job_iam_member" "worker_runs_analysis" {
  project  = var.project_id
  name     = google_cloud_run_v2_job.analysis.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_service_account_iam_member" "worker_acts_as_analysis" {
  service_account_id = google_service_account.analysis.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name                = "terraforge-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  template {
    service_account                  = google_service_account.api.email
    timeout                          = "300s"
    max_instance_request_concurrency = 40
    containers {
      image = var.api_image
      env {
        name  = "TERRAFORGE_ENV"
        value = "production"
      }
      env {
        name  = "TERRAFORGE_PROCESS_ROLE"
        value = "api"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "GEMMA_MODEL"
        value = var.gemma_model
      }
      env {
        name  = "VEO_MODEL"
        value = var.veo_model
      }
      env {
        name  = "LYRIA_MODEL"
        value = var.lyria_model
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.google_api_key_secret
            version = var.google_api_key_secret_version
          }
        }
      }
      env {
        name = "FORTYGUARD_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.fortyguard_api_key_secret
            version = var.fortyguard_api_key_secret_version
          }
        }
      }
      env {
        name  = "FORTYGUARD_POLL_INTERVAL_SECONDS"
        value = "5"
      }
      env {
        name  = "FORTYGUARD_POLL_TIMEOUT_SECONDS"
        value = "600"
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = google_firestore_database.runs.name
      }
      env {
        name  = "ARTIFACT_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.events.name
      }
      env {
        name  = "WORKFLOW_TOPIC"
        value = google_pubsub_topic.workflow.name
      }
      env {
        name  = "MEDIA_TOPIC"
        value = google_pubsub_topic.media.name
      }
      env {
        name  = "ANALYSIS_JOB_NAME"
        value = google_cloud_run_v2_job.analysis.name
      }
      env {
        name  = "TERRAFORGE_API_ORIGINS"
        value = "*"
      }
      env {
        name  = "INTERNAL_INVOKER_EMAIL"
        value = google_service_account.internal_invoker.email
      }
      resources {
        limits   = { cpu = "1", memory = "1Gi" }
        cpu_idle = false
      }
      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/api/v1/healthz"
          port = 8080
        }
      }
    }
    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }
  }
  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.api_google_key,
    google_secret_manager_secret_iam_member.api_fortyguard_key,
  ]
}

resource "google_cloud_run_v2_service" "worker" {
  name                = "terraforge-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false
  template {
    service_account                  = google_service_account.worker.email
    timeout                          = "900s"
    max_instance_request_concurrency = 1
    containers {
      image = var.api_image
      env {
        name  = "TERRAFORGE_ENV"
        value = "production"
      }
      env {
        name  = "TERRAFORGE_PROCESS_ROLE"
        value = "workflow"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "GEMMA_MODEL"
        value = var.gemma_model
      }
      env {
        name  = "VEO_MODEL"
        value = var.veo_model
      }
      env {
        name  = "LYRIA_MODEL"
        value = var.lyria_model
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.google_api_key_secret
            version = var.google_api_key_secret_version
          }
        }
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = google_firestore_database.runs.name
      }
      env {
        name  = "ARTIFACT_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.events.name
      }
      env {
        name  = "WORKFLOW_TOPIC"
        value = google_pubsub_topic.workflow.name
      }
      env {
        name  = "MEDIA_TOPIC"
        value = google_pubsub_topic.media.name
      }
      env {
        name  = "ANALYSIS_JOB_NAME"
        value = google_cloud_run_v2_job.analysis.name
      }
      env {
        name  = "INTERNAL_INVOKER_EMAIL"
        value = google_service_account.internal_invoker.email
      }
      dynamic "env" {
        for_each = var.monitoring_webhook_secret == "" ? [] : [var.monitoring_webhook_secret]
        content {
          name = "MONITORING_WEBHOOK_URL"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = var.monitoring_webhook_secret_version
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.firms_map_key_secret == "" ? [] : [var.firms_map_key_secret]
        content {
          name = "FIRMS_MAP_KEY"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = var.firms_map_key_secret_version
            }
          }
        }
      }
      resources {
        limits   = { cpu = "1", memory = "2Gi" }
        cpu_idle = true
      }
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
  }
  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.worker_google_key,
    google_secret_manager_secret_iam_member.worker_webhook,
    google_secret_manager_secret_iam_member.worker_firms_key,
  ]
}

resource "google_cloud_run_v2_service" "media_worker" {
  name                = "terraforge-media-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false
  template {
    service_account                  = google_service_account.media_worker.email
    timeout                          = "900s"
    max_instance_request_concurrency = 1
    containers {
      image = var.api_image
      env {
        name  = "TERRAFORGE_ENV"
        value = "production"
      }
      env {
        name  = "TERRAFORGE_PROCESS_ROLE"
        value = "media"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "GEMMA_MODEL"
        value = var.gemma_model
      }
      env {
        name  = "VEO_MODEL"
        value = var.veo_model
      }
      env {
        name  = "LYRIA_MODEL"
        value = var.lyria_model
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = google_firestore_database.runs.name
      }
      env {
        name  = "ARTIFACT_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.events.name
      }
      env {
        name  = "MEDIA_TOPIC"
        value = google_pubsub_topic.media.name
      }
      env {
        name  = "INTERNAL_INVOKER_EMAIL"
        value = google_service_account.internal_invoker.email
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.google_api_key_secret
            version = var.google_api_key_secret_version
          }
        }
      }
      resources {
        limits   = { cpu = "1", memory = "1Gi" }
        cpu_idle = true
      }
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
  }
  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.media_worker_google_key,
  ]
}

resource "google_cloud_run_v2_service" "web" {
  name                = "terraforge-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  template {
    max_instance_request_concurrency = 80
    containers {
      image = var.web_image
      env {
        name  = "API_BASE_URL"
        value = google_cloud_run_v2_service.api.uri
      }
      startup_probe {
        initial_delay_seconds = 1
        timeout_seconds       = 2
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "public_web" {
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "internal_worker" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.internal_invoker.email}"
}

resource "google_cloud_run_v2_service_iam_member" "internal_media_worker" {
  name     = google_cloud_run_v2_service.media_worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.internal_invoker.email}"
}

resource "google_service_account_iam_member" "internal_token_creators" {
  for_each = toset([
    "service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com",
    "service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com",
  ])
  service_account_id = google_service_account.internal_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "pubsub_dead_letter_roles" {
  for_each = toset(["roles/pubsub.publisher", "roles/pubsub.subscriber"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription" "workflow_push" {
  name                 = "terraforge-workflow-worker"
  topic                = google_pubsub_topic.workflow.id
  ack_deadline_seconds = 600

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/api/v1/internal/workflow/dispatch"
    oidc_token {
      service_account_email = google_service_account.internal_invoker.email
      audience              = google_cloud_run_v2_service.worker.uri
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.workflow_dead_letter.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.internal_worker,
    google_service_account_iam_member.internal_token_creators,
    google_project_iam_member.pubsub_dead_letter_roles,
  ]
}

resource "google_pubsub_subscription" "media_push" {
  name                 = "terraforge-media-worker"
  topic                = google_pubsub_topic.media.id
  ack_deadline_seconds = 600

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.media_worker.uri}/api/v1/internal/media/dispatch"
    oidc_token {
      service_account_email = google_service_account.internal_invoker.email
      audience              = google_cloud_run_v2_service.media_worker.uri
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.media_dead_letter.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.internal_media_worker,
    google_service_account_iam_member.internal_token_creators,
    google_project_iam_member.pubsub_dead_letter_roles,
  ]
}

resource "google_cloud_scheduler_job" "monitoring_checks" {
  name        = "terraforge-monitoring-checks"
  description = "Queues legacy compatibility monitoring missions"
  region      = var.region
  schedule    = "0 */6 * * *"
  time_zone   = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker.uri}/api/v1/missions/check-due"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.internal_invoker.email
      audience              = google_cloud_run_v2_service.worker.uri
    }
  }

  depends_on = [
    google_project_service.required,
    google_cloud_run_v2_service_iam_member.internal_worker,
    google_service_account_iam_member.internal_token_creators,
  ]
}
