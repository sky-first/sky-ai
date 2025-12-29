# Script para atribuir permissões das App Registrations no Storage Account
# Execute este script com uma conta que tenha permissão "User Access Administrator" ou "Owner"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ATRIBUIÇÃO DE PERMISSÕES - STORAGE" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Configurações
$STORAGE_ACCOUNT = "aisaasbackup18980"
$RESOURCE_GROUP = "ai-saas-rg"
$SUBSCRIPTION_ID = "e1070cf9-7790-4f2d-b449-d4bf4bc21906"
$SCOPE = "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"

# App Registrations
$APPS = @(
    @{
        Name = "github-actions-terraform"
        ClientId = "0571e7c6-2529-4a1a-a20e-f431f57d5ee1"
        ObjectId = "8004e3a7-4f70-43bb-868f-c46e1f0a3dbe"
    },
    @{
        Name = "github-actions-terraform-1766055240"
        ClientId = "12f92aed-2ca0-4b27-8a04-376369308773"
        ObjectId = "ea6eedca-e1c8-444d-b56f-864860bb073d"
    }
)

Write-Host "Storage Account: $STORAGE_ACCOUNT" -ForegroundColor White
Write-Host "Resource Group: $RESOURCE_GROUP" -ForegroundColor White
Write-Host "Role: Storage Blob Data Contributor`n" -ForegroundColor White

$SUCCESS_COUNT = 0
$FAIL_COUNT = 0

foreach ($APP in $APPS) {
    Write-Host "Atribuindo permissão para: $($APP.Name)" -ForegroundColor Yellow
    Write-Host "  Client ID: $($APP.ClientId)" -ForegroundColor Gray
    Write-Host "  Object ID: $($APP.ObjectId)" -ForegroundColor Gray
    
    try {
        $result = az role assignment create `
            --role "Storage Blob Data Contributor" `
            --assignee $APP.ObjectId `
            --scope $SCOPE `
            2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK: Permissão atribuída com sucesso!`n" -ForegroundColor Green
            $SUCCESS_COUNT++
        } else {
            if ($result -match "already exists" -or $result -match "RoleAssignmentExists") {
                Write-Host "  INFO: Permissão já existe`n" -ForegroundColor Cyan
                $SUCCESS_COUNT++
            } else {
                Write-Host "  ERRO: $result`n" -ForegroundColor Red
                $FAIL_COUNT++
            }
        }
    } catch {
        Write-Host "  ERRO: $($_.Exception.Message)`n" -ForegroundColor Red
        $FAIL_COUNT++
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  RESUMO" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Sucesso: $SUCCESS_COUNT" -ForegroundColor Green
Write-Host "Falhas: $FAIL_COUNT`n" -ForegroundColor $(if ($FAIL_COUNT -gt 0) { "Red" } else { "Green" })

# Verificar permissões atribuídas
Write-Host "Verificando permissões atribuídas...`n" -ForegroundColor Cyan
az role assignment list `
    --scope $SCOPE `
    --query "[?contains(principalName, 'github') || contains(principalName, '0571e7c6') || contains(principalName, '12f92aed')].{Principal:principalName, Role:roleDefinitionName}" `
    -o table

Write-Host "`nScript concluído!" -ForegroundColor Green

