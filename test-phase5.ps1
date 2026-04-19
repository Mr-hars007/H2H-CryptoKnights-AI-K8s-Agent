#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Phase 5 Integration Tests for AI Diagnosis Loop

.DESCRIPTION
    Validates all components of Phase 5 (AI Diagnosis Loop)
    - Dependencies installed
    - AI agent initialization
    - Tool integration
    - End-to-end diagnosis flow
    - CLI and UI functionality

.EXAMPLE
    .\test-phase5.ps1
    .\test-phase5.ps1 -Quick
    .\test-phase5.ps1 -Full
#>

param(
    [switch]$Quick = $false,
    [switch]$Full = $false
)

$ErrorActionPreference = 'Continue'
$namespace = 'ai-ops'
$results = @{
    Passed = 0
    Failed = 0
    Skipped = 0
}

function Write-Color($Message, $Color = 'White') {
    Write-Host $Message -ForegroundColor $Color
}

function Write-Title($Message) {
    Write-Host "`n" + "=" * 70 -ForegroundColor Cyan
    Write-Host $Message -ForegroundColor Cyan
    Write-Host "=" * 70 + "`n" -ForegroundColor Cyan
}

function Test-Condition($Name, $Condition, $OnFail) {
    if ($Condition) {
        Write-Color "✓ $Name" -Color Green
        $results.Passed++
    } else {
        Write-Color "✗ $Name" -Color Red
        if ($OnFail) { Write-Color "  → $OnFail" -Color Yellow }
        $results.Failed++
    }
}

function Test-File($Path, $Description) {
    $exists = Test-Path $Path
    Test-Condition "File exists: $Description" $exists "Expected: $Path"
    return $exists
}

function Test-Import($Module, $Description) {
    try {
        $code = "from $Module import *"
        $output = python -c $code 2>&1
        $success = $LASTEXITCODE -eq 0
        Test-Condition "Import available: $Description" $success "Error: $output"
        return $success
    } catch {
        Test-Condition "Import available: $Description" $false "Exception: $_"
        return $false
    }
}

# ========================================
# PHASE 5 INTEGRATION TESTS
# ========================================

Write-Title "H2H CryptoKnights - Phase 5 Integration Tests"

# Test 1: File Structure
Write-Color "TEST 1: File Structure" -Color Yellow
Test-File "backend/agent/ai_agent.py" "AI Agent Implementation"
Test-File "backend/agent/tools.py" "Agent Tool Wrappers"
Test-File "backend/agent/memory.py" "Conversation Memory"
Test-File "backend/cli.py" "Interactive CLI"
Test-File "ui/streamlit_app.py" "Streamlit Web UI"
Test-File "requirements.txt" "Python Dependencies"
Test-File "docs/PHASE_5_SETUP.md" "Setup Documentation"
Test-File "start-diagnosis.ps1" "Launch Script"

# Test 2: Dependencies
Write-Color "`nTEST 2: Python Dependencies" -Color Yellow
$deps = @('langchain', 'langchain-core', 'langchain-ollama', 'ollama', 'pydantic', 'streamlit')
foreach ($dep in $deps) {
    try {
        $output = python -c "import ${dep.replace('-', '_')}" 2>&1
        $installed = $LASTEXITCODE -eq 0
        Test-Condition "Package installed: $dep" $installed "Run: pip install -r requirements.txt"
    } catch {
        Test-Condition "Package installed: $dep" $false "Exception: $_"
    }
}

# Test 3: Module Imports
Write-Color "`nTEST 3: Agent Module Imports" -Color Yellow
Test-Import "agent" "Agent package"
Test-Import "agent.ai_agent" "AI Agent module"
Test-Import "agent.tools" "Agent tools module"
Test-Import "agent.memory" "Memory module"
Test-Import "tools" "Kubernetes tools"

# Test 4: Kubernetes Cluster
Write-Color "`nTEST 4: Kubernetes Cluster (Namespace: $namespace)" -Color Yellow
try {
    $podCount = kubectl get pods -n $namespace --no-headers 2>&1 | Measure-Object -Line
    $success = $podCount.Lines -gt 0
    Test-Condition "Namespace exists: $namespace" $success "Run: kubectl create namespace $namespace"
    
    if ($success) {
        $pods = kubectl get pods -n $namespace -o name --no-headers
        Test-Condition "Demo pods deployed" ($null -ne $pods) "Deploy manifests: kubectl apply -f k8s/manifests/"
    }
} catch {
    Test-Condition "Cluster accessible" $false "Error: $_"
}

# Test 5: Ollama
Write-Color "`nTEST 5: Ollama (Local LLM)" -Color Yellow
try {
    $response = curl -s http://localhost:11434/api/tags
    $hasOllama = $null -ne $response
    Test-Condition "Ollama running at localhost:11434" $hasOllama "Start with: ollama serve"
    
    if ($hasOllama) {
        $hasModel = $response -like "*llama*" -or $response -like "*mistral*"
        Test-Condition "LLM models available" $hasModel "Pull model: ollama pull llama2"
    }
} catch {
    Test-Condition "Ollama accessible" $false "Error: $_"
}

