#!/usr/bin/env python3
"""
Testa o Davinci via UI do browser (como cliente real).

Navega pela interface e testa:
1. Login
2. Acesso ao dashboard
3. Abertura do chat
4. Criação de dashboard via AI (Davinci)
5. Verificação de cache e validação
"""

import asyncio
import time
from playwright.async_api import async_playwright, Page, Browser

# Configurações
FRONTEND_URL = "http://localhost:3000"
TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "Test@2024!Secure"  # Senha padrão do script create-test-user.py


async def wait_for_element(page: Page, selector: str, timeout: int = 10000):
    """Aguarda elemento aparecer na página"""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        return True
    except:
        return False


async def test_login(page: Page):
    """Testa login na aplicação"""
    print("🔐 Testando login...")
    
    await page.goto(f"{FRONTEND_URL}/login", wait_until="networkidle")
    await page.wait_for_timeout(2000)  # Aguardar página carregar
    
    # Preencher email
    email_input = page.locator('input[name="email"], input[type="email"], input#email').first
    if await email_input.count() > 0:
        await email_input.fill(TEST_EMAIL)
        print(f"   ✅ Email preenchido: {TEST_EMAIL}")
    else:
        print("   ⚠️  Campo de email não encontrado")
        return False
    
    # Preencher senha
    password_input = page.locator('input[name="password"], input[type="password"], input#password').first
    if await password_input.count() > 0:
        await password_input.fill(TEST_PASSWORD)
        print(f"   ✅ Senha preenchida")
    else:
        print("   ⚠️  Campo de senha não encontrado")
        return False
    
    # Clicar em Sign in
    signin_button = page.locator('button:has-text("Sign in"), button[type="submit"]').first
    if await signin_button.count() > 0:
        await signin_button.click()
        print("   ✅ Botão Sign in clicado")
    else:
        print("   ⚠️  Botão Sign in não encontrado")
        return False
    
    # Aguardar redirecionamento
    await page.wait_for_timeout(3000)
    
    # Verificar se foi para o dashboard
    current_url = page.url
    if "/dashboard" in current_url or "/login" not in current_url:
        print(f"   ✅ Login bem-sucedido! URL atual: {current_url}")
        return True
    else:
        print(f"   ⚠️  Ainda na página de login. URL: {current_url}")
        return False


async def test_open_chat(page: Page):
    """Abre o chat AI"""
    print("\n💬 Testando abertura do chat...")
    
    # Procurar pelo botão do chat (pode ser um ícone de mensagem ou search bar)
    # Vários seletores possíveis
    chat_selectors = [
        'button[aria-label*="chat" i]',
        'button[aria-label*="AI" i]',
        'button:has-text("Ask")',
        '[data-testid*="chat"]',
        'button:has(svg)',
    ]
    
    chat_opened = False
    for selector in chat_selectors:
        try:
            elements = page.locator(selector)
            count = await elements.count()
            if count > 0:
                # Tentar clicar no primeiro elemento que parece ser o chat
                await elements.first.click()
                await page.wait_for_timeout(2000)
                print(f"   ✅ Chat aberto (seletor: {selector})")
                chat_opened = True
                break
        except:
            continue
    
    if not chat_opened:
        print("   ⚠️  Não foi possível encontrar o botão do chat automaticamente")
        print("   💡 Você pode abrir o chat manualmente e o teste continuará")
        await page.wait_for_timeout(5000)  # Dar tempo para abrir manualmente
    
    return True


async def test_dashboard_creation(page: Page):
    """Testa criação de dashboard via Davinci"""
    print("\n🎨 Testando criação de dashboard via AI (Davinci)...")
    
    # Procurar pelo card "Create dashboard" nas sugestões
    create_dashboard_selectors = [
        'button:has-text("Create dashboard")',
        'button:has-text("Criar dashboard")',
        '[data-action="create_dashboard"]',
        'button:has-text("dashboard")',
    ]
    
    found = False
    for selector in create_dashboard_selectors:
        try:
            elements = page.locator(selector)
            count = await elements.count()
            if count > 0:
                print(f"   ✅ Card 'Create dashboard' encontrado!")
                
                # Clicar no card
                start_time = time.time()
                await elements.first.click()
                print("   ✅ Card clicado - iniciando criação do dashboard...")
                
                # Aguardar processo de criação
                # Procurar por indicadores de progresso
                progress_selectors = [
                    ':has-text("Creating dashboard")',
                    ':has-text("Criando dashboard")',
                    ':has-text("Building")',
                    '[data-progress]',
                ]
                
                progress_found = False
                for prog_sel in progress_selectors:
                    try:
                        await page.wait_for_selector(prog_sel, timeout=5000)
                        print(f"   📊 Progresso detectado: {prog_sel}")
                        progress_found = True
                        break
                    except:
                        continue
                
                # Aguardar conclusão (pode levar alguns segundos)
                print("   ⏳ Aguardando conclusão da criação...")
                await page.wait_for_timeout(15000)  # Aguardar até 15 segundos
                
                # Verificar se foi redirecionado para o dashboard
                current_url = page.url
                if "dashboard" in current_url and "job_id" in current_url:
                    elapsed = time.time() - start_time
                    print(f"   ✅ Dashboard criado com sucesso! Tempo: {elapsed:.2f}s")
                    print(f"   📊 URL: {current_url}")
                    return True
                elif "dashboard" in current_url:
                    elapsed = time.time() - start_time
                    print(f"   ✅ Redirecionado para dashboard! Tempo: {elapsed:.2f}s")
                    print(f"   📊 URL: {current_url}")
                    return True
                else:
                    print(f"   ⚠️  Ainda na mesma página. URL: {current_url}")
                    return False
                
        except Exception as e:
            continue
    
    if not found:
        print("   ⚠️  Card 'Create dashboard' não encontrado nas sugestões")
        print("   💡 Verifique se:")
        print("      - O chat está aberto")
        print("      - As sugestões foram carregadas")
        print("      - Você está em modo Personal")
        return False
    
    return False


