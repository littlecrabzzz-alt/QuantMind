#!/bin/zsh
# Archive maintenance (maintain.py: worker stop-if-running -> hold -> ingest ->
# retire by original rules -> restore original worker state) runs automatically at
# most once per MAINTAIN_CADENCE seconds via the .last-maintain marker; a failed
# pass defers to the next cycle instead of crashing the loop. Authorized manual
# windows can also run maintain.py directly.
# The QM_OCR_* overrides exist so scripts/test_pdf_text_driver.py can exercise
# the cycle logic against fixtures (QM_OCR_PY substitutes the python executable,
# including a fixture script that prints stage markers); production uses the
# defaults below. No eval: paths stay individually quoted.
M="${QM_OCR_M:-$HOME/Library/Application Support/QuantMind/maintenance/pdf-text-driver}"
RT="${QM_OCR_RT:-$HOME/Library/Application Support/QuantMind/tushare-client}"
ROOT="${QM_OCR_ROOT:-$HOME/Library/Application Support/QuantMind/tushare}"
ST="${QM_OCR_ST:-$HOME/Library/Application Support/QuantMind/maintenance/ocr-staging}"
PY="${QM_OCR_PY:-.venv/bin/python}"
BACKOFF="${QM_OCR_BACKOFF:-1800}"
PAUSE="${QM_OCR_PAUSE:-60}"
PARSE_PATTERN="${QM_OCR_PARSE_PATTERN:-run_parse.sh}"
MAINTAIN_CADENCE="${QM_OCR_MAINTAIN_CADENCE:-86400}"
while pgrep -f "$PARSE_PATTERN" >/dev/null; do sleep 300; done
cd "$RT" || exit 1

maybe_maintain() {
  local marker="$M/.last-maintain"
  [[ -f "$marker" ]] || { touch "$marker"; return 0; }
  if (( $(date +%s) - $(stat -f %m "$marker") >= MAINTAIN_CADENCE )); then
    echo "periodic maintain start $(date)" >> "$M/maintain.log"
    if "$PY" -u "$M/maintain.py" >> "$M/maintain.log" 2>&1; then
      touch "$marker"
      echo "periodic maintain done $(date)" >> "$M/maintain.log"
    else
      echo "periodic maintain deferred, retry next cycle $(date)" >> "$M/maintain.log"
    fi
  fi
}
while true; do
  timeout 86400 "$PY" -u -m backend.shared.tushare_document_ocr stage \
    --root "$ROOT" --staging "$ST" --workers 1 --page-workers 2 \
    --model glm-5.3-flash >> "$M/ocr.log" 2>&1
  last_line=$(tail -1 "$M/ocr.log")
  if [[ "$last_line" == *"stage=no_candidates"* ]]; then
    echo "no more candidates $(date)" >> "$M/maintain.log"
    pending=$(find "$ST" -maxdepth 1 -name '*.json' -type f 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$pending" -gt 0 ]]; then
      # The queue is done; never exit leaving staged text un-ingested. Busy (75)
      # retries with backoff instead of quitting silently.
      while true; do
        echo "final drain start (${pending} staged) $(date)" >> "$M/maintain.log"
        if "$PY" -u "$M/maintain.py" >> "$M/maintain.log" 2>&1; then
          touch "$M/.last-maintain"
          echo "final drain done $(date)" >> "$M/maintain.log"
          break
        fi
        echo "final drain busy/failed; retry in ${BACKOFF}s $(date)" >> "$M/maintain.log"
        sleep "$BACKOFF"
        pending=$(find "$ST" -maxdepth 1 -name '*.json' -type f 2>/dev/null | wc -l | tr -d ' ')
      done
    else
      maybe_maintain
    fi
    break
  fi
  if [[ "$last_line" == *"stage=quota_exceeded"* ]]; then
    echo "quota backoff ${BACKOFF}s $(date)" >> "$M/maintain.log"
    sleep "$BACKOFF"
  else
    sleep "$PAUSE"
  fi
  maybe_maintain
done
