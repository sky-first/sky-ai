terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.16"
    }
  }
  required_version = ">= 1.2.0"
}

provider "aws" {
  region  = "us-east-1" # Região da AWS (Norte da Virgínia)
}

# 1. Security Group (Firewall)
resource "aws_security_group" "ai_saas_sg" {
  name        = "ai_saas_security_group"
  description = "Permitir SSH, Backend e Frontend"

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Frontend (Next.js)
  ingress {
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Backend (FastAPI)
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Saída liberada para tudo (baixar pacotes, etc)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 2. Key Pair (Chave SSH)
# Ele vai ler a sua chave pública local (na pasta acima) para enviar para a AWS
resource "aws_key_pair" "deployer" {
  key_name   = "deploy-key-terraform"
  public_key = file("../deploy_key.pub")
}

# 3. Instância EC2
resource "aws_instance" "app_server" {
  ami           = "ami-0c7217cdde317cfec" # Ubuntu 22.04 LTS (us-east-1)
  instance_type = "t3.medium"
  key_name      = aws_key_pair.deployer.key_name

  vpc_security_group_ids = [aws_security_group.ai_saas_sg.id]

  # Tamanho do Disco (30GB é bom para Docker)
  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = {
    Name = "AI-SaaS-Prod"
  }
}

output "instance_ip" {
  description = "O IP público da sua instância"
  value       = aws_instance.app_server.public_ip
}

