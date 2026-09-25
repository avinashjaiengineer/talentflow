output "public_ip" {
  value = aws_eip.this.public_ip
}

output "url" {
  value = "http://${aws_eip.this.public_ip}"
}

output "ssh" {
  value = "ssh -i ${local_sensitive_file.ssh_key.filename} ubuntu@${aws_eip.this.public_ip}"
}

output "ssh_key_path" {
  value = local_sensitive_file.ssh_key.filename
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "region" {
  value = var.region
}
