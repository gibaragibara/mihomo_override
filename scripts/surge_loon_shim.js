// Surge / Loon / QuanX script compatibility shim for Anywhere MITM.
// Prepended to converted third-party scripts so process(ctx) can run them.
(function () {
  "use strict";

  function headersToObject(headers) {
    var out = {};
    if (!headers) return out;
    for (var i = 0; i < headers.length; i++) {
      var pair = headers[i];
      if (!pair || pair.length < 2) continue;
      var name = String(pair[0]).toLowerCase();
      if (out[name] === undefined) out[name] = String(pair[1]);
    }
    return out;
  }

  function decodeBody(body) {
    if (!body || body.length === 0) return "";
    try {
      return Anywhere.codec.utf8.decode(body);
    } catch (e) {
      return "";
    }
  }

  function encodeBody(value) {
    if (value == null) return new Uint8Array(0);
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    return Anywhere.codec.utf8.encode(String(value));
  }

  function makeBodyProperty(phase, ctx, storage, isBytes) {
    return {
      get: function () {
        if (phase === "request" && ctx.phase !== "request") return isBytes ? new Uint8Array(0) : "";
        if (phase === "response" && ctx.phase !== "response") return isBytes ? new Uint8Array(0) : null;
        return isBytes ? ctx.body : decodeBody(ctx.body);
      },
      set: function (value) {
        storage.value = value;
        ctx.body = encodeBody(value);
      },
      configurable: true,
    };
  }

  globalThis.__awSetupSurgeLoonShim = function (ctx, argumentValue) {
    var requestBodyStore = { value: null };
    var responseBodyStore = { value: null };
    var responseBytesStore = { value: null };
    var donePayload = null;

    globalThis.$done = function (obj) {
      if (!obj) {
        donePayload = {};
        return;
      }
      if (obj.abort) {
        donePayload = { abort: true };
        return;
      }
      donePayload = obj.response ? obj.response : obj;
    };

    globalThis.$persistentStore = {
      read: function (key) {
        return Anywhere.store.getString(key);
      },
      write: function (value, key) {
        try {
          Anywhere.store.set(key, String(value));
          return true;
        } catch (e) {
          return false;
        }
      },
    };

    globalThis.$prefs = {
      valueForKey: function (key) {
        return Anywhere.store.getString(key);
      },
      setValueForKey: function (value, key) {
        try {
          Anywhere.store.set(key, String(value));
        } catch (e) {}
      },
    };

    globalThis.$notify = function () {};
    globalThis.$notification = { post: function () {} };

    globalThis.$httpClient = {
      get: function (options, callback) {
        invokeHttp("GET", options, callback);
      },
      post: function (options, callback) {
        invokeHttp("POST", options, callback);
      },
      put: function (options, callback) {
        invokeHttp("PUT", options, callback);
      },
      delete: function (options, callback) {
        invokeHttp("DELETE", options, callback);
      },
    };

    function invokeHttp(method, options, callback) {
      var opts = options || {};
      var url = opts.url || "";
      var headers = [];
      if (opts.headers) {
        if (Array.isArray(opts.headers)) {
          headers = opts.headers;
        } else {
          for (var key in opts.headers) {
            if (Object.prototype.hasOwnProperty.call(opts.headers, key)) {
              headers.push([key, String(opts.headers[key])]);
            }
          }
        }
      }
      var req = {
        url: url,
        method: method,
        headers: headers,
        timeout: opts.timeout || 10000,
      };
      if (opts.body != null) {
        req.body = opts.body;
      }
      Anywhere.http.request(req)
        .then(function (resp) {
          callback(null, { status: resp.status, statusCode: resp.status, headers: resp.headers }, resp.body);
        })
        .catch(function (err) {
          callback(err || new Error("request failed"));
        });
    }

    var reqHeaders = headersToObject(ctx.headers);
    var req = {
      url: ctx.url || "",
      method: ctx.method || "GET",
      headers: reqHeaders,
    };
    Object.defineProperty(req, "body", makeBodyProperty("request", ctx, requestBodyStore, false));
    Object.defineProperty(req, "bodyBytes", makeBodyProperty("request", ctx, requestBodyStore, true));
    globalThis.$request = req;

    var resp = {
      status: ctx.status || 200,
      headers: reqHeaders,
    };
    Object.defineProperty(resp, "body", makeBodyProperty("response", ctx, responseBodyStore, false));
    Object.defineProperty(resp, "bodyBytes", makeBodyProperty("response", ctx, responseBytesStore, true));
    globalThis.$response = resp;

    if (argumentValue == null) {
      globalThis.$argument = {};
    } else if (typeof argumentValue === "string") {
      try {
        globalThis.$argument = JSON.parse(argumentValue);
      } catch (e) {
        globalThis.$argument = argumentValue;
      }
    } else {
      globalThis.$argument = argumentValue;
    }

    return {
      applyDone: function () {
        if (donePayload && donePayload.abort) {
          return false;
        }
        if (donePayload && donePayload.body != null) {
          ctx.body = encodeBody(donePayload.body);
          return true;
        }
        if (responseBodyStore.value != null) {
          ctx.body = encodeBody(responseBodyStore.value);
          return true;
        }
        if (responseBytesStore.value != null) {
          ctx.body = encodeBody(responseBytesStore.value);
          return true;
        }
        return false;
      },
    };
  };
})();