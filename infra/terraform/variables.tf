variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "api_image" {
  type = string
}

variable "web_image" {
  type = string
}

variable "analysis_image" {
  type = string
}

variable "gemini_model" {
  type    = string
  default = "gemini-3.6-flash"
}

variable "gemma_model" {
  type    = string
  default = "gemma-4-26b-a4b-it"
}

variable "veo_model" {
  type    = string
  default = "veo-3.1-generate-preview"
}

variable "lyria_model" {
  type    = string
  default = "lyria-3-clip-preview"
}

variable "google_api_key_secret" {
  type        = string
  description = "Secret Manager secret name containing the Gemini API key"
  default     = "terraforge-google-api-key"
}

variable "google_api_key_secret_version" {
  type        = string
  description = "Pinned Secret Manager version for the Gemini API key"
  default     = "1"
}

variable "fortyguard_api_key_secret" {
  type        = string
  description = "Secret Manager secret name containing the FortyGuard API key"
  default     = "thermasite-fortyguard-api-key"
}

variable "fortyguard_api_key_secret_version" {
  type        = string
  description = "Pinned Secret Manager version for the FortyGuard API key"
  default     = "1"
}

variable "monitoring_webhook_secret" {
  type        = string
  description = "Optional Secret Manager secret containing an HTTPS alert webhook"
  default     = ""
}

variable "monitoring_webhook_secret_version" {
  type        = string
  description = "Pinned Secret Manager version for the optional monitoring webhook"
  default     = "1"
}

variable "firms_map_key_secret" {
  type        = string
  description = "Optional Secret Manager secret containing a NASA FIRMS MAP_KEY"
  default     = ""
}

variable "firms_map_key_secret_version" {
  type        = string
  description = "Pinned Secret Manager version for the optional NASA FIRMS key"
  default     = "1"
}

variable "artifact_retention_days" {
  type        = number
  description = "Number of days generated evidence artifacts are retained before lifecycle deletion"
  default     = 7

  validation {
    condition     = var.artifact_retention_days >= 1 && var.artifact_retention_days <= 90
    error_message = "artifact_retention_days must be between 1 and 90 for the demo deployment."
  }
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to supported ThermaSite resources"
  default = {
    application = "thermasite"
    environment = "production"
    managed-by  = "terraform"
  }
}
