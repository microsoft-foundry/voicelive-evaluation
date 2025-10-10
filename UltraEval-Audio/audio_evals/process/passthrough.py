"""
PassThrough post-processor for audio evaluation pipeline.
This processor returns the input unchanged, effectively bypassing post-processing.
"""

from audio_evals.process.base import Process


class PassThrough(Process):
    """
    Pass-through processor that returns input unchanged.
    
    This processor is useful when you want to pass inference results
    directly to the evaluator without any post-processing transformation.
    It preserves the original data type (string, dict, list, etc.) and
    maintains JSON structure if present.
    """
    
    def __call__(self, answer):
        """
        Return the input answer unchanged, preserving its original type.
        
        Args:
            answer: The input to process (can be str, dict, list, or any type)
            
        Returns:
            The same input without any modifications, maintaining original type
        """
        return answer