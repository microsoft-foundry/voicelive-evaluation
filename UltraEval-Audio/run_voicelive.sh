export PYTHONPATH=$PWD:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=0
echo "Environment setup:"
echo "  PYTHONPATH: $PYTHONPATH"
echo "  CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
echo "  Working Directory: $(pwd)"

python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --evaluator azure-ai-batch-agent-base --post_process passthrough --limit 5
