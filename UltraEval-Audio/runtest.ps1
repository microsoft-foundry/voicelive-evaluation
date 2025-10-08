# VoiceLive S2T Evaluator Test Script
# Tests all English-compatible evaluators with llama-questions dataset
# Results are organized in subfolders for each evaluator

param(
    [int]$Workers = 2,
    [int]$Limit = 2
)

# Initialize Azure login and environment
# az login

cd C:\Localrepos\voicelive-evaluation\UltraEval-Audio

# .\.venv\Scripts\activate

$env:PYTHONPATH = "C:\Localrepos\voicelive-evaluation\UltraEval-Audio;$env:PYTHONPATH"; $env:CUDA_VISIBLE_DEVICES = "0"

Write-Host "🚀 VoiceLive S2T Evaluator Testing Script" -ForegroundColor Green
Write-Host "Workers: $Workers, Limit: $Limit" -ForegroundColor Cyan
Write-Host ""

# Create timestamp for this test run
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
Write-Host "Test Run: $timestamp" -ForegroundColor Yellow

# Define English-compatible evaluators
$evaluators = @(
    @{Name="default"; Args=""; Description="Default QA evaluator (qa-exist-match)"}
    # @{Name="em"; Args="--evaluator em"; Description="Exact Match"},
    @{Name="exist-match"; Args="--evaluator exist-match"; Description="Existence Match"},
    # @{Name="prefix-match"; Args="--evaluator prefix-match"; Description="Prefix Match"},
    # @{Name="wer"; Args="--evaluator wer"; Description="Word Error Rate"},
    # @{Name="wer-sensitive"; Args="--evaluator wer-sensitive-case"; Description="Word Error Rate (Case Sensitive)"},
    # @{Name="cer"; Args="--evaluator cer"; Description="Character Error Rate"},
    @{Name="bleu"; Args="--evaluator bleu"; Description="BLEU Score"},
    # @{Name="bleu-char"; Args="--evaluator bleu-char"; Description="BLEU Score (Character-level)"},
    # @{Name="coco"; Args="--evaluator coco"; Description="COCO Metrics"},
    @{Name="qa-exist-match"; Args="--evaluator qa-exist-match"; Description="QA Existence Match"},
    # @{Name="dump"; Args="--evaluator dump"; Description="Dump (No Scoring)"}
)

# Define datasets compatible with VoiceLive S2T
$datasets = @(
    @{Name="llama-questions"; Description="Question Answering (English)"; PostProcess="extract_text"},
    # @{Name="speech-triviaqa"; Description="Question Answering (English)"; PostProcess="extract_text"},
    # @{Name="speech-web-questions"; Description="Question Answering (English)"; PostProcess="extract_text"}
    # @{Name="librispeech-test-clean"; Description="LibriSpeech Clean Test Set (English ASR)"; PostProcess="extract_text"},
    # @{Name="librispeech-dev-clean"; Description="LibriSpeech Clean Dev Set (English ASR)"; PostProcess="extract_text"},
    # @{Name="cv-15-en"; Description="Common Voice 15 English"; PostProcess="extract_text"},
    # @{Name="fleurs-en_us"; Description="FLEURS English US"; PostProcess="extract_text"},
    # @{Name="tedlium-test"; Description="TED-LIUM Test Set (English ASR)"; PostProcess="extract_text"},
    # @{Name="peoples_speech-test"; Description="People's Speech Test Set"; PostProcess="extract_text"}
)

# Create base results directory structure
$baseResultsDir = "res\VoiceLiveS2T"
if (!(Test-Path $baseResultsDir)) {
    New-Item -ItemType Directory -Path $baseResultsDir -Force | Out-Null
}

Write-Host "📁 Results will be saved to: $baseResultsDir\<dataset-name>\<evaluator-name>\" -ForegroundColor Cyan
Write-Host ""

