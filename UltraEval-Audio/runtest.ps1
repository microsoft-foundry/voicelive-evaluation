# VoiceLive S2T Evaluator Test Script (Cross-Platform)
# Tests all English-compatible evaluators with llama-questions dataset
# Results are organized in subfolders for each evaluator
# Compatible with Windows, macOS, and Linux

param(
    [int]$Workers = 20,
    [int]$Limit = 1000,
    [switch]$InferenceOnly,          # Only run inference, skip evaluation
    [bool]$EvaluationOnly = $false,         # Only run evaluation, skip inference
    [string]$InferenceFile = "",     # Path to existing inference results
    [string]$TestSuite = "bingchat-agent-base-cascaded",  # Predefined test configuration: default, quick, comprehensive, azure-ai-only, qa-only
    [string[]]$ModelConfigs = @(),   # Override model configs: e.g., @("GPT4o", "GPT4o-Mini")
    [string[]]$Datasets = @(),       # Override datasets: e.g., @("llama-questions", "speech-triviaqa")
    [string[]]$Evaluators = @(),     # Override evaluators: e.g., @("azure-ai-batch-qaevaluator", "em")
    [switch]$DryRun,                 # Show what would be executed without running
    [switch]$ParallelModels          # Run model configs in parallel (experimental)
)

# Cross-platform detection
function Get-PlatformInfo {
    $platform = @{
        IsWindows = $false
        IsMacOS = $false
        IsLinux = $false
        PathSeparator = ":"
        PythonCommand = "python3"
    }
    
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        $platform.IsWindows = $true
        $platform.PathSeparator = ";"
        $platform.PythonCommand = "python"
    } elseif ($IsMacOS -or (uname) -eq "Darwin") {
        $platform.IsMacOS = $true
    } else {
        $platform.IsLinux = $true
    }
    
    return $platform
}

$platformInfo = Get-PlatformInfo
Write-Host "🖥️  Platform detected: " -NoNewline -ForegroundColor Cyan
if ($platformInfo.IsWindows) { Write-Host "Windows" -ForegroundColor Green }
elseif ($platformInfo.IsMacOS) { Write-Host "macOS" -ForegroundColor Green }
else { Write-Host "Linux" -ForegroundColor Green }

# Initialize Azure login and environment
# Uncomment the next line if you need to login to Azure
# az login

# Cross-platform path handling
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$ultraEvalPath = Join-Path $projectRoot "UltraEval-Audio"

# Change to UltraEval-Audio directory
Set-Location $ultraEvalPath

# Cross-platform virtual environment activation
if ($platformInfo.IsWindows) {
    $venvActivateScript = Join-Path $ultraEvalPath ".venv" "Scripts" "Activate.ps1"
    $venvPython = Join-Path $ultraEvalPath ".venv" "Scripts" "python.exe"
} else {
    $venvActivateScript = Join-Path $ultraEvalPath ".venv" "bin" "Activate.ps1"
    $venvPython = Join-Path $ultraEvalPath ".venv" "bin" "python"
}

# Activate virtual environment if it exists
if (Test-Path $venvActivateScript) {
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    & $venvActivateScript
} elseif (Test-Path $venvPython) {
    Write-Host "Virtual environment detected, using venv Python..." -ForegroundColor Cyan
    $platformInfo.PythonCommand = $venvPython
}

# Cross-platform environment variable setting
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$ultraEvalPath$($platformInfo.PathSeparator)$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $ultraEvalPath
}
$env:CUDA_VISIBLE_DEVICES = "0"

Write-Host "Environment setup:" -ForegroundColor Cyan
Write-Host "  PYTHONPATH: $env:PYTHONPATH" -ForegroundColor Gray
Write-Host "  CUDA_VISIBLE_DEVICES: $env:CUDA_VISIBLE_DEVICES" -ForegroundColor Gray
Write-Host "  Working Directory: $(Get-Location)" -ForegroundColor Gray

