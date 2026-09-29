// Narrow local observation of Pi's actual fetch request. Never retain headers/body.
const fs = require('node:fs');
let transportFetch = globalThis.fetch;
const callId = process.env.QM_TRACE_CALL_ID;
const file = process.env.QM_TRACE_WIRE_FILE;
if (!/^[0-9a-f]{32}$/.test(callId || '') || !file || typeof transportFetch !== 'function') {
  throw new Error('glm_wire_trace_configuration_invalid');
}
let attempt = 0;
async function observedFetch(input, init) {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  if (url.origin !== 'https://open.bigmodel.cn' || url.pathname !== '/api/coding/paas/v4/chat/completions') {
    return transportFetch(input, init);
  }
  let body;
  try {
    const raw = init?.body ?? (input instanceof Request ? await input.clone().text() : null);
    if (typeof raw !== 'string') throw new Error();
    body = JSON.parse(raw);
  } catch { throw new Error('glm_wire_request_unobservable'); }
  if (body.model !== 'glm-5.3' || body.reasoning_effort !== 'max') {
    throw new Error('glm_wire_model_effort_mismatch');
  }
  const event = {event: 'wire_request', at: Date.now() / 1000, call_id: callId,
    attempt: ++attempt, model: body.model, reasoning_effort: body.reasoning_effort,
    max_tokens: Number.isSafeInteger(body.max_tokens) && body.max_tokens > 0 ? body.max_tokens : null,
    observation: 'fetch_request_before_transport'};
  const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT |
    fs.constants.O_APPEND | fs.constants.O_NOFOLLOW, 0o600);
  try {
    const info = fs.fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid()) {
      throw new Error('unsafe_wire_trace_file');
    }
    fs.fchmodSync(fd, 0o600);
    fs.writeSync(fd, JSON.stringify(event) + '\n');
    fs.fsyncSync(fd);
  } finally { fs.closeSync(fd); }
  return transportFetch(input, init);
}
// Pi installs undici after preloads. Keep observing its replacement transport,
// rather than letting that ordinary initialization silently remove this guard.
Object.defineProperty(globalThis, 'fetch', {
  configurable: true,
  enumerable: true,
  get: () => observedFetch,
  set: value => {
    if (typeof value !== 'function') throw new Error('glm_wire_fetch_replacement_invalid');
    if (value !== observedFetch) transportFetch = value;
  },
});
