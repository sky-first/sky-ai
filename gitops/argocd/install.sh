#!/bin/bash
# Installs ArgoCD into the cluster

# Combine create namespace and install to avoid race conditions or errors if ns exists
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Install ArgoCD
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --version 5.46.7 \
  --set server.service.type=LoadBalancer \
  --set server.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-internal"=true \
  --wait
