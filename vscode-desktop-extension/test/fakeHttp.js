'use strict';

// Replaces https.get for one test, so the code that reads ghcr.io or PyPI runs
// without the network. `routes(url, headers)` returns { status, body, headers }
// or throws to simulate a connection error.

const https = require('https');
const { EventEmitter } = require('events');
const { PassThrough } = require('stream');

function stubHttpsGet(t, routes) {
  const requests = [];
  const original = https.get;
  https.get = (url, options, callback) => {
    const request = new EventEmitter();
    request.destroy = (error) => request.emit('error', error || new Error('destroyed'));
    const headers = (options && options.headers) || {};
    requests.push({ url: String(url), headers });
    setImmediate(() => {
      let answer;
      try {
        answer = routes(String(url), headers);
      } catch (error) {
        request.emit('error', error);
        return;
      }
      if (answer === 'timeout') {
        request.emit('timeout');
        return;
      }
      const res = new PassThrough();
      res.statusCode = answer.status || 200;
      res.headers = answer.headers || {};
      callback(res);
      res.end(typeof answer.body === 'string' ? answer.body : JSON.stringify(answer.body || ''));
    });
    return request;
  };
  t.after(() => { https.get = original; });
  return requests;
}

module.exports = { stubHttpsGet };
