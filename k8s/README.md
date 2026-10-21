# Kubernetes manifests (M5)

Runs Occurrence Desk on GKE Autopilot behind a global HTTPS load balancer.

| File | What it defines |
|---|---|
| `00-namespace-config.yaml` | Namespace, Workload Identity service account, shared config (no secrets) |
| `05-queue.yaml` | In-cluster ElasticMQ (single replica) with the parse queue and dead-letter queue |
| `10-api-deployment.yaml` | API Deployment: 2+ replicas, startup, liveness (`/healthz`) and readiness (`/readyz`) probes |
| `11-worker-deployment.yaml` | Worker Deployment: 2 replicas, liveness from the main-loop heartbeat |
| `20-service-ingress.yaml` | Service, load balancer health check, http-to-https redirect, managed certificate, Ingress |
| `30-hpa-pdb.yaml` | HorizontalPodAutoscaler (CPU 50%, 2-6) and PodDisruptionBudgets (`minAvailable: 1`) |

## `${VARS}` in the files

The files contain `${PROJECT_ID}`, `${REGISTRY}`, `${IMAGE_TAG}`, `${APP_HOSTNAME}` and similar placeholders so no
project-specific value or secret is hard-coded. `ops/m5-deploy.sh` fills them in with `envsubst` before applying.

```bash
ops/m5-cluster-setup.sh                                  # one-time: cluster, identity, static IP
APP_HOSTNAME=<ip-with-dashes>.sslip.io ops/m5-deploy.sh build
APP_HOSTNAME=<ip-with-dashes>.sslip.io ops/m5-deploy.sh apply
APP_HOSTNAME=<ip-with-dashes>.sslip.io ops/m5-deploy.sh render   # print final YAML only
```

Secrets (database URL, JWT secret) are read from Secret Manager at startup, never from these files.