# Function to display usage information
function Show-Usage {
    Write-Host "🚀 VoiceLive S2T Automated Evaluator Test Suite" -ForegroundColor Green
    Write-Host ""
    Write-Host "USAGE:" -ForegroundColor Yellow
    Write-Host "  ./runtest.ps1 [-TestSuite <suite>] [-Workers <int>] [-Limit <int>] [options...]" -ForegroundColor White
    Write-Host ""
    Write-Host "PARAMETERS:" -ForegroundColor Yellow
    Write-Host "  -TestSuite <suite>     Predefined test configuration (default: 'default')" -ForegroundColor White
    Write-Host "  -Workers <int>         Number of parallel workers (default: 5)" -ForegroundColor White
    Write-Host "  -Limit <int>           Limit number of samples per dataset (default: 10)" -ForegroundColor White
    Write-Host "  -InferenceOnly         Only run inference phase, skip evaluation" -ForegroundColor White
    Write-Host "  -EvaluationOnly        Only run evaluation phase (requires -InferenceFile)" -ForegroundColor White
    Write-Host "  -InferenceFile <path>  Path to existing inference results" -ForegroundColor White
    Write-Host "  -DryRun                Show what would be executed without running" -ForegroundColor White
    Write-Host "  -ModelConfigs <array>  Override model configs (e.g., @('GPT4o','GPT4o-Mini'))" -ForegroundColor White
    Write-Host "  -Datasets <array>      Override datasets" -ForegroundColor White
    Write-Host "  -Evaluators <array>    Override evaluators" -ForegroundColor White
    Write-Host ""
    Write-Host "TEST SUITES:" -ForegroundColor Yellow
    Write-Host "  quick                  Quick test (1 model, 1 dataset, 1 evaluator)" -ForegroundColor White
    Write-Host "  azure-ai-basic         Basic Azure AI evaluators" -ForegroundColor White
    Write-Host "  azure-ai-comprehensive Comprehensive Azure AI test" -ForegroundColor White
    Write-Host "  qa-comparison          Compare QA evaluators" -ForegroundColor White
    Write-Host "  multi-dataset          Test multiple datasets" -ForegroundColor White
    Write-Host "  production-ready       Production environment test" -ForegroundColor White
    Write-Host "  staging-validation     Staging environment test" -ForegroundColor White
    Write-Host "  comprehensive          Full test suite (all configs)" -ForegroundColor White
    Write-Host "  inference-only         Generate inference results only" -ForegroundColor White
    Write-Host ""
    Write-Host "EXAMPLES:" -ForegroundColor Yellow
    Write-Host "  ./runtest.ps1 -TestSuite quick -Limit 5" -ForegroundColor Gray
    Write-Host "  ./runtest.ps1 -TestSuite azure-ai-comprehensive -Workers 10" -ForegroundColor Gray
    Write-Host "  ./runtest.ps1 -InferenceOnly -TestSuite multi-dataset" -ForegroundColor Gray
    Write-Host "  ./runtest.ps1 -EvaluationOnly -InferenceFile 'path/to/inference.jsonl'" -ForegroundColor Gray
    Write-Host "  ./runtest.ps1 -DryRun -TestSuite comprehensive" -ForegroundColor Gray
    Write-Host "  ./runtest.ps1 -ModelConfigs @('VoiceLive-phi4-mm-realtime') -Evaluators @('azure-ai-batch-qaevaluator')" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# Check for help request
if ($args -contains "-help" -or $args -contains "--help" -or $args -contains "-h") {
    Show-Usage
}

Write-Host "🚀 VoiceLive S2T Automated Evaluator Test Suite" -ForegroundColor Green
Write-Host "Workers: $Workers, Limit: $Limit" -ForegroundColor Cyan

# Display execution mode
if ($InferenceOnly) {
    Write-Host "Mode: Inference Only (will skip evaluation)" -ForegroundColor Yellow
} elseif ($EvaluationOnly) {
    Write-Host "Mode: Evaluation Only (requires existing inference file)" -ForegroundColor Yellow
    if ($InferenceFile) {
        Write-Host "Using inference file: $InferenceFile" -ForegroundColor Cyan
    } else {
        Write-Host "❌ Error: -EvaluationOnly requires -InferenceFile parameter" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Mode: Full Pipeline (Inference + Multiple Evaluations)" -ForegroundColor Green
}
Write-Host ""

# Create timestamp for this test run
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
Write-Host "Test Run: $timestamp" -ForegroundColor Yellow

# Define all available model configurations
$allModelConfigs = @(
    @{
        Name = "VoiceLive-gpt-realtime"
        EnvVars = @{
            "AZURE_VOICELIVE_MODEL" = "gpt-realtime"
            "AZURE_VOICELIVE_TRANSCRIPTION_MODEL" = "gpt-4o-transcribe"
            "AZURE_AI_EVALUATION_NAME" = "VL-gpt-realtime+gpt-4o-transcribe-"
        }
    },
    @{
        Name = "VoiceLive-phi4-mm-realtime"
        EnvVars = @{
            "AZURE_VOICELIVE_MODEL" = "phi4-mm-realtime"
            "AZURE_VOICELIVE_TRANSCRIPTION_MODEL" = "azure-speech"
            "AZURE_AI_EVALUATION_NAME" = "VL-phi4-mm-realtime+azure-speech-"
        }
    },
    @{
        Name = "VoiceLive-gpt-4.1-mini"
        EnvVars = @{
            "AZURE_VOICELIVE_MODEL" = "gpt-4.1-mini"
            "AZURE_VOICELIVE_TRANSCRIPTION_MODEL" = "azure-speech"
            "AZURE_AI_EVALUATION_NAME" = "VL-gpt-4.1-mini+azure-speech-"
        }
    }
)

# Define all available evaluators with their required post-processors
$allEvaluators = @(
    # Basic evaluators
    @{Name="qa-exist-match"; Args="--evaluator qa-exist-match"; Description="QA Existence Match"; PostProcess="extract_response"},
    @{Name="em"; Args="--evaluator em"; Description="Exact Match"; PostProcess="extract_response"},
    @{Name="exist-match"; Args="--evaluator exist-match"; Description="Existence Match"; PostProcess="extract_response"},
    @{Name="prefix-match"; Args="--evaluator prefix-match"; Description="Prefix Match"; PostProcess="extract_response"},
    @{Name="wer"; Args="--evaluator wer"; Description="Word Error Rate"; PostProcess="extract_transcription"},
    @{Name="cer"; Args="--evaluator cer"; Description="Character Error Rate"; PostProcess="extract_response"},
    @{Name="bleu"; Args="--evaluator bleu"; Description="BLEU Score"; PostProcess="extract_response"},
    @{Name="dump"; Args="--evaluator dump"; Description="Dump (No Scoring)"; PostProcess="passthrough"},
    
    # Azure AI Foundry evaluators (batch optimized)
    @{Name="azure-ai-batch-qaevaluator"; Args="--evaluator azure-ai-batch-qaevaluator"; Description="Azure AI Batch QA Evaluator"; PostProcess="passthrough"},
    @{Name="azure-ai-batch-agent-base"; Args="--evaluator azure-ai-batch-agent-base"; Description="Azure AI Batch Agent Base (Intent + Task)"; PostProcess="passthrough"},
    @{Name="azure-ai-batch-agent-base-no-groundtruth"; Args="--evaluator azure-ai-batch-agent-base-no-groundtruth"; Description="Azure AI Batch Agent Base No Groundtruth (Intent + Task)"; PostProcess="passthrough"},
    @{Name="azure-ai-batch-agent-full"; Args="--evaluator azure-ai-batch-agent-full+tool"; Description="Azure AI Batch Agent Full + Tool"; PostProcess="passthrough"},
    @{Name="azure-ai-batch-quality"; Args="--evaluator azure-ai-batch-quality"; Description="Azure AI Batch Quality (Coherence + Fluency + Relevance)"; PostProcess="passthrough"},
    
    # Individual Azure AI evaluators
    @{Name="azure-ai-intent-resolution"; Args="--evaluator azure-ai-intent-resolution"; Description="Azure AI Intent Resolution"; PostProcess="passthrough"},
    @{Name="azure-ai-task-adherence"; Args="--evaluator azure-ai-task-adherence"; Description="Azure AI Task Adherence"; PostProcess="passthrough"},
    @{Name="azure-ai-groundedness"; Args="--evaluator azure-ai-groundedness"; Description="Azure AI Groundedness"; PostProcess="passthrough"},
    @{Name="azure-ai-coherence"; Args="--evaluator azure-ai-coherence"; Description="Azure AI Coherence"; PostProcess="passthrough"},
    @{Name="azure-ai-fluency"; Args="--evaluator azure-ai-fluency"; Description="Azure AI Fluency"; PostProcess="passthrough"},
    @{Name="azure-ai-relevance"; Args="--evaluator azure-ai-relevance"; Description="Azure AI Relevance"; PostProcess="passthrough"}
)

# Define all available datasets compatible with VoiceLive S2T
$allDatasets = @(
    # Question Answering datasets
    @{Name="llama-questions"; Description="Question Answering (English)"},
    @{Name="llama-questions-voicelive"; Description="Question Answering (VoiceLive optimized)"},
    @{Name="speech-triviaqa"; Description="TriviaQA Question Answering (English)"},
    @{Name="speech-web-questions"; Description="WebQuestions (English)"},
    
    # ASR datasets  
    @{Name="librispeech-test-clean"; Description="LibriSpeech Clean Test Set (English ASR)"},
    @{Name="librispeech-dev-clean"; Description="LibriSpeech Clean Dev Set (English ASR)"},
    @{Name="cv-15-en"; Description="Common Voice 15 English"},
    @{Name="fleurs-en_us"; Description="FLEURS English US"},
    @{Name="tedlium-test"; Description="TED-LIUM Test Set (English ASR)"},
    @{Name="peoples_speech-test"; Description="People's Speech Test Set"},
    
    # BingChat Agent Test Sets
    @{Name="bingchat-agent-en-us"; Description="BingChat Agent Test Set - English (1583 utterances)"},
    @{Name="bingchat-agent-fr-fr"; Description="BingChat Agent Test Set - French (784 utterances)"}
)

# Create base results directory structure (cross-platform)
$baseResultsDir = Join-Path "res" "VoiceLiveS2T"
if (!(Test-Path $baseResultsDir)) {
    New-Item -ItemType Directory -Path $baseResultsDir -Force | Out-Null
}

# =============================================================================
# TEST SUITE CONFIGURATION SYSTEM
# =============================================================================

# Function to get test suite configuration
function Get-TestSuiteConfig {
    param([string]$SuiteName)
    
    switch ($SuiteName) {
        "firsteval" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime")
                Datasets = @("llama-questions-voicelive")
                Evaluators = @("azure-ai-batch-agent-base")
                Description = "Simple test with one model, one dataset, multiple evaluators"
            }
        }
        "firsteval-bingchat" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime")
                Datasets = @("bingchat-agent-en-us", "bingchat-agent-fr-fr")
                Evaluators = @("azure-ai-batch-agent-base")
                Description = "Simple test with one model, one dataset, multiple evaluators"
            }
        }
        "bingchat-agent-base" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-4.1-mini")
                Datasets = @("bingchat-agent-en-us", "bingchat-agent-fr-fr")
                Evaluators = @("azure-ai-batch-agent-base")
                Description = "Simple test with one model, one dataset, multiple evaluators"
            }
        }
        "bingchat-agent-base-cascaded" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime", "VoiceLive-gpt-4.1-mini")
                Datasets = @("bingchat-agent-en-us", "bingchat-agent-fr-fr")
                Evaluators = @("azure-ai-batch-agent-base-no-groundtruth")
                Description = "Simple test with one model, one dataset, multiple evaluators"
            }
        }
        "llama-test" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime", "VoiceLive-gpt-4.1-mini")
                Datasets = @("llama-questions-voicelive")
                Evaluators = @("qa-exist-match", "azure-ai-batch-qaevaluator", "azure-ai-batch-agent-base")
                Description = "Full test on llama-questions-voicelive dataset"
            }   
        }
        "foundry-batch-speech-trivia" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime")
                Datasets = @("speech-triviaqa")
                Evaluators = @("azure-ai-batch-agent-base", "azure-ai-batch-qaevaluator")
                Description = "Full test on speech-triviaqa dataset"
            }   
        }        
        "foundry-batch-speech-web" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime")
                Datasets = @("speech-web-questions")
                Evaluators = @("azure-ai-batch-agent-base", "azure-ai-batch-qaevaluator")
                Description = "Full test on speech-web-questions dataset"
            }   
        }              
        "comprehensive-nollama" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime", "VoiceLive-gpt-4.1-mini")
                Datasets = @("speech-triviaqa", "speech-web-questions")
                Evaluators = @("qa-exist-match", "azure-ai-batch-qaevaluator", "azure-ai-batch-agent-base")
                Description = "Full comprehensive test (all models, multiple datasets without LLAMA, main evaluators)"
            }
        }
        "comprehensive" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime", "VoiceLive-gpt-4.1-mini")
                Datasets = @("llama-questions-voicelive", "speech-triviaqa", "speech-web-questions")
                Evaluators = @("qa-exist-match", "azure-ai-batch-qaevaluator", "azure-ai-batch-agent-base")
                Description = "Full comprehensive test (all models, multiple datasets, main evaluators)"
            }
        }            
        "repeat" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime", "VoiceLive-gpt-4.1-mini")
                Datasets = @("speech-web-questions")
                Evaluators = @("qa-exist-match", "azure-ai-batch-qaevaluator", "azure-ai-batch-agent-base")
                Description = "Full comprehensive test (all models, multiple datasets, main evaluators)"
            }
        }        
        "wer" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime", "VoiceLive-phi4-mm-realtime", "VoiceLive-gpt-4.1-mini") #("VoiceLive-gpt-realtime") #, (
                Datasets = @("librispeech-test-clean")
                Evaluators = @("wer")
                Description = "WER Test"
            }
        }
        "inference-qa-avaluation" {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime")
                Datasets = @("llama-questions-voicelive")
                Evaluators = @("qa-exist-match")  # Only inference, no evaluation
                Description = "Inference-only test for later evaluation"
            }
        }
        default {
            return @{
                ModelConfigs = @("VoiceLive-gpt-realtime")
                Datasets = @("llama-questions-voicelive")
                Evaluators = @("azure-ai-batch-qaevaluator")
                Description = "Default test configuration"
            }
        }
    }
}

