#!/bin/zsh
# One scheduled tick (K6, K8): load the local model once, play CYCLES cycles of one society, or of every unpaused
# society in turn (NAME = all), save, unload.
#
#   scripts/tick.sh NAME [MODEL] [CYCLES]        e.g. scripts/tick.sh paper qwen/qwen3.5-35b-a3b 1
#   scripts/tick.sh all  [MODEL] [CYCLES]        every unpaused society (commons list shows them)
#
# It skips the tick, and touches nothing, when:
#   - less than MIN_FREE % of memory is free (you are using the machine)
#   - any model is already loaded in LM Studio (yours: it is never unloaded by this script)
#   - a live run holds runs/live.pid
# Every line it prints goes to runs/ticks/NAME/tick.log as well.
set -u
cd "${0:A:h}/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
NAME=${1:?usage: scripts/tick.sh NAME [MODEL] [CYCLES]}
MODEL=${2:-qwen/qwen3.5-35b-a3b}
CYCLES=${3:-1}
PACK=${PACK:-}  # only for a society's first tick; later ticks keep the pack it was built with
MIN_FREE=${MIN_FREE:-60}
LMS=~/.lmstudio/bin/lms
LOG=runs/ticks/$NAME/tick.log
mkdir -p "${LOG:h}"
say() { print -r -- "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

free=$(memory_pressure | awk -F': ' '/free percentage/ {gsub("%", "", $2); print $2}')
if (( ${free:-0} < MIN_FREE )); then say "skip: ${free:-?}% memory free (need $MIN_FREE%)"; exit 0; fi
if $LMS ps 2>/dev/null | grep -q "LOADED\|IDLE\|GENERATING"; then say "skip: a model is already loaded in LM Studio"; exit 0; fi
if [[ -f runs/live.pid ]] && kill -0 "$(cat runs/live.pid)" 2>/dev/null; then say "skip: a live run is going"; exit 0; fi

say "tick: $NAME, $CYCLES cycle(s) on $MODEL"
$LMS server start >/dev/null 2>&1
if ! $LMS load "$MODEL" --context-length 32768 -y >/dev/null 2>&1; then
  say "skip: couldn't load $MODEL"; $LMS server stop >/dev/null 2>&1; exit 1
fi
if [[ $NAME == all ]]; then
  cmd=(uv run commons tick-all --backend lmstudio --model "$MODEL" --cycles "$CYCLES")
else
  cmd=(uv run commons tick "$NAME" --backend lmstudio --model "$MODEL" --cycles "$CYCLES" ${PACK:+--pack "$PACK"})
fi
"${cmd[@]}" 2>&1 | grep -E "^(tick-all|cycle|[a-z0-9-]+: |STOPPED|KILL)" | while read -r line; do say "$line"; done
rc=${pipestatus[1]}
$LMS unload --all >/dev/null 2>&1
$LMS server stop >/dev/null 2>&1
say "done (exit $rc); model unloaded"
exit $rc
