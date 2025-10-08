az login

cd C:\Localrepos\voicelive-evaluation\UltraEval-Audio

.\.venv\Scripts\activate

$env:PYTHONPATH = "C:\Localrepos\voicelive-evaluation\UltraEval-Audio;$env:PYTHONPATH"; $env:CUDA_VISIBLE_DEVICES = "0"

# pip install -r requirments-offline-model.txt

# Override just the post-processing to avoid redundant STT
python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2T --post_process extract_text --workers 10
python audio_evals/main.py --dataset speech-web-questions --model VoiceLiveS2T --post_process extract_text --workers 10
python audio_evals/main.py --dataset speech-triviaqa --model VoiceLiveS2T --post_process extract_text --workers 10
# python audio_evals/main.py --dataset speech-web-questions --model VoiceLiveS2S --post_process extract_text --workers 3 --limit 6
# python audio_evals/main.py --dataset llama-questions --model VoiceLiveS2S --post_process extract_text --workers 20
# python audio_evals/main.py --dataset speech-web-questions --model VoiceLiveS2S --post_process extract_text --workers 20
# python audio_evals/main.py --dataset speech-triviaqa --model VoiceLiveS2S --post_process extract_text --workers 20