# Get test suite configuration
$testConfig = Get-TestSuiteConfig -SuiteName $TestSuite

# Override with command-line parameters if provided
$selectedModelConfigs = if ($ModelConfigs.Count -gt 0) { $ModelConfigs } else { $testConfig.ModelConfigs }
$selectedDatasets = if ($Datasets.Count -gt 0) { $Datasets } else { $testConfig.Datasets }
$selectedEvaluators = if ($Evaluators.Count -gt 0) { $Evaluators } else { $testConfig.Evaluators }

# Ensure arrays (PowerShell can return single items as non-arrays)
$selectedModelConfigs = @($selectedModelConfigs)
$selectedDatasets = @($selectedDatasets)
$selectedEvaluators = @($selectedEvaluators)

# Debug output
Write-Host "DEBUG: Selected Model Configs: $($selectedModelConfigs -join ', ')" -ForegroundColor Gray
Write-Host "DEBUG: Selected Datasets: $($selectedDatasets -join ', ')" -ForegroundColor Gray
Write-Host "DEBUG: Selected Evaluators: $($selectedEvaluators -join ', ')" -ForegroundColor Gray
Write-Host "DEBUG: All Model Configs Count: $($allModelConfigs.Count)" -ForegroundColor Gray
Write-Host "DEBUG: All Datasets Count: $($allDatasets.Count)" -ForegroundColor Gray
Write-Host "DEBUG: All Evaluators Count: $($allEvaluators.Count)" -ForegroundColor Gray

