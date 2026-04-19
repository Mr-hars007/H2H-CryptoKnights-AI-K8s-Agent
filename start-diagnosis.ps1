#!/usr/bin/env pwsh
<#
.SYNOPSIS
    H2H CryptoKnights Phase 5 - AI Diagnosis Loop Launcher

.DESCRIPTION
    Quick launcher for Interactive CLI, Streamlit UI, or single diagnosis queries

.EXAMPLE
    .\start-diagnosis.ps1 cli
    .\start-diagnosis.ps1 web
    .\start-diagnosis.ps1 diagnose --question "Why is orders failing?"
#>

param(
    [Parameter(Position=0)]
    [ValidateSet('cli', 'web', 'diagnose')]
    [string]$Mode = 'cli',
    
    [string]$Question = '',
    [string]$Namespace = 'ai-ops',
    [string]$Model = 'llama2'
)

$ErrorActionPreference = 'Stop'

# Colors for output
function Write-Color($Message, $Color = 'White') {
    Write-Host $Message -ForegroundColor $Color
}

function Write-Title($Message) {
    Write-Host "`n" + "=" * 70 -ForegroundColor Cyan
    Write-Host $Message -ForegroundColor Cyan
    Write-Host "=" * 70 + "`n" -ForegroundColor Cyan
}

# Check prerequisites
function Check-Prerequisites {
    Write-Title "Checking Prerequisites"
    
    # Check kubectl
    try {
        $kubectlVersion = kubectl version --client 2>$null
        Write-Color "✓ kubectl available" -Color Green
    } catch {
        Write-Color "✗ kubectl not found. Install kubectl." -Color Red
        exit 1
    }
    
    # Check Python
    try {
        $pythonVersion = python --version 2>&1
        Write-Color "✓ Python $pythonVersion" -Color Green
    } catch {
        Write-Color "✗ Python not found. Install Python 3.10+" -Color Red
        exit 1
    }
    
    # Check venv activation
    if ($null -eq $env:VIRTUAL_ENV) {
        Write-Color "⚠ Virtual environment not activated" -Color Yellow
        Write-Color "Activating .venv..." -Color Yellow
        & .\.venv\Scripts\Activate.ps1
    } else {
        Write-Color "✓ Virtual environment active: $env:VIRTUAL_ENV" -Color Green
    }
    
    # Check Ollama
    try {
        $curlCheck = curl -s http://localhost:11434/api/tags 2>$null
        if ($curlCheck) {
            Write-Color "✓ Ollama running at http://localhost:11434" -Color Green
            
            # Check if model exists
            if ($curlCheck -like "*$Model*" -or $curlCheck -like "*llama*") {
                Write-Color "✓ Models available" -Color Green
            } else {
                Write-Color "⚠ No models detected. Run: ollama pull llama2" -Color Yellow
            }
        } else {
            Write-Color "✗ Ollama not responding. Start with: ollama serve" -Color Red
            Write-Color "  Starting Ollama in background..." -Color Yellow
            Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
            Start-Sleep -Seconds 3
        }
    } catch {
        Write-Color "✗ Cannot connect to Ollama. Ensure it's running." -Color Red
        Write-Color "  Start with: ollama serve" -Color Yellow
        exit 1
    }
}

# Launch interactive CLI
function Launch-CLI {
    Write-Title "Launching Interactive Diagnosis CLI"
    Write-Color "Starting Python CLI..." -Color Cyan
    Write-Color "Type /help for commands or ask questions directly" -Color Gray
    Write-Color "`n" -Color Gray
    
    python backend/app.py cli --namespace $Namespace
}

# Launch Streamlit Web UI
function Launch-Web {
    Write-Title "Launching Streamlit Web UI"
    Write-Color "Starting Streamlit server..." -Color Cyan
    Write-Color "Opening http://localhost:8501 in browser..." -Color Cyan
    Write-Color "`n" -Color Gray
    
    Start-Process "http://localhost:8501"
    Start-Sleep -Seconds 2
    
    streamlit run ui/streamlit_app.py
}

# Run single diagnosis
function Run-Diagnose {
    if ([string]::IsNullOrEmpty($Question)) {
        Write-Color "Error: --question is required for diagnose mode" -Color Red
        exit 1
    }
    
    Write-Title "Running Single Diagnosis"
    Write-Color "Question: $Question" -Color Cyan
    Write-Color "Namespace: $Namespace" -Color Cyan
    Write-Color "`n" -Color Gray
    
    python backend/app.py diagnose --question $Question --namespace $Namespace
}

# Show help
function Show-Help {
    Write-Title "H2H CryptoKnights - Phase 5 AI Diagnosis Launcher"
    
    Write-Color "USAGE:" -Color Cyan
    Write-Color "  .\start-diagnosis.ps1 [MODE] [OPTIONS]" -Color White
    Write-Color ""
    
    Write-Color "MODES:" -Color Cyan
    Write-Color "  cli              Launch interactive diagnosis CLI (default)" -Color White
    Write-Color "  web              Launch Streamlit web UI" -Color White
    Write-Color "  diagnose         Run single diagnosis query" -Color White
    Write-Color ""
    
    Write-Color "OPTIONS:" -Color Cyan
    Write-Color "  --question TEXT  Question to diagnose (required for diagnose mode)" -Color White
    Write-Color "  --namespace NS   Kubernetes namespace (default: ai-ops)" -Color White
    Write-Color "  --model MODEL    Ollama model to use (default: llama2)" -Color White
    Write-Color ""
    
    Write-Color "EXAMPLES:" -Color Cyan
    Write-Color "  .\start-diagnosis.ps1                    # Launch interactive CLI" -Color White
    Write-Color "  .\start-diagnosis.ps1 web                # Launch Streamlit UI" -Color White
    Write-Color '  .\start-diagnosis.ps1 diagnose --question "Why are orders failing?"' -Color White
    Write-Color ""
}

# Main execution
function Main {
    # Check for help flag
    if ($Mode -eq '-h' -or $Mode -eq '--help' -or $Mode -eq 'help') {
        Show-Help
        exit 0
    }
    
    # Check prerequisites
    Check-Prerequisites
    
    # Set environment
    $env:AI_K8S_NAMESPACE = $Namespace
    $env:OLLAMA_MODEL = $Model
    
    Write-Color "`nConfiguration:" -Color Gray
    Write-Color "  Namespace: $Namespace" -Color Gray
    Write-Color "  Model: $Model" -Color Gray
    Write-Color ""
    
    # Launch selected mode
    switch ($Mode) {
        'cli' { Launch-CLI }
        'web' { Launch-Web }
        'diagnose' { Run-Diagnose }
        default { 
            Write-Color "Unknown mode: $Mode" -Color Red
            Show-Help
            exit 1
        }
    }
}

Main