# Run tests for each dataset and evaluator combination
foreach ($dataset in $datasets) {
    Write-Host "📊 Testing dataset: $($dataset.Name) - $($dataset.Description)" -ForegroundColor Magenta
    
    # Create dataset directory
    $datasetDir = "$baseResultsDir\$($dataset.Name)"
    if (!(Test-Path $datasetDir)) {
        New-Item -ItemType Directory -Path $datasetDir -Force | Out-Null
    }
    
    foreach ($eval in $evaluators) {
        Write-Host "  🔄 Testing evaluator: $($eval.Name) - $($eval.Description)" -ForegroundColor Yellow
        
        # Create subfolder for this evaluator within the dataset
        $evalDir = "$datasetDir\$($eval.Name)"
        if (!(Test-Path $evalDir)) {
            New-Item -ItemType Directory -Path $evalDir -Force | Out-Null
        }
        
        # Generate output filename
        $outputFile = "$evalDir\${timestamp}_$($eval.Name).jsonl"
        
        # Build command
        $baseCmd = "python audio_evals/main.py --dataset $($dataset.Name) --model VoiceLiveS2T --post_process $($dataset.PostProcess) --workers $Workers --limit $Limit --debug_mode 1 --save `"$outputFile`""
        
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
    }
    Write-Host ""
}

Write-Host "🏁 Test run completed!" -ForegroundColor Green
Write-Host ""

# Generate summary report
Write-Host "📊 Generating Summary Report..." -ForegroundColor Yellow

$summaryFile = "$baseResultsDir\test-summary-$timestamp.md"
$summaryContent = @"
# VoiceLive S2T Multi-Dataset Evaluator Test Summary

**Test Run:** $timestamp  
**Workers:** $Workers  
**Limit:** $Limit  
**Datasets:** $($datasets | ForEach-Object { $_.Name } | Join-String -Separator ', ')  
**Model:** VoiceLiveS2T  

## Results by Dataset and Evaluator

"@

foreach ($dataset in $datasets) {
    $summaryContent += "`n### Dataset: $($dataset.Name) - $($dataset.Description)`n`n"
    $summaryContent += "| Evaluator | Description | Status | Results File |`n"
    $summaryContent += "|-----------|-------------|--------|--------------|`n"
    
    foreach ($eval in $evaluators) {
        $evalDir = "$baseResultsDir\$($dataset.Name)\$($eval.Name)"
        $outputFile = "$evalDir\${timestamp}_$($eval.Name).jsonl"
        $overallFile = $outputFile -replace '\.jsonl$', '-overall.json'
        
        if (Test-Path $outputFile) {
            $status = "✅ Success"
            $resultPath = "$($dataset.Name)\$($eval.Name)\${timestamp}_$($eval.Name).jsonl"
        } else {
            $status = "❌ Failed"
            $resultPath = "N/A"
        }
        
        $summaryContent += "`n| ``$($eval.Name)`` | $($eval.Description) | $status | ``$resultPath`` |"
    }
}

$summaryContent += @"


## Directory Structure

``````
$baseResultsDir/
├── test-summary-$timestamp.md
"@

foreach ($dataset in $datasets) {
    $summaryContent += "`n├── $($dataset.Name)/"
    foreach ($eval in $evaluators) {
        $summaryContent += "`n│   ├── $($eval.Name)/"
        $summaryContent += "`n│   │   ├── ${timestamp}_$($eval.Name).jsonl"
        $summaryContent += "`n│   │   └── ${timestamp}_$($eval.Name)-overall.json"
    }
}

$summaryContent += @"

``````

## Usage

To view detailed results for any dataset/evaluator combination:
``````bash
# View JSONL results
cat "$baseResultsDir\<dataset-name>\<evaluator-name>\${timestamp}_<evaluator-name>.jsonl"

# View summary results  
cat "$baseResultsDir\<dataset-name>\<evaluator-name>\${timestamp}_<evaluator-name>-overall.json"
``````

## Rerun Individual Tests

``````bash
# Example: Rerun WER evaluator on llama-questions dataset
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator wer --post_process extract_text --workers $Workers --limit $Limit --save "$baseResultsDir\llama-questions\wer\custom-run.jsonl"

# Example: Rerun on different dataset
python audio_evals/main.py --dataset librispeech-test-clean --model VoiceLiveS2T --evaluator wer --post_process extract_text --workers $Workers --limit $Limit --save "$baseResultsDir\librispeech-test-clean\wer\custom-run.jsonl"
``````
"@

Set-Content -Path $summaryFile -Value $summaryContent -Encoding UTF8

Write-Host "📄 Summary report saved to: $summaryFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "🎉 All tests completed! Check the results in the dataset/evaluator subfolders." -ForegroundColor Green