# Filter configurations based on selections
$modelConfigs = @($allModelConfigs | Where-Object { $_.Name -in $selectedModelConfigs })
$datasets = @($allDatasets | Where-Object { $_.Name -in $selectedDatasets })
$evaluators = @($allEvaluators | Where-Object { $_.Name -in $selectedEvaluators })

Write-Host "DEBUG: Filtered Model Configs: $($modelConfigs.Count)" -ForegroundColor Gray
if ($modelConfigs.Count -gt 0) {
    Write-Host "DEBUG: First Model Config Type: $($modelConfigs[0].GetType().Name)" -ForegroundColor Gray
    Write-Host "DEBUG: First Model Config Name: $($modelConfigs[0].Name)" -ForegroundColor Gray
    Write-Host "DEBUG: First Model Config Keys: $($modelConfigs[0].Keys -join ', ')" -ForegroundColor Gray
}
Write-Host "DEBUG: Filtered Datasets: $($datasets.Count)" -ForegroundColor Gray
Write-Host "DEBUG: Filtered Evaluators: $($evaluators.Count)" -ForegroundColor Gray

# Display test configuration
Write-Host "📋 Test Suite: $TestSuite - $($testConfig.Description)" -ForegroundColor Cyan
Write-Host "🤖 Model Configs: $(($modelConfigs | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor Yellow
Write-Host "📊 Datasets: $(($datasets | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor Yellow
Write-Host "⚖️  Evaluators: $(($evaluators | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor Yellow
Write-Host "📁 Results will be saved to: $baseResultsDir\<model-config>\<dataset-name>\<evaluator-name>\" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "🧪 DRY RUN MODE - No actual execution will occur" -ForegroundColor Yellow
}
Write-Host ""

