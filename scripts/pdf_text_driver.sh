#!/bin/zsh
# OCR staging loop with bounded quota backoff. Archive maintenance (maintain.py:
# archive-worker stop -> ingest -> retire -> restart) is NOT run automatically;
# it only runs in an explicitly authorized maintenance window.
# The QM_OCR_* overrides exist so scripts/test_pdf_text_driver.py can exercise
# the cycle logic against fixtures; production uses the defaults below.
M="${QM_OCR_M:-$HOME/Library/Application Support/QuantMind/maintenance/pdf-text-driver}"
RT="${QM_OCR_RT:-$HOME/Library/Application Support/QuantMind/tushare-client}"
ROOT="${QM_OCR_ROOT:-$HOME/Library/Application Support/QuantMind/tushare}"
ST="${QM_OCR_ST:-$HOME/Library/Application Support/QuantMind/maintenance/ocr-staging}"
STAGE="${QM_OCR_STAGE:-timeout 86400 .venv/bin/python -u -m backend.shared.tushare_document_ocr stage --root $ROOT --staging $ST --workers 1 --page-workers 2 --model glm-5.3-flash}"
BACKOFF="${QM_OCR_BACKOFF:-1800}"
PAUSE="${QM_OCR_PAUSE:-60}"
PARSE_PATTERN="${QM_OCR_PARSE_PATTERN:-run_parse.sh}"
while pgrep -f "$PARSE_PATTERN" >/dev/null; do sleep 300; done
cd "$RT" || exit 1
while true; do
  eval "$STAGE" >> "$M/ocr.log" 2>&1
  last_line=$(tail -1 "$M/ocr.log")
  if [[ "$last_line" == *"stage=no_candidates"* ]]; then
    echo "no more candidates $(date)" >> "$M/maintain.log"
    break
  fi
  if [[ "$last_line" == *"stage=quota_exceeded"* ]]; then
    echo "quota backoff ${BACKOFF}s $(date)" >> "$M/maintain.log"
    sleep "$BACKOFF"
  else
    sleep "$PAUSE"
  fi
done
