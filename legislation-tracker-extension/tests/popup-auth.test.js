const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const utils = require("../extension-utils");

function popup(fetch) {
  const base = utils.DEFAULT_API_BASE;
  const stored = {
    legislation_tracker_auth_origin: new URL(base).origin,
    [utils.AUTH_TOKEN_KEY]: "access0",
    [utils.AUTH_REFRESH_KEY]: "refresh0",
  };
  const nodes = new Map();
  const document = { getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, { addEventListener() {} });
    return nodes.get(id);
  }};
  const context = vm.createContext({
    URL, fetch, document, window: { LegislationTrackerExtension: {
      ...utils, checkApiHealth: async () => {}, requestHostPermission: async () => true,
    }},
    chrome: { runtime: {}, tabs: { query: (_, done) => done([]) }, storage: { local: {
      get: (_, done) => done({...stored}),
      set: (patch, done) => { Object.assign(stored, patch); done(); },
      remove: (keys, done) => { keys.forEach(key => delete stored[key]); done(); },
    }}},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../popup.js"), "utf8"), context);
  return { context, stored, nodes };
}

test("concurrent requests share one rotation and the next rotation uses the saved token", async () => {
  let generation = 0;
  let expire = true;
  const { context, stored } = popup(async (url, init) => {
    if (url.endsWith("/refresh/")) {
      assert.equal(JSON.parse(init.body).refresh, "refresh" + generation);
      generation++;
      expire = false;
      return Response.json({ access: "access" + generation, refresh: "refresh" + generation });
    }
    return Response.json({}, { status: expire || init.headers.Authorization !== "Bearer access" + generation ? 401 : 200 });
  });
  await context.loadSettingsAndAuth();
  await Promise.all([context.authJson("/one", "GET"), context.authJson("/two", "GET")]);
  assert.equal(generation, 1);
  expire = true;
  await context.authJson("/three", "GET");
  assert.equal(stored[utils.AUTH_REFRESH_KEY], "refresh2");
});

test("saving a different API origin requires a fresh sign-in", async () => {
  const { context, nodes, stored } = popup(() => assert.fail("signed-out action made a request"));
  await context.loadSettingsAndAuth();
  nodes.get("settings-api-base").value = "https://api.example.org";
  await context.saveSettings({ preventDefault() {} });
  assert.equal(stored[utils.AUTH_TOKEN_KEY], undefined);
  assert.equal(stored[utils.AUTH_REFRESH_KEY], undefined);
  await assert.rejects(context.authJson("/action", "POST"), /Sign in/);
});

test("an in-flight refresh cannot restore a session after an endpoint change", async () => {
  let finish;
  let started;
  const refreshing = new Promise(resolve => { started = resolve; });
  const { context, nodes, stored } = popup(async url => {
    assert.equal(new URL(url).origin, new URL(utils.DEFAULT_API_BASE).origin);
    if (url.endsWith("/refresh/")) {
      started();
      return new Promise(resolve => { finish = resolve; });
    }
    return Response.json({}, { status: 401 });
  });
  await context.loadSettingsAndAuth();
  const operation = context.authJson("/action", "GET");
  await refreshing;
  nodes.get("settings-api-base").value = "https://api.example.org";
  await context.saveSettings({ preventDefault() {} });
  finish(Response.json({ access: "replacement", refresh: "rotation" }));
  await assert.rejects(operation);
  assert.equal(stored[utils.AUTH_TOKEN_KEY], undefined);
  assert.equal(stored[utils.AUTH_REFRESH_KEY], undefined);
});
