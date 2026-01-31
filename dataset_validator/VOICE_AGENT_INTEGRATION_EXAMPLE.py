"""
Example: Voice Agent Integration with Dataset Validators

This script demonstrates how an AI agent or automated system would
integrate the dataset validators into a voice evaluation pipeline.

Use Case:
    An agent needs to validate a dataset before running voice agent evaluations.
    The agent should check consistency first, then quality, then proceed to evaluation.
"""

import sys
from pathlib import Path
from validate_dataset_consistency import DatasetConsistencyValidator
from validate_dataset_quality import DatasetQualityValidator


def validate_dataset_for_evaluation(dataset_path: str, strict_quality: bool = False) -> bool:
    """
    Agent-friendly function to validate a dataset before evaluation.
    
    This function orchestrates the validation workflow:
    1. Consistency validation (must pass)
    2. Quality validation (advisory)
    3. Decision to proceed
    
    Args:
        dataset_path: Path to JSONL file or folder containing dataset
        strict_quality: Use strict alignment matching for quality (default: False)
    
    Returns:
        bool: True if dataset is ready for evaluation, False otherwise
    
    Example:
        >>> if validate_dataset_for_evaluation("dataset.jsonl"):
        ...     run_voice_evaluation("dataset.jsonl")
    """
    
    print("=" * 80)
    print("  AUTOMATED DATASET VALIDATION WORKFLOW")
    print("=" * 80)
    
    # STEP 1: Consistency Validation (MANDATORY)
    print("\n[STEP 1] Checking dataset consistency...")
    print("   This ensures the dataset is structurally sound.")
    
    try:
        consistency_validator = DatasetConsistencyValidator(
            dataset_path,
            ignore_comments=True  # Handle test datasets with comments
        )
        
        is_consistent = consistency_validator.validate()
        
        if not is_consistent:
            print("\n❌ CONSISTENCY VALIDATION FAILED")
            print("\n   Critical errors found:")
            for error in consistency_validator.errors:
                print(f"     • {error}")
            
            if consistency_validator.warnings:
                print("\n   Warnings:")
                for warning in consistency_validator.warnings:
                    print(f"     ⚠ {warning}")
            
            print("\n   ⛔ Cannot proceed to evaluation. Fix errors first.")
            return False
        
        print("\n✅ CONSISTENCY VALIDATION PASSED")
        print("   Dataset structure is valid.")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False
    
    # STEP 2: Quality Validation (ADVISORY)
    print("\n\n[STEP 2] Assessing dataset quality...")
    print("   This evaluates content appropriateness.")
    
    try:
        quality_validator = DatasetQualityValidator(
            dataset_path,
            strict=strict_quality,
            ignore_comments=True
        )
        
        results = quality_validator.validate()
        
        if results.get('status') != 'success':
            print("\n⚠ QUALITY VALIDATION ENCOUNTERED ISSUES")
            return False
        
        # Evaluate quality metrics
        alignment = results.get('prompt_alignment', 0)
        tool_assessment = results.get('tool_assessment', 'unknown')
        quality_score = results.get('content_quality', 0)
        
        print(f"\n QUALITY METRICS:")
        print(f"   • Prompt Alignment: {alignment:.1f}%")
        print(f"   • Tool Assessment: {tool_assessment}")
        print(f"   • Content Quality: {quality_score}/3")
        
        # Decision logic
        quality_issues = []
        
        if alignment < 50:
            quality_issues.append("Low prompt alignment (<50%)")
        elif alignment < 70:
            print("\n   ⚠ Moderate alignment - consider review")
        else:
            print("\n   ✅ Good alignment")
        
        if tool_assessment == 'needs_review':
            quality_issues.append("Tool definitions need review")
        
        if quality_score < 2:
            quality_issues.append("Low content quality score")
        
        if quality_issues:
            print("\n⚠ QUALITY CONCERNS DETECTED:")
            for issue in quality_issues:
                print(f"     • {issue}")
            print("\n   Recommendation: Review dataset before evaluation")
            print("   However, evaluation can proceed if acceptable.")
            
            # Agent decision: proceed with warnings
            return True
        
        print("\n✅ QUALITY VALIDATION PASSED")
        print("   Dataset quality is good.")
        
    except Exception as e:
        print(f"\n⚠ Quality validation error: {str(e)}")
        print("   Proceeding with caution...")
    
    # STEP 3: Decision
    print("\n\n✅ VALIDATION COMPLETE - READY FOR EVALUATION")
    return True


def main():
    """Example usage for an AI agent."""
    
    # Example 1: Validate a production dataset
    print("\nEXAMPLE 1: Production Dataset")
    dataset_path = "local_datasets/DataOcean/20260122-wave1-50"
    
    if validate_dataset_for_evaluation(dataset_path):
        print("\n✅ Agent would now proceed to voice evaluation...")
        # run_voice_evaluation(dataset_path)
    else:
        print("\n❌ Agent would halt and request dataset fixes...")
    
    print("\n" + "=" * 80)
    print("\nEXAMPLE 2: Strict Quality Mode")
    
    # Example 2: Use strict quality validation
    if validate_dataset_for_evaluation(dataset_path, strict_quality=True):
        print("\n✅ Agent confirms domain expertise in dataset...")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
