// Runs an original n8n Code node body with a mocked n8n context.
// stdin:  {"node": "<file in n8n_nodes/>", "input": <$input.first().json>,
//          "nodes": {"<Node name>": {"json": {...} | [..], "binary": {...}}}}
// stdout: JSON array returned by the node ([{json: ...}, ...]); a batch (array of requests) returns an array.
'use strict';
const fs = require('fs');
const path = require('path');

const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const cache = {};
const load = (n) => (cache[n] = cache[n] || fs.readFileSync(path.join(__dirname, 'n8n_nodes', n), 'utf8'));

function runOne(req) {
const code = load(req.node);

const wrap = (entry) => {
  const list = Array.isArray(entry.json) ? entry.json : [entry.json];
  const items = list.map((j) => ({ json: j, binary: entry.binary || undefined }));
  return { first: () => items[0], all: () => items, item: items[0] };
};
const $ = (name) => {
  const e = (req.nodes || {})[name];
  if (!e) throw new Error('mock: no node ' + name);
  return wrap(e);
};
const $input = wrap({ json: req.input });
const fn = new Function('$input', '$', '$execution', code);
try { return fn($input, $, { id: 'test' }); } catch (e) { return { __error__: String(e && e.message || e) }; }
}

// a single request or an array of requests (batch: one node process for many cases)
const result = Array.isArray(payload) ? payload.map(runOne) : runOne(payload);
process.stdout.write(JSON.stringify(result));
