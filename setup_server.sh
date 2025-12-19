#!/bin/bash

# Exit on error
set -e

echo "Starting Server Setup for AI SaaS..."

# 1. Update System
echo "Updating system packages..."
sudo apt-get update

# 2. Install Essentials
echo "Installing essential tools..."
sudo apt-get install -y git curl ca-certificates gnupg lsb-release

# 3. Install Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # Enable Docker without sudo for the current user
    sudo usermod -aG docker $USER
    echo "Docker installed. (You may need to logout and login again for group changes to take effect)"
else
    echo "Docker is already installed."
fi

# 4. Generate SSH Key for GitHub
echo "Checking SSH Keys..."
if [ ! -f ~/.ssh/id_ed25519 ]; then
    echo "Generating new SSH key for GitHub..."
    ssh-keygen -t ed25519 -C "deploy@server" -f ~/.ssh/id_ed25519 -N ""
    echo "SSH Key generated."
    
    echo "--------------------------------------------------------"
    echo "ACTION REQUIRED: Copy the key below to your GitHub Repo (Settings -> Deploy Keys)"
    echo "--------------------------------------------------------"
    cat ~/.ssh/id_ed25519.pub
    echo "--------------------------------------------------------"
else
    echo "SSH Key already exists."
    echo "Public Key:"
    cat ~/.ssh/id_ed25519.pub
fi

echo "Setup Complete! Next steps:"
echo "1. Copy the SSH key above to GitHub."
echo "2. Clone your repository."
echo "3. Create your .env file."
echo "4. Run 'docker compose up -d --build'"

