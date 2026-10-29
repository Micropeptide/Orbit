#!/bin/bash
#SBATCH -J qwen-serve
#SBATCH -t 24:00:00
#SBATCH -c 16
#SBATCH --mem=128G
#SBATCH --gres=gpu:1
#SBATCH -o /dev/null
# Serves one model with vLLM on one GPU, for Orbit (Settings -> Cluster models). Orbit passes the settings below as
# environment variables (sbatch --export=ALL,NAME=value) and the resources as sbatch flags; every one has a default.
#   MAXLEN  context length (tokens)         SEQS    requests answered at once        GPUUTIL  share of GPU memory
#   MTP     look-ahead tokens (0 = off)     EAGER   1 = skip compile + graphs       BATCHED  tokens read per step (prefill)
#   KVDTYPE auto|fp8 (fp8 = double context memory)   ASYNC 1 = async scheduling      GPUS     tensor parallel size
#   TEMP / TOPP / TOPK   sampling defaults for requests that do not say             TLIMIT_H job time limit, for the notices
#   KEEPLOG 1 = keep a server and request log (text of chats!) in $D/logs   ERRLOG 0 = keep no error log (default: kept, no chat text)   NOTIFY_TO / NOTIFY_EVENTS / MODEL_LABEL  mail
# Copy this file into a new model's folder and change D, the -J name, --served-model-name and the two parsers.
D=/path/to/project/user/Models/qwen-server
umask 077
S=${TMPDIR:-/work/$USER/$SLURM_JOB_ID}; mkdir -p $S
mkdir -p $D/run; chmod 700 $D/run
KEY=$(head -c 24 /dev/urandom | base64 | tr -d "/+=")
PORT=$((20000 + SLURM_JOB_ID % 20000))
printf "%s %s %s\n" "$(hostname -s)" "$PORT" "$KEY" > $D/run/$SLURM_JOB_ID     # how Orbit finds it: node port key
source /etc/profile.d/modules.sh 2>/dev/null; module load cuda/12.8 2>/dev/null       # vLLM's sampler wants nvcc

# ---- environment
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True              # long contexts fragment memory otherwise
export TORCHINDUCTOR_COMPILE_THREADS=${SLURM_CPUS_ON_NODE:-8}         # compiling used one thread
# compiled kernels only (no requests, no text): kept between jobs, so a start does not recompile everything
C=$D/cache; mkdir -p $C
export VLLM_CACHE_ROOT=$C/vllm TORCHINDUCTOR_CACHE_DIR=$C/inductor TRITON_CACHE_DIR=$C/triton HOME=$S

# ---- notices from the job itself, through the cluster's own mail: they arrive with the Mac off.
# What they say: the job and the model, never anything from a chat.
MAILCMD=${MAILCMD:-mail}
LABEL=${MODEL_LABEL//_/ }; LABEL=${LABEL:-the model}
notify() {   # notify EVENT SUBJECT BODY
  [ -n "$NOTIFY_TO" ] || return 0
  case ":$NOTIFY_EVENTS:" in *":$1:"*) ;; *) return 0;; esac
  printf "%s\n" "$3" | $MAILCMD -s "[Orbit] $2" "$NOTIFY_TO" 2>/dev/null
}
mins() { echo $(( SECONDS / 60 )); }
finish() {     # on the way out, however it ends (cancelled, time limit, crash)
  if [ -n "$MOVED" ]; then return 0                       # handed over to another node (see the preflight): nothing to report
  elif [ -f $S/ready ]; then
    why="it was stopped"
    [ $SECONDS -ge $(( ${TLIMIT_H:-24} * 3600 - 180 )) ] && why="its time limit ran out"
    notify stopped "$LABEL stopped" "$LABEL stopped: $why.
Job $SLURM_JOB_ID on $(hostname -s), up for about $(( ($SECONDS - $(cat $S/ready)) / 60 )) min."
  else
    # one mail per three hours at most: a job that keeps failing the same way must not fill the inbox; and say why
    LASTMAIL=$D/run/lastfailmail; NOWS=$(date +%s)
    if ! { [ -f $LASTMAIL ] && [ $(( NOWS - $(cat $LASTMAIL 2>/dev/null || echo 0) )) -lt 10800 ]; }; then
      echo $NOWS > $LASTMAIL
      CAUSE=$(grep -h -i -m6 "out of memory\|not compatible\|RuntimeError\|ValueError\|no space\|Killed" $D/logs/errors.$SLURM_JOB_ID.log 2>/dev/null | grep -v 'File "' | tail -2 | cut -c1-170)
      notify failed "$LABEL did not come up" "$LABEL ended after $(mins) min without ever answering.
Job $SLURM_JOB_ID on $(hostname -s).${CAUSE:+
Why, from its log: $CAUSE}
Orbit keeps the node out of the next start. (More failures in the next three hours are not mailed.)"
    fi
  fi
}
trap 'finish; rm -rf $S $D/run/$SLURM_JOB_ID' EXIT

