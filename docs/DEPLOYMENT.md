# Deploying TalentFlow to AWS

This guide sets up one EC2 instance running the full stack behind Caddy:

```
Internet ──► Caddy (:80/:443, automatic HTTPS) ──► API (uvicorn ×2) ──► Postgres 17 + pgvector
                                                    Agent worker ────┘
             CloudWatch Logs ◄── all containers      S3 ◄── nightly pg_dump
```

It costs about **$17/month** in ap-south-1: t3.small, a 20 GB gp3 volume, and an Elastic IP. S3 and CloudWatch cost cents at this scale.

## Prerequisites

- AWS CLI credentials that work (`aws sts get-caller-identity`)
- Terraform ≥ 1.6, `ssh`, `tar`, Python 3
- An Anthropic API key

## 1. Create the infrastructure

```bash
cd infra
echo 'ssh_cidr = "'"$(curl -s https://checkip.amazonaws.com)"'/32"' > terraform.tfvars
terraform init
terraform apply          # optional: -var region=us-east-1 -var instance_type=t3.medium
```

This creates the following, all tagged `Project=talentflow`:

- **EC2 server:** Ubuntu 24.04 with IMDSv2 only and an encrypted disk. On first boot it installs Docker, sets up 2 GB of swap, and schedules nightly backups.
- **Elastic IP:** a fixed address that doesn't change if the server restarts.
- **Security group:** port 22 open only to your IP; ports 80 and 443 open to everyone.
- **SSH key:** written to `infra/talentflow.pem`, which is gitignored.
- **S3 bucket for backups:** private, encrypted, and deletes backups after 30 days.
- **CloudWatch log group:** `/talentflow/app`, kept for 30 days.
- **Server permissions (IAM role):** the server can write backups to the bucket and send logs to the log group, and nothing else. It also has the Systems Manager permission, so you can open a shell without SSH.

## 2. Configure secrets

```bash
./deploy/deploy.sh    # first run writes deploy/.env.production with random secrets, then stops
```

Edit `deploy/.env.production`:

- `ADMIN_EMAIL`: your sign-in email
- `ANTHROPIC_API_KEY`: without it, the agents run in offline heuristic mode
- `ADMIN_PASSWORD` is generated for you. Change it after you first sign in, from **Settings → Change password**.

The file is gitignored. It is copied to the server with `0600` permissions.

## 3. Deploy

```bash
./deploy/deploy.sh
```

This uploads the working tree, builds the image on the server, and starts the containers. It runs `alembic upgrade head` before the API starts and waits for `/api/ready`. Re-run it to ship changes; builds after the first one are cached.

## 4. Verify

```bash
python scripts/smoke_test.py http://<public_ip>
```

The smoke test runs the whole pipeline with the real agents:

1. Signs in.
2. Parses a resume.
3. Screens the candidate.
4. Runs sourcing.
5. Approves the candidate at the screening gate.
6. Sends outreach.
7. Schedules the interview.
8. Evaluates the interview notes.
9. Approves the offer.

It also checks the security headers, that the API requires sign-in, and that `/docs` is disabled in production.

## HTTPS

1. Point a DNS **A record** at the Elastic IP.
2. In `deploy/.env.production`, set `DOMAIN=talent.example.com` and `COOKIE_SECURE=true`.
3. Run `./deploy/deploy.sh`.

Caddy gets and renews a Let's Encrypt certificate and adds HSTS. Keep HTTP-only deployments for testing: without HTTPS, passwords and session cookies travel unencrypted.

## Operations

| Task | Command (on the server, in `/opt/talentflow`) |
|---|---|
| Status | `docker compose -f deploy/docker-compose.prod.yml ps` |
| Logs | `docker compose -f deploy/docker-compose.prod.yml logs -f app worker`, or CloudWatch → `/talentflow/app` |
| Backup now | `sudo talentflow-backup` |
| Restore | `aws s3 cp s3://<bucket>/postgres/<file>.dump - \| docker compose -f deploy/docker-compose.prod.yml exec -T db pg_restore -U talentflow -d talentflow --clean --if-exists` |
| Load demo data | `docker compose -f deploy/docker-compose.prod.yml exec app python -m app.seed` |
| Scale agents | `docker compose -f deploy/docker-compose.prod.yml up -d --scale worker=3` (tasks are claimed with `SKIP LOCKED`, so workers never duplicate work) |

SSH in with the `ssh` output from Terraform: `terraform -chdir=infra output -raw ssh`.

## Tear down

```bash
terraform -chdir=infra destroy
```

This deletes the server, its disk, the IP, the logs, **and the backup bucket**. Copy any backups you want to keep first.