# Run tests for each model configuration, dataset, and evaluator combination
foreach ($modelConfig in $modelConfigs) {
    Write-Host "🤖 Testing model configuration: $($modelConfig.Name)" -ForegroundColor Green
    
    # Store original environment variables for restoration
    $originalEnvVars = @{}
    
    # Set model-specific environment variables (overrides .env)
    foreach ($envVar in $modelConfig.EnvVars.GetEnumerator()) {
        $originalEnvVars[$envVar.Name] = [Environment]::GetEnvironmentVariable($envVar.Name)
        [Environment]::SetEnvironmentVariable($envVar.Name, $envVar.Value, "Process")
        Set-Item -Path "env:$($envVar.Name)" -Value $envVar.Value
        Write-Host "  🔧 Set $($envVar.Name) = $($envVar.Value)" -ForegroundColor Gray
    }
    
    # Create model config results directory
    $modelResultsDir = Join-Path $baseResultsDir $modelConfig.Name
    if (!(Test-Path $modelResultsDir)) {
        New-Item -ItemType Directory -Path $modelResultsDir -Force | Out-Null
    }

    # Store original evaluation name environment variable
    $evalNameEnvVar = "AZURE_AI_EVALUATION_NAME"
    $originalEvalName = [Environment]::GetEnvironmentVariable($evalNameEnvVar)
    foreach ($dataset in $datasets) {
        Write-Host "  📊 Testing dataset: $($dataset.Name) - $($dataset.Description)" -ForegroundColor Magenta
        
        # Append dataset name to evaluation name environment variable
        $newEvalName = "$originalEvalName$($dataset.Name)"
        [Environment]::SetEnvironmentVariable($evalNameEnvVar, $newEvalName, "Process")
        Set-Item -Path "env:$evalNameEnvVar" -Value $newEvalName
        Write-Host "    🔧 Set $evalNameEnvVar = $newEvalName" -ForegroundColor Gray

        # Create dataset directory under model config (cross-platform)
        $datasetDir = Join-Path $modelResultsDir $dataset.Name
        if (!(Test-Path $datasetDir)) {
            New-Item -ItemType Directory -Path $datasetDir -Force | Out-Null
        }
        
        # Phase 1: Inference Only (if requested or if it's the first run)
        $inferenceFile = ""
        if ($InferenceOnly -or (!$EvaluationOnly -and !$InferenceFile)) {
            Write-Host "    🧠 Running inference phase..." -ForegroundColor Cyan
            
            # Create inference results directory
            $inferenceDir = Join-Path $datasetDir "inference"
            if (!(Test-Path $inferenceDir)) {
                New-Item -ItemType Directory -Path $inferenceDir -Force | Out-Null
            }
            
            # Generate inference output filename
            $inferenceFile = Join-Path $inferenceDir "${timestamp}_inference.jsonl"
            $inferenceFileEscaped = $inferenceFile -replace '\\', '/'
            
            # Build inference-only command (using dump evaluator to skip evaluation)
            $inferenceCmd = "$($platformInfo.PythonCommand) audio_evals/main.py --dataset $($dataset.Name) --model VoiceLiveS2T --evaluator dump --post_process passthrough --workers $Workers --limit $Limit --debug_mode 0 --save `"$inferenceFileEscaped`""
            
            Write-Host "      Command: $inferenceCmd" -ForegroundColor Gray
            
            try {
                $startTime = Get-Date
                Invoke-Expression $inferenceCmd
                $endTime = Get-Date
                $duration = ($endTime - $startTime).TotalSeconds
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "      ✅ Inference completed ($([math]::Round($duration, 2))s)" -ForegroundColor Green
                    Write-Host "      � Inference results: $inferenceFile" -ForegroundColor Cyan
                } else {
                    Write-Host "      ❌ Inference failed (Exit Code: $LASTEXITCODE)" -ForegroundColor Red
                    continue  # Skip evaluation phase for this dataset
                }
            } catch {
                Write-Host "      ❌ Inference error: $($_.Exception.Message)" -ForegroundColor Red
                continue  # Skip evaluation phase for this dataset
            }
        } elseif ($InferenceFile) {
            $inferenceFile = $InferenceFile
            Write-Host "    📁 Using existing inference file: $inferenceFile" -ForegroundColor Cyan
        }
        
        # Phase 2: Multiple Evaluations (skip if InferenceOnly mode)
        if (!$InferenceOnly) {
            Write-Host "    📊 Running evaluation phase with multiple evaluators..." -ForegroundColor Cyan
            
            foreach ($eval in $evaluators) {
                Write-Host "      �🔄 Testing evaluator: $($eval.Name) - $($eval.Description)" -ForegroundColor Yellow
            
                # Create subfolder for this evaluator within the dataset (cross-platform)
                $evalDir = Join-Path $datasetDir $eval.Name
                if (!(Test-Path $evalDir)) {
                    New-Item -ItemType Directory -Path $evalDir -Force | Out-Null
                }
                
                # Generate output filename (cross-platform)
                $outputFile = Join-Path $evalDir "${timestamp}_$($eval.Name).jsonl"
                $outputFileEscaped = $outputFile -replace '\\', '/'  # Use forward slashes for Python
                
                # Build evaluation command using existing inference results
                if ($eval.PostProcess) {
                    $baseCmd = "$($platformInfo.PythonCommand) audio_evals/main.py --dataset $($dataset.Name) --model VoiceLiveS2T --post_process $($eval.PostProcess) --inf_file `"$inferenceFile`" --workers $Workers --limit $Limit --debug_mode 0 --save `"$outputFileEscaped`""
                } else {
                    $baseCmd = "$($platformInfo.PythonCommand) audio_evals/main.py --dataset $($dataset.Name) --model VoiceLiveS2T --post_process passthrough --inf_file `"$inferenceFile`" --workers $Workers --limit $Limit --debug_mode 0 --save `"$outputFileEscaped`""
                }

                if ($eval.Args) {
                    $fullCmd = "$baseCmd $($eval.Args)"
                } else {
                    $fullCmd = $baseCmd
                }
        
        Write-Host "     Command: $fullCmd" -ForegroundColor Gray
        
        # Execute command
        try {
            $startTime = Get-Date
            Invoke-Expression $fullCmd
            $endTime = Get-Date
            $duration = ($endTime - $startTime).TotalSeconds
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "     ✅ Success ($([math]::Round($duration, 2))s)" -ForegroundColor Green
                
                # Check if results files exist
                $overallFile = $outputFile -replace '\.jsonl$', '-overall.json'
                if (Test-Path $outputFile) {
                    $lineCount = (Get-Content $outputFile | Measure-Object -Line).Lines
                    Write-Host "        📄 Results: $outputFile ($lineCount lines)" -ForegroundColor Cyan
                }
                if (Test-Path $overallFile) {
                    Write-Host "        📊 Summary: $overallFile" -ForegroundColor Cyan
                }
            } else {
                Write-Host "     ❌ Failed (Exit Code: $LASTEXITCODE)" -ForegroundColor Red
            }
        }
        catch {
            Write-Host "     ❌ Error: $($_.Exception.Message)" -ForegroundColor Red
        }
        
                Write-Host ""
            }  # End of evaluators loop
        }  # End of evaluation phase
        Write-Host ""
    }  # End of datasets loop
    
    # Restore original environment variables
    Write-Host "  🔄 Restoring original environment variables..." -ForegroundColor Gray
    foreach ($envVar in $originalEnvVars.GetEnumerator()) {
        if ($null -ne $envVar.Value) {
            [Environment]::SetEnvironmentVariable($envVar.Name, $envVar.Value, "Process")
            Set-Item -Path "env:$($envVar.Name)" -Value $envVar.Value
        } else {
            [Environment]::SetEnvironmentVariable($envVar.Name, $null, "Process")
            Remove-Item -Path "env:$($envVar.Name)" -ErrorAction SilentlyContinue
        }
    }
    Write-Host ""
}

