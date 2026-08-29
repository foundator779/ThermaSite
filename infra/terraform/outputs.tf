output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "web_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "worker_url" {
  value = google_cloud_run_v2_service.worker.uri
}

output "media_worker_url" {
  value = google_cloud_run_v2_service.media_worker.uri
}

output "media_dead_letter_topic" {
  value = google_pubsub_topic.media_dead_letter.name
}

output "artifact_bucket" {
  value = google_storage_bucket.artifacts.name
}

output "analysis_job" {
  value = google_cloud_run_v2_job.analysis.name
}

output "workflow_dead_letter_topic" {
  value = google_pubsub_topic.workflow_dead_letter.name
}