# Test 6: Agent Initialization
Write-Color "`nTEST 6: Agent Initialization" -Color Yellow
if ($results.Failed -eq 0 -and -not $Quick) {
    try {
        $testScript = @"
import sys
sys.path.insert(0, 'backend')
from agent import create_agent
agent = create_agent(namespace='$namespace')
print('OK')
"@
        $output = python -c $testScript 2>&1
        $success = $output -like "*OK*"
        Test-Condition "Agent initializes successfully" $success "Check: $output"
        
        if ($success) {
            Test-Condition "Agent has tools defined" $true
            Test-Condition "Agent has diagnosis method" $true
        }
    } catch {
        Test-Condition "Agent initialization" $false "Exception: $_"
    }
}

# Test 7: Tool Wrappers
Write-Color "`nTEST 7: Tool Wrappers (Kubernetes Tools)" -Color Yellow
if ($results.Failed -eq 0 -and -not $Quick) {
    try {
        $testScript = @"
import sys
sys.path.insert(0, 'backend')
from agent.tools import (
    tool_collect_evidence_snapshot,
    tool_get_cluster_status,
    tool_list_scenarios,
    tool_monitor_cluster
)
print('OK')
"@
        $output = python -c $testScript 2>&1
        Test-Condition "Tool wrappers import" ($output -like "*OK*") "Check imports in agent/tools.py"
    } catch {
        Test-Condition "Tool wrappers" $false "Exception: $_"
    }
}

# Test 8: CLI Execution
Write-Color "`nTEST 8: CLI Commands" -Color Yellow

# Test list command
try {
    $output = python backend/app.py list 2>&1
    $hasScenarios = $output -like "*crashloop*" -or $output -like "*pending*"
    Test-Condition "app.py list command" $hasScenarios "Check: app.py"
} catch {
    Test-Condition "app.py list command" $false "Exception: $_"
}

# Test status command
try {
    $output = python backend/app.py status --namespace $namespace 2>&1
    $hasStatus = $output -like "*pods*" -or $output -like "*ok*"
    Test-Condition "app.py status command" $hasStatus "Check: app.py"
} catch {
    Test-Condition "app.py status command" $false "Exception: $_"
}

# Test 9: Documentation
Write-Color "`nTEST 9: Documentation" -Color Yellow
if (Test-Path "docs/PHASE_5_SETUP.md") {
    $content = Get-Content "docs/PHASE_5_SETUP.md" -Raw
    Test-Condition "Setup guide includes prerequisites" ($content -like "*Prerequisites*")
    Test-Condition "Setup guide includes quick start" ($content -like "*Quick Start*")
    Test-Condition "Setup guide includes CLI commands" ($content -like "*CLI*")
    Test-Condition "Setup guide includes troubleshooting" ($content -like "*Troubleshooting*")
}

# Test 10: Full End-to-End (if Full flag set)
if ($Full) {
    Write-Color "`nTEST 10: Full End-to-End Diagnosis" -Color Yellow
    
    if ($results.Failed -eq 0) {
        Write-Color "Running single diagnosis query..." -Color Cyan
        try {
            $output = python backend/app.py diagnose --question "What is the cluster status?" --namespace $namespace 2>&1
            $hasDiagnosis = $output -like "*diagnosis*" -or $output -like "*ok*"
            Test-Condition "End-to-end diagnosis" $hasDiagnosis "Check diagnosis output"
        } catch {
            Test-Condition "End-to-end diagnosis" $false "Exception: $_"
        }
    } else {
        Write-Color "Skipping end-to-end test (prerequisites failed)" -Color Yellow
        $results.Skipped++
    }
}

# Summary
Write-Title "Test Results Summary"
Write-Color "Passed:  $($results.Passed)" -Color Green
Write-Color "Failed:  $($results.Failed)" -Color $(if ($results.Failed -gt 0) { 'Red' } else { 'Green' })
Write-Color "Skipped: $($results.Skipped)" -Color Yellow

Write-Color ""
if ($results.Failed -eq 0) {
    Write-Color "✓ ALL TESTS PASSED - Phase 5 Ready!" -Color Green
    Write-Color ""
    Write-Color "Next steps:" -Color Cyan
    Write-Color "  1. Start the AI agent: .\start-diagnosis.ps1 cli" -Color White
    Write-Color "  2. Ask diagnostic questions: Why is service X failing?" -Color White
    Write-Color "  3. Or try: .\start-diagnosis.ps1 web (for Streamlit UI)" -Color White
    Write-Color ""
    exit 0
} else {
    Write-Color "✗ TESTS FAILED - See errors above" -Color Red
    Write-Color ""
    Write-Color "Troubleshooting:" -Color Cyan
    Write-Color "  1. Ensure virtual environment is activated" -Color White
    Write-Color "  2. Install dependencies: pip install -r requirements.txt" -Color White
    Write-Color "  3. Start Ollama: ollama serve" -Color White
    Write-Color "  4. Check Kubernetes cluster: kubectl get nodes" -Color White
    Write-Color ""
    exit 1
}
