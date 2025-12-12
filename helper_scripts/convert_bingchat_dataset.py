#!/usr/bin/env python3
"""
Convert BingChat Agent Test Set from JSON format to JSONL format for evaluation pipeline.

This script reads the JSON metadata files and creates JSONL files with proper field mapping:
- audio: Path to local WAV file (mapped to WavPath via col_aliases in YAML config)
- question: The transcription (ground truth text, mapped to label via col_aliases)
- answer: Empty (not provided in this dataset)
- uuid: CompareKey for reference
- audio_url: Original Azure blob storage URL (for reference)
"""

import json
import os
import argparse
from pathlib import Path


def convert_bingchat_to_jsonl(json_file_path, audio_dir_path, output_jsonl_path):
    """
    Convert BingChat JSON format to JSONL format.
    
    Args:
        json_file_path: Path to the JSON metadata file (BTEST or DTEST)
        audio_dir_path: Path to directory containing WAV files
        output_jsonl_path: Path where JSONL output will be written
    """
    # Read the JSON file
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    flow_name = data.get('FlowName', 'Unknown')
    utterances = data.get('ListOfUtterances', [])
    
    print(f"Processing {flow_name}")
    print(f"Found {len(utterances)} utterances")
    
    # Convert to JSONL format
    records = []
    missing_files = []
    
    for utterance in utterances:
        uuid = utterance.get('CompareKey', '')
        transcription = utterance.get('Transcription', '')
        audio_url = utterance.get('AudioUrl', '')
        
        # Construct local audio file path
        # The WAV files are named as {uuid}.wav
        audio_filename = f"{uuid}.wav"
        audio_path = os.path.join(audio_dir_path, audio_filename)
        
        # Check if audio file exists
        if not os.path.exists(audio_path):
            missing_files.append(audio_filename)
            continue
        
        # Create JSONL record
        record = {
            "audio": audio_path,
            "question": transcription,
            "answer": "",  # Not provided in this dataset
            "uuid": uuid,
            "audio_url": audio_url  # Keep original URL for reference
        }
        
        records.append(record)
    
    # Write JSONL file
    with open(output_jsonl_path, 'w', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    
    print(f"Successfully converted {len(records)} records to {output_jsonl_path}")
    
    if missing_files:
        print(f"Warning: {len(missing_files)} audio files not found")
        print(f"First 10 missing files: {missing_files[:10]}")
    
    return len(records), len(missing_files)


def main():
    parser = argparse.ArgumentParser(description='Convert BingChat dataset to JSONL format')
    parser.add_argument('--dataset-dir', required=True, 
                        help='Path to dataset directory (e.g., raw/BingChat_AgentTestSet_FY26/en-us_14112025)')
    parser.add_argument('--output-dir', default='.',
                        help='Output directory for JSONL files')
    parser.add_argument('--test-type', choices=['BTEST', 'DTEST', 'both'], default='both',
                        help='Which test type to convert')
    
    args = parser.parse_args()
    
    dataset_dir = Path(args.dataset_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine language from directory name
    if 'en-us' in str(dataset_dir):
        lang = 'en-us'
    elif 'fr-fr' in str(dataset_dir):
        lang = 'fr-fr'
    else:
        lang = 'unknown'
    
    test_types = ['BTEST', 'DTEST'] if args.test_type == 'both' else [args.test_type]
    
    total_records = 0
    total_missing = 0
    
    # Combine all test types into single output file when test_type is 'both'
    if args.test_type == 'both':
        output_filename = f"bingchat-agent-{lang}.jsonl"
        output_path = output_dir / output_filename
        all_records = []
        
        for test_type in test_types:
            json_filename = f"BingChat_AgentTestSet_FY26_{lang}_{test_type}_TxResults.json"
            json_path = dataset_dir / json_filename
            
            if not json_path.exists():
                print(f"Warning: {json_path} not found, skipping...")
                continue
            
            print(f"\n{'='*60}")
            print(f"Processing {test_type}...")
            print(f"{'='*60}")
            
            # Read and convert this test type
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            flow_name = data.get('FlowName', 'Unknown')
            utterances = data.get('ListOfUtterances', [])
            
            print(f"Processing {flow_name}")
            print(f"Found {len(utterances)} utterances")
            
            missing_files = []
            for utterance in utterances:
                uuid = utterance.get('CompareKey', '')
                transcription = utterance.get('Transcription', '')
                audio_url = utterance.get('AudioUrl', '')
                
                audio_filename = f"{uuid}.wav"
                audio_path = os.path.join(str(dataset_dir), audio_filename)
                
                if not os.path.exists(audio_path):
                    missing_files.append(audio_filename)
                    continue
                
                record = {
                    "audio": audio_path,
                    "question": transcription,
                    "answer": "",
                    "uuid": uuid,
                    "audio_url": audio_url
                }
                all_records.append(record)
            
            print(f"Successfully processed {len(utterances) - len(missing_files)} records")
            if missing_files:
                print(f"Warning: {len(missing_files)} audio files not found")
                print(f"First 10 missing files: {missing_files[:10]}")
            
            total_records += len(utterances) - len(missing_files)
            total_missing += len(missing_files)
        
        # Write combined output
        with open(output_path, 'w', encoding='utf-8') as f:
            for record in all_records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        print(f"\n{'='*60}")
        print(f"Combined output written to: {output_path}")
        print(f"{'='*60}")
    else:
        # Single test type - keep original behavior
        for test_type in test_types:
            json_filename = f"BingChat_AgentTestSet_FY26_{lang}_{test_type}_TxResults.json"
            json_path = dataset_dir / json_filename
            
            if not json_path.exists():
                print(f"Warning: {json_path} not found, skipping...")
                continue
            
            output_filename = f"bingchat-agent-{lang}-{test_type.lower()}.jsonl"
            output_path = output_dir / output_filename
            output_filename = f"bingchat-agent-{lang}-{test_type.lower()}.jsonl"
            output_path = output_dir / output_filename
            
            print(f"\n{'='*60}")
            print(f"Converting {test_type}...")
            print(f"{'='*60}")
            
            records, missing = convert_bingchat_to_jsonl(
                json_path,
                dataset_dir,
                output_path
            )
            
            total_records += records
            total_missing += missing
    
    print(f"\n{'='*60}")
    print(f"Conversion complete!")
    print(f"Total records: {total_records}")
    print(f"Total missing files: {total_missing}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