# ---- moving to another node: submit the same job again without this node (at most 3 hops), remember the node as bad, end this one quietly.
hop_away() {   # hop_away REASON ; returns only when it could not hand over
  echo "$(hostname -s) $(date +%s) $1" >> $D/run/badnodes 2>/dev/null
  HOPS=${HOPS:-0}; EXCL="${EXCLUDE:+$EXCLUDE,}$(hostname -s)"
  if [ "$HOPS" -lt 3 ]; then
    NEW=$(sbatch --parsable --export=ALL,HOPS=$((HOPS + 1)),EXCLUDE=$EXCL -t ${TLIMIT_H:-24}:00:00 -c ${SLURM_CPUS_ON_NODE:-16} \
          --mem=${SLURM_MEM_PER_NODE:-131072}M --gres=gpu:${GPUS:-1} --exclude=$EXCL ${CONSTRAINT:+--constraint="$CONSTRAINT"} $D/serve.sbatch 2>/dev/null)
    case "$NEW" in [0-9]*) MOVED=1
      notify moved "$LABEL moved to another node" "$(hostname -s) was not usable ($1), so job $SLURM_JOB_ID was replaced by job ${NEW%%;*} on another node."
      exit 0;;
    esac
  fi
}

# ---- preflight 1: is this GPU big enough and free? A card with too little memory fails loading the model after minutes (seen: a 40 GB card, four jobs in a row, and an
# 8 GB card), and a card another job is already filling leaves nothing to load into. Orbit asks the scheduler for big-enough GPUs (MINVRAM_GB); this catches the rest.
if [ "${MINVRAM_GB:-0}" -gt 0 ] && command -v nvidia-smi >/dev/null 2>&1; then
  read TOTMB USEDMB <<< "$(nvidia-smi --query-gpu=memory.total,memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr ',' ' ')"
  if [ -n "$TOTMB" ] && { [ "$TOTMB" -lt $(( MINVRAM_GB * 1000 )) ] || [ "${USEDMB:-0}" -gt 2000 ]; }; then
    hop_away "its GPU has ${TOTMB} MB of memory with ${USEDMB:-0} MB already in use; the model needs ${MINVRAM_GB} GB free"
  fi
fi