Write-Host "🏁 Test run completed!" -ForegroundColor Green
Write-Host ""

# # Generate summary report
# Write-Host "📊 Generating Summary Report..." -ForegroundColor Yellow

# $summaryFile = Join-Path $baseResultsDir "test-summary-$timestamp.md"
# $summaryContent = @"
# # VoiceLive S2T Multi-Dataset Evaluator Test Summary

# **Test Run:** $timestamp  
# **Workers:** $Workers  
# **Limit:** $Limit  
# **Datasets:** $($datasets | ForEach-Object { $_.Name } | Join-String -Separator ', ')  
# **Model:** VoiceLiveS2T  

# ## Results by Dataset and Evaluator

# "@

# foreach ($dataset in $datasets) {
#     $summaryContent += "`n### Dataset: $($dataset.Name) - $($dataset.Description)`n`n"
#     $summaryContent += "| Evaluator | Description | Status | Results File |`n"
#     $summaryContent += "|-----------|-------------|--------|--------------|`n"
    
#     foreach ($eval in $evaluators) {
#         $evalDir = Join-Path $baseResultsDir $dataset.Name | Join-Path -ChildPath $eval.Name
#         $outputFile = Join-Path $evalDir "${timestamp}_$($eval.Name).jsonl"
#         $overallFile = $outputFile -replace '\.jsonl$', '-overall.json'
        
