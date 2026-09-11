#!/bin/bash
# Sets up a local SQS-compatible queue (ElasticMQ) for Occurrence Desk.
# Owner: Sowmya — Queue, Autoscaling, Observability & Load
#
# Usage: bash ops/setup-local-queue.sh
# Requires: Docker Desktop running.

set -e

echo "Starting ElasticMQ container..."
docker run -d --name occdesk-queue -p 9324:9324 -p 9325:9325 softwaremill/elasticmq-native || \
  echo "Container may already be running — continuing."

echo "Waiting for ElasticMQ to be ready..."
sleep 3

echo "Creating main queue: occdesk-dev-parse"
curl -s -X POST "http://localhost:9324/?Action=CreateQueue&QueueName=occdesk-dev-parse&Version=2012-11-05" > /dev/null

echo "Creating dead-letter queue: occdesk-dev-parse-dlq"
curl -s -X POST "http://localhost:9324/?Action=CreateQueue&QueueName=occdesk-dev-parse-dlq&Version=2012-11-05" > /dev/null

echo ""
echo "Done. Add these to your .env:"
echo "SQS_ENDPOINT_URL=http://localhost:9324"
echo "SQS_QUEUE_URL=http://localhost:9324/000000000000/occdesk-dev-parse"
echo "SQS_DLQ_URL=http://localhost:9324/000000000000/occdesk-dev-parse-dlq"
echo ""
echo "Also export dummy AWS credentials before starting the API (boto3 requires them, even locally):"
echo "export AWS_ACCESS_KEY_ID=minioadmin"
echo "export AWS_SECRET_ACCESS_KEY=minioadmin"
