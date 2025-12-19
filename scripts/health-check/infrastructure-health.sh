#!/bin/bash

set -euo pipefail

ENVIRONMENT="${1:-dev}"
VM_IP="${2:-}"
SSH_USER="${3:-azureuser}"

if [ -z "${VM_IP}" ]; then
    echo "VM IP not provided"
    exit 1
fi

if ! ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "${SSH_USER}@${VM_IP}" "echo 'SSH OK'" 2>/dev/null; then
    echo "Cannot connect via SSH"
    exit 1
fi

if ! ssh "${SSH_USER}@${VM_IP}" "docker ps" > /dev/null 2>&1; then
    echo "Docker is not running or not accessible"
    exit 1
fi

CONTAINERS=$(ssh "${SSH_USER}@${VM_IP}" "docker ps --format '{{.Names}}' | wc -l" 2>/dev/null || echo "0")
if [ "${CONTAINERS}" -eq "0" ]; then
    echo "No containers running"
fi

if ssh "${SSH_USER}@${VM_IP}" "docker exec postgres pg_isready -U postgres" > /dev/null 2>&1; then
    echo "PostgreSQL is healthy"
fi

if ssh "${SSH_USER}@${VM_IP}" "docker exec redis redis-cli ping" > /dev/null 2>&1; then
    echo "Redis is healthy"
fi

DISK_USAGE=$(ssh "${SSH_USER}@${VM_IP}" "df -h / | tail -1 | awk '{print \$5}' | sed 's/%//'" 2>/dev/null || echo "0")
if [ "${DISK_USAGE}" -gt "90" ]; then
    echo "Disk usage is high: ${DISK_USAGE}%"
fi

MEM_USAGE=$(ssh "${SSH_USER}@${VM_IP}" "free | grep Mem | awk '{printf \"%.0f\", \$3/\$2 * 100}'" 2>/dev/null || echo "0")
if [ "${MEM_USAGE}" -gt "90" ]; then
    echo "Memory usage is high: ${MEM_USAGE}%"
fi
