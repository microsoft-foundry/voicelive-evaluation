#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Seeds the sessionconfigs Azure Table with default configurations.
.DESCRIPTION
    This script populates the sessionconfigs table with pre-defined VoiceLive
    session configurations for different evaluation scenarios.
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$StorageAccountName
)

Write-Host "Seeding session configs to table storage..."
Write-Host "Storage Account: $StorageAccountName"

# Default session configs
$configs = @(
    @{
        RowKey = "default"
        PartitionKey = "voicelive"
        Name = "default"
        Description = "Default configuration - 24kHz, Azure Semantic VAD, EOU enabled"
        Model = "gpt-4.1"
        SampleRate = "24000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "azure_semantic_vad_multilingual"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "true"
        EouModel = "azure_semantic_v1_multilingual"
        TranscriptionModel = "azure-speech"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "true"
        PushToTalk = "false"
    },
    @{
        RowKey = "conf1"
        PartitionKey = "voicelive"
        Name = "conf1"
        Description = "16kHz, Server VAD, gpt-realtime"
        Model = "gpt-realtime"
        SampleRate = "16000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "server_vad"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "false"
        EouModel = ""
        TranscriptionModel = "gpt-4o-transcribe"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
    },
    @{
        RowKey = "conf2"
        PartitionKey = "voicelive"
        Name = "conf2"
        Description = "16kHz, Server VAD, gpt-realtime-mini"
        Model = "gpt-realtime-mini"
        SampleRate = "16000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "server_vad"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "false"
        EouModel = ""
        TranscriptionModel = "gpt-4o-mini-transcribe"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
    },
    @{
        RowKey = "conf3"
        PartitionKey = "voicelive"
        Name = "conf3"
        Description = "16kHz, Server VAD, gpt-4.1 with EOU"
        Model = "gpt-4.1"
        SampleRate = "16000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "server_vad"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "true"
        EouModel = "azure_semantic_v1_multilingual"
        TranscriptionModel = "azure-speech"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
    },
    @{
        RowKey = "conf4"
        PartitionKey = "voicelive"
        Name = "conf4"
        Description = "24kHz, Azure Semantic VAD, gpt-realtime"
        Model = "gpt-realtime"
        SampleRate = "24000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "azure_semantic_vad_multilingual"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "false"
        EouModel = ""
        TranscriptionModel = "gpt-4o-transcribe"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
    },
    @{
        RowKey = "conf5"
        PartitionKey = "voicelive"
        Name = "conf5"
        Description = "24kHz, Azure Semantic VAD, gpt-realtime-mini"
        Model = "gpt-realtime-mini"
        SampleRate = "24000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "azure_semantic_vad_multilingual"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "false"
        EouModel = ""
        TranscriptionModel = "gpt-4o-mini-transcribe"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
    },
    @{
        RowKey = "conf6"
        PartitionKey = "voicelive"
        Name = "conf6"
        Description = "24kHz, Azure Semantic VAD, gpt-4.1 with EOU"
        Model = "gpt-4.1"
        SampleRate = "24000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "azure_semantic_vad_multilingual"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "true"
        EouModel = "azure_semantic_v1_multilingual"
        TranscriptionModel = "azure-speech"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
    },
    @{
        RowKey = "push-to-talk"
        PartitionKey = "voicelive"
        Name = "push-to-talk"
        Description = "Push-to-talk mode - 24kHz, gpt-4.1, explicit audio commit (no VAD end detection)"
        Model = "gpt-4.1"
        SampleRate = "24000"
        VoiceName = "alloy"
        VoiceType = "preset"
        VadType = "azure_semantic_vad_multilingual"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "true"
        EouModel = "azure_semantic_v1_multilingual"
        TranscriptionModel = "azure-speech"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "true"
    },
    @{
        RowKey = "agent-mode"
        PartitionKey = "voicelive"
        Name = "agent-mode"
        Description = "Agent mode - Foundry Agent integration (voicelive-demo-agent). Agent manages instructions and tools."
        Model = ""
        SampleRate = "24000"
        VoiceName = "en-US-Ava:DragonHDLatestNeural"
        VoiceType = "azure-standard"
        VadType = "azure_semantic_vad_multilingual"
        VadThreshold = ""
        SilenceDurationMs = ""
        EouDetection = "true"
        EouModel = "semantic_detection_v1_multilingual"
        TranscriptionModel = "azure-speech"
        NoiseReduction = "azure_deep_noise_suppression"
        EchoCancellation = "server_echo_cancellation"
        IsDefault = "false"
        PushToTalk = "false"
        AgentName = "voicelive-demo-agent"
        ProjectName = ""
        AgentVersion = ""
    }
)

$successCount = 0
foreach ($config in $configs) {
    # Build entity string from hashtable
    $entityParts = @()
    foreach ($key in $config.Keys) {
        $value = $config[$key]
        $entityParts += "$key=$value"
    }
    $entityString = $entityParts -join " "
    
    # Use az storage entity insert (auto-gets account key)
    $result = az storage entity insert `
        --account-name $StorageAccountName `
        --table-name sessionconfigs `
        --if-exists replace `
        --entity $entityParts 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Seeded: $($config['Name'])"
        $successCount++
    } else {
        Write-Host "  ✗ Failed $($config['Name']): $result" -ForegroundColor Red
    }
}

Write-Host "`nSeeded $successCount/$($configs.Count) session configs"

if ($successCount -eq $configs.Count) {
    Write-Host "`n✓ Session configs seeded successfully" -ForegroundColor Green
} else {
    Write-Host "`n⚠ Some configs failed to seed" -ForegroundColor Yellow
    exit 1
}