async def test_second_dashboard_creation(page: Page):
    """Testa segunda criação (deve usar cache)"""
    print("\n🔄 Testando segunda criação (deve usar cache)...")
    
    # Voltar para o chat
    # Procurar botão do chat novamente
    await page.wait_for_timeout(2000)
    
    # Procurar pelo card novamente
    create_dashboard_selector = 'button:has-text("Create dashboard"), button:has-text("Criar dashboard")'
    
    try:
        elements = page.locator(create_dashboard_selector)
        count = await elements.count()
        if count > 0:
            start_time = time.time()
            await elements.first.click()
            print("   ✅ Card clicado novamente...")
            
            # Aguardar (deve ser mais rápido se usar cache)
            await page.wait_for_timeout(10000)
            
            elapsed = time.time() - start_time
            print(f"   ⏱️  Tempo da segunda criação: {elapsed:.2f}s")
            
            if elapsed < 2.0:
                print("   ✅ Muito rápido! Provavelmente usou cache!")
            else:
                print("   ⚠️  Demorou mais que o esperado (pode não ter usado cache)")
            
            return True
    except Exception as e:
        print(f"   ⚠️  Erro ao testar segunda criação: {e}")
        return False
    
    return False


async def take_screenshot(page: Page, name: str):
    """Tira screenshot da página"""
    try:
        await page.screenshot(path=f"/tmp/davinci_test_{name}.png", full_page=True)
        print(f"   📸 Screenshot salvo: davinci_test_{name}.png")
    except Exception as e:
        print(f"   ⚠️  Erro ao tirar screenshot: {e}")


async def main():
    """Executa todos os testes"""
    print("=" * 70)
    print("TESTE DAVINCI VIA UI (BROWSER)")
    print("=" * 70)
    print()
    
    async with async_playwright() as p:
        # Iniciar browser
        print("🌐 Iniciando browser...")
        browser = await p.chromium.launch(headless=False)  # headless=False para ver o que acontece
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        
        try:
            # Teste 1: Login
            login_success = await test_login(page)
            if not login_success:
                print("\n❌ Login falhou. Verifique as credenciais.")
                await take_screenshot(page, "login_failed")
                return
            
            await take_screenshot(page, "after_login")
            await page.wait_for_timeout(2000)
            
            # Teste 2: Abrir chat
            await test_open_chat(page)
            await take_screenshot(page, "chat_opened")
            await page.wait_for_timeout(3000)  # Aguardar sugestões carregarem
            
            # Teste 3: Criar dashboard (primeira vez)
            dashboard_created = await test_dashboard_creation(page)
            if dashboard_created:
                await take_screenshot(page, "dashboard_created")
                await page.wait_for_timeout(3000)
            
            # Teste 4: Segunda criação (testar cache)
            # Voltar para o chat primeiro
            await page.goto(f"{FRONTEND_URL}/dashboard", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            await test_open_chat(page)
            await page.wait_for_timeout(3000)
            await test_second_dashboard_creation(page)
            
            print("\n" + "=" * 70)
            print("✅ TESTES CONCLUÍDOS")
            print("=" * 70)
            print("\n💡 Verifique os screenshots em /tmp/ para ver o que aconteceu")
            print("💡 Verifique os logs do backend para ver eventos de cache")
            
        except Exception as e:
            print(f"\n❌ ERRO durante teste: {e}")
            import traceback
            traceback.print_exc()
            await take_screenshot(page, "error")
        finally:
            # Manter browser aberto por 10 segundos para inspeção
            print("\n⏳ Mantendo browser aberto por 10 segundos para inspeção...")
            await page.wait_for_timeout(10000)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

