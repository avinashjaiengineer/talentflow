variable "region" {
  description = "AWS region"
  type        = string
  default     = "ap-south-1"
}

variable "name" {
  description = "Name prefix for every resource"
  type        = string
  default     = "talentflow"
}

variable "instance_type" {
  description = "EC2 size. t3.small (2 GB) runs the full stack; use t3.medium for heavier use."
  type        = string
  default     = "t3.small"
}

variable "volume_size_gb" {
  type    = number
  default = 20
}

variable "ssh_cidr" {
  description = "CIDR allowed to SSH in, e.g. your IP as 203.0.113.7/32"
  type        = string
}

variable "backup_retention_days" {
  type    = number
  default = 30
}