# ---- preflight 2: can this node read the model files at all? Now and then a node cannot (its reads of the project disk stall: the
# process sits in uninterruptible I/O wait, the job shows "loading" for ever and nothing is logged). Read 200 MB of the biggest weight
# file with a time limit; if that does not finish, move to another node.
PRE=$(ls -S $D/model/*.safetensors 2>/dev/null | head -1)
if [ -n "$PRE" ] && ! timeout -k 5 ${PREFLIGHT_S:-90} dd if="$PRE" of=/dev/null bs=1048576 count=200 skip=$((RANDOM % 40)) 2>/dev/null; then
  hop_away "a 200 MB read of the model files did not finish in ${PREFLIGHT_S:-90} s"          # could not hand over: carry on and try to load here
fi

# ---- wait until it answers, then warm it up and say so
(
  for i in $(seq 1 360); do
    sleep 10
    R=$(curl -s -m 5 -H "Authorization: Bearer $KEY" http://127.0.0.1:$PORT/v1/models)
    case "$R" in *max_model_len*)
      echo $SECONDS > $S/ready
      # the first real request would otherwise pay for kernels that are loaded lazily
      curl -s -m 120 -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" http://127.0.0.1:$PORT/v1/chat/completions \
        -d '{"model":"qwen","messages":[{"role":"user","content":"hi"}],"max_tokens":8}' > /dev/null 2>&1
      CTX=$(printf "%s" "$R" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"][0]["max_model_len"])' 2>/dev/null)
      notify ready "$LABEL is ready" "$LABEL is up and answering.
Context length: ${CTX:-?} tokens
Node: $(hostname -s)   Job: $SLURM_JOB_ID
Took about $(mins) min to load. The job ends by itself after ${TLIMIT_H:-24} h."
      exit 0;;
    esac
  done
) &

# ---- the libraries first, in the foreground and in big sequential reads: Python would otherwise page them in a few KB at a time,
# ~1 MB/s on a cold node (seen: 10+ minutes in uninterruptible I/O wait before the first line). 8 GB of them take about a minute.
timeout 600 bash -c "find $D/venv -name '*.so*' -size +2M -print0 2>/dev/null | xargs -0 -P 8 -n 1 cat > /dev/null 2>&1"

# ---- read the weights in parallel while Python starts: shard by shard from the network disk took ~5 minutes cold
ls $D/model/*.safetensors 2>/dev/null | xargs -P 8 -n 1 cat > /dev/null 2>&1 &

# ---- logging. No request is ever logged by default (--no-enable-log-requests). Statistics (speed, queue, cache use) stay on:
# counters and timings, nothing from a chat. What happens to the server's own output (startup steps, warnings, errors):
#   default (ERRLOG=1): kept in $D/logs/errors.<job>.log for the START ONLY: writing stops for good the moment the server answers (the
#                       $S/ready flag the watcher below writes), which is before the first chat can reach it, so no chat can ever be in it.
#                       As a second guard, lines with prompt/messages/content fields are dropped, lines are cut at 300 characters and the
#                       file at 4000 lines. This is what tells you WHY a start failed. Nothing is kept about the time it is serving.
#   ERRLOG=0:           thrown away (/dev/null)
#   KEEPLOG=1:          the whole output and the log of every request, which HAS the text of chats
# All in $D/logs, this user only (0700); older files go after 14 days.
LOGARGS=(--no-enable-log-requests)
mkdir -p $D/logs; chmod 700 $D/logs
find $D/logs -name "serve.*.log" -mtime +14 -delete 2>/dev/null; find $D/logs -name "errors.*.log" -mtime +14 -delete 2>/dev/null
if [ -n "$KEEPLOG" ]; then
  SERVE_LOG=$D/logs/serve.$SLURM_JOB_ID.log; LOGARGS=(--enable-log-requests)
  exec > "$SERVE_LOG" 2>&1
elif [ "${ERRLOG:-1}" != 0 ]; then
  cat > $S/filter.awk <<'AWK'
# the flag file exists once the server answers: from then on everything is read and thrown away
stopped == 0 { if ((getline line < flag) > 0) stopped = 1; close(flag) }
stopped { next }
/prompt_token_ids|prompt=|messages=|input_value|"content"|'content'|"role"|'role'/ { next }
{ if (length($0) > 300) $0 = substr($0, 1, 300) " ..."; if (n < 4000) { print; n++; fflush() } }
AWK
  exec > >(awk -v flag=$S/ready -f $S/filter.awk >> $D/logs/errors.$SLURM_JOB_ID.log) 2>&1
else
  exec > /dev/null 2>&1
fi

# ---- the optional arguments
SPEC=(); [ "${MTP:-2}" != 0 ] && SPEC=(--speculative-config "{\"method\":\"mtp\",\"num_speculative_tokens\":${MTP:-2}}")
KV=();   [ -n "$KVDTYPE" ] && [ "$KVDTYPE" != auto ] && KV=(--kv-cache-dtype "$KVDTYPE")
ASYNCARG=(); [ -n "$ASYNC" ] && ASYNCARG=(--async-scheduling)
SAMPLING=(--override-generation-config "{\"temperature\":${TEMP:-0.6},\"top_p\":${TOPP:-0.95},\"top_k\":${TOPK:-20}}")

$D/venv/bin/vllm serve $D/model --served-model-name qwen \
  --host 127.0.0.1 --port $PORT --api-key "$KEY" \
  --max-num-seqs ${SEQS:-32} --max-model-len ${MAXLEN:-262144} --gpu-memory-utilization ${GPUUTIL:-0.90} \
  --max-num-batched-tokens ${BATCHED:-16384} --tensor-parallel-size ${GPUS:-1} ${EAGER:+--enforce-eager} \
  --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  "${SPEC[@]}" "${KV[@]}" "${ASYNCARG[@]}" "${SAMPLING[@]}" "${LOGARGS[@]}"