#         if (Test-Path $outputFile) {
#             $status = "✅ Success"
#             $resultPath = Join-Path $dataset.Name $eval.Name | Join-Path -ChildPath "${timestamp}_$($eval.Name).jsonl"
#         } else {
#             $status = "❌ Failed"
#             $resultPath = "N/A"
#         }
        
#         $summaryContent += "`n| ``$($eval.Name)`` | $($eval.Description) | $status | ``$resultPath`` |"
#     }
# }

# $summaryContent += @"


# ## Directory Structure

# ``````
# $baseResultsDir/
# ├── test-summary-$timestamp.md
# "@

# foreach ($dataset in $datasets) {
#     $summaryContent += "`n├── $($dataset.Name)/"
#     foreach ($eval in $evaluators) {
#         $summaryContent += "`n│   ├── $($eval.Name)/"
#         $summaryContent += "`n│   │   ├── ${timestamp}_$($eval.Name).jsonl"
#         $summaryContent += "`n│   │   └── ${timestamp}_$($eval.Name)-overall.json"
#     }
# }

# $summaryContent += @"

# ``````

# ## Usage

# To view detailed results for any dataset/evaluator combination:
# ``````bash
# # View JSONL results
# cat "$baseResultsDir\<dataset-name>\<evaluator-name>\${timestamp}_<evaluator-name>.jsonl"

# # View summary results  
# cat "$baseResultsDir\<dataset-name>\<evaluator-name>\${timestamp}_<evaluator-name>-overall.json"
# ``````

# ## Rerun Individual Tests

# ``````bash
# # Example: Rerun WER evaluator on llama-questions dataset
# python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator wer --post_process extract_response --workers $Workers --limit $Limit --save "$baseResultsDir\llama-questions\wer\custom-run.jsonl"

# # Example: Rerun on different dataset
# python audio_evals/main.py --dataset librispeech-test-clean --model VoiceLiveS2T --evaluator wer --post_process extract_response --workers $Workers --limit $Limit --save "$baseResultsDir\librispeech-test-clean\wer\custom-run.jsonl"
# ``````
# "@

# Set-Content -Path $summaryFile -Value $summaryContent -Encoding UTF8

# Write-Host "📄 Summary report saved to: $summaryFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "🎉 All tests completed! Check the results in the dataset/evaluator subfolders." -ForegroundColor Green