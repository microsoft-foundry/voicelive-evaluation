export PYTHONPATH=$PWD:$PYTHONPATH
#CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset sample --prompt mini-cpm-omni-asr-zh --model MiniCPMo2_6-audio

pip install -r requirments-offline-model.txt
#CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset sample --model qwen2-audio-chat
#CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset llama-questions --model  MiniCPMo2_6-speech #qwen2-audio-chat
#CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset speech-web-questions --model  MiniCPMo2_6-speech #qwen2-audio-chat
#CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset speech-triviaqa	 --model  MiniCPMo2_6-speech #qwen2-audio-chat



CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset llama-questions  --model  VoiceLiveS2S  --workers 20 #qwen2-audio-chat
CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset speech-web-questions  --model  VoiceLiveS2S --workers 15 #qwen2-audio-chat
CUDA_VISIBLE_DEVICES=0 python audio_evals/main.py --dataset speech-triviaqa  --model  VoiceLiveS2S --workers 15 #qwen2-audio-chat
