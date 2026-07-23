(() => {
  "use strict";

  const STORAGE_KEY = "outo_llms_session";
  const LEGACY_STORAGE_KEY = "outo_llms_api_key";
  const INFERENCE_KEYS_STORAGE_KEY = "outo_llms_keys";
  const SIGN_IN_MIGRATION_NOTICE = "Sign-in changed: please log in with your username and password (API keys are now only for inference).";
  const migratedLegacyKey = removeLegacyApiKey();
  const elements = {
    appShell: document.getElementById("app-shell"),
    modalRoot: document.getElementById("modal-root"),
    nav: document.getElementById("main-nav"),
    noticeRegion: document.getElementById("notice-region"),
    profileMenu: document.getElementById("profile-menu"),
    profileTrigger: document.getElementById("profile-trigger"),
    viewRoot: document.getElementById("view-root"),
  };

  const numberFormat = new Intl.NumberFormat(undefined);
  const dateFormat = new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });

  const newViewState = () => ({
    status: "idle",
    data: null,
    error: null,
  });

  const state = {
    activeView: "models",
    sessionToken: readStoredSession(),
    cachedInferenceKeys: readStoredInferenceKeys(),
    authNotice: "",
    notice: null,
    userStatus: "idle",
    user: null,
    userError: null,
    workspaces: [],
    selectedWorkspaceName: "",
    currentWorkspaceName: "",
    selectedModelName: "",
    modelDetail: {
      ...newViewState(),
      requestId: 0,
    },
    views: {
      models: newViewState(),
      status: newViewState(),
      live: newViewState(),
    },
    workspaceData: {
      status: "idle",
      keysStatus: "idle",
      keys: null,
      keysError: null,
      usageStatus: "idle",
      usage: null,
      usageError: null,
      requestId: 0,
    },
    workspaceFormError: null,
    keyFormError: null,
    passwordFormError: null,
    busyAction: "",
    profileOpen: false,
    modal: null,
    noticeTimer: 0,
    liveTimer: 0,
  };

  class ApiError extends Error {
    constructor(message, status = 0, network = false) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.network = network;
    }
  }

  function removeLegacyApiKey() {
    try {
      if (window.localStorage.getItem(LEGACY_STORAGE_KEY) === null) {
        return false;
      }
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
      return true;
    } catch (_error) {
      return false;
    }
  }

  function readStoredSession() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) || "";
    } catch (_error) {
      return "";
    }
  }

  function storeSession(sessionToken) {
    try {
      if (sessionToken) {
        window.localStorage.setItem(STORAGE_KEY, sessionToken);
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch (_error) {
    }
  }

  function readStoredInferenceKeys() {
    try {
      const rawKeys = window.localStorage.getItem(INFERENCE_KEYS_STORAGE_KEY);
      if (!rawKeys) {
        return {};
      }
      const parsedKeys = JSON.parse(rawKeys);
      if (!isObject(parsedKeys) || Array.isArray(parsedKeys)) {
        return {};
      }
      const cachedKeys = {};
      Object.entries(parsedKeys).forEach(([keyId, plaintext]) => {
        if (keyId && typeof plaintext === "string" && plaintext.startsWith("outo_sk_")) {
          cachedKeys[keyId] = plaintext;
        }
      });
      return cachedKeys;
    } catch (_error) {
      return {};
    }
  }

  function storeInferenceKeys(cachedKeys) {
    try {
      window.localStorage.setItem(INFERENCE_KEYS_STORAGE_KEY, JSON.stringify(cachedKeys));
    } catch (_error) {
    }
  }

  function getCachedInferenceKey(keyId) {
    const plaintext = state.cachedInferenceKeys[String(keyId)] || "";
    return typeof plaintext === "string" && plaintext.startsWith("outo_sk_") ? plaintext : "";
  }

  function cacheInferenceKey(keyId, plaintext) {
    if (keyId === null || keyId === undefined || typeof plaintext !== "string" || !plaintext.startsWith("outo_sk_")) {
      return false;
    }
    const normalizedId = String(keyId);
    if (!normalizedId) {
      return false;
    }
    state.cachedInferenceKeys = {
      ...state.cachedInferenceKeys,
      [normalizedId]: plaintext,
    };
    storeInferenceKeys(state.cachedInferenceKeys);
    return true;
  }

  function removeCachedInferenceKey(keyId) {
    const normalizedId = String(keyId);
    if (!Object.prototype.hasOwnProperty.call(state.cachedInferenceKeys, normalizedId)) {
      return;
    }
    const cachedKeys = { ...state.cachedInferenceKeys };
    delete cachedKeys[normalizedId];
    state.cachedInferenceKeys = cachedKeys;
    storeInferenceKeys(cachedKeys);
  }

  function listedInferenceKeyIds(keys) {
    return new Set(
      (Array.isArray(keys) ? keys : [])
        .filter((key) => isObject(key) && key.id !== null && key.id !== undefined)
        .map((key) => String(key.id)),
    );
  }

  function cacheCreatedInferenceKeyFromList(plaintext, keys, knownKeyIds) {
    const candidates = (Array.isArray(keys) ? keys : []).filter(
      (key) => isObject(key)
        && key.id !== null
        && key.id !== undefined
        && !key.revoked
        && !knownKeyIds.has(String(key.id)),
    );
    return candidates.length === 1 ? cacheInferenceKey(candidates[0].id, plaintext) : false;
  }

  async function cacheCreatedInferenceKey(workspaceName, plaintext, knownKeyIds, listedKeys = null) {
    if (!workspaceName) {
      return;
    }
    if (cacheCreatedInferenceKeyFromList(plaintext, listedKeys, knownKeyIds)) {
      return;
    }
    try {
      const keys = await apiRequest(
        `/v1/workspaces/${encodeURIComponent(workspaceName)}/keys`,
        {},
        undefined,
        false,
      );
      cacheCreatedInferenceKeyFromList(plaintext, keys, knownKeyIds);
    } catch (_error) {
    }
  }

  function node(tagName, className = "", text = "") {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text) {
      element.textContent = text;
    }
    return element;
  }

  function setAttributes(element, attributes) {
    Object.entries(attributes).forEach(([name, value]) => {
      if (value !== null && value !== undefined) {
        element.setAttribute(name, String(value));
      }
    });
    return element;
  }

  function clear(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function safeString(value, fallback = "—") {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
    return fallback;
  }

  function formatNumber(value) {
    const number = typeof value === "number" ? value : Number(value);
    return Number.isFinite(number) ? numberFormat.format(number) : "0";
  }

  function formatDate(value) {
    if (typeof value !== "string" || !value) {
      return "—";
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : dateFormat.format(date);
  }

  function isObject(value) {
    return typeof value === "object" && value !== null;
  }

  function extractErrorMessage(payload, fallback) {
    if (!isObject(payload)) {
      return fallback;
    }
    const detail = isObject(payload.detail) ? payload.detail : null;
    const nestedError = detail && isObject(detail.error) ? detail.error : null;
    const error = isObject(payload.error) ? payload.error : null;
    const candidates = [
      error && error.message,
      nestedError && nestedError.message,
      detail && detail.message,
      payload.message,
    ];
    const message = candidates.find((candidate) => typeof candidate === "string" && candidate.trim());
    return message || fallback;
  }

  async function readJson(response) {
    if (response.status === 204) {
      return null;
    }
    try {
      return await response.json();
    } catch (_error) {
      return null;
    }
  }

  async function apiRequest(path, options = {}, sessionOverride, manageUnauthorized = true) {
    const sessionToken = typeof sessionOverride === "string" ? sessionOverride : state.sessionToken;
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    if (sessionToken) {
      headers.Authorization = `Bearer ${sessionToken}`;
    }
    let response;
    try {
      response = await fetch(new URL(path, window.location.origin).toString(), {
        ...options,
        headers,
      });
    } catch (_error) {
      throw new ApiError("server unreachable", 0, true);
    }

    const payload = await readJson(response);
    const errorMessage = extractErrorMessage(payload, `Request failed with status ${response.status}.`);
    if (response.status === 401 && manageUnauthorized) {
      handleUnauthorized();
      throw new ApiError(errorMessage, 401);
    }
    if (!response.ok) {
      throw new ApiError(errorMessage, response.status);
    }
    return payload;
  }

  function handleUnauthorized() {
    state.sessionToken = "";
    storeSession("");
    state.authNotice = "Your session expired or is no longer valid. Log in again to continue.";
    state.userStatus = "idle";
    state.user = null;
    state.userError = null;
    state.workspaces = [];
    state.selectedWorkspaceName = "";
    state.currentWorkspaceName = "";
    resetModelDetail();
    state.workspaceData = {
      status: "idle",
      keysStatus: "idle",
      keys: null,
      keysError: null,
      usageStatus: "idle",
      usage: null,
      usageError: null,
      requestId: state.workspaceData.requestId + 1,
    };
    state.workspaceFormError = null;
    state.keyFormError = null;
    state.passwordFormError = null;
    state.busyAction = "";
    state.modal = null;
    state.profileOpen = true;
    render();
  }

  function showNotice(message, tone = "info") {
    state.notice = { message, tone };
    window.clearTimeout(state.noticeTimer);
    state.noticeTimer = window.setTimeout(() => {
      state.notice = null;
      render();
    }, 4500);
    render();
  }

  function applyAccountPayload(payload) {
    const rawWorkspaces = isObject(payload) && Array.isArray(payload.workspaces) ? payload.workspaces : [];
    state.workspaces = rawWorkspaces
      .filter((workspace) => isObject(workspace) && safeString(workspace.name, "") !== "")
      .map((workspace) => ({
        id: workspace.id,
        name: safeString(workspace.name, ""),
        created_at: safeString(workspace.created_at, ""),
      }));
    state.user = {
      user_id: isObject(payload) ? payload.user_id : null,
      username: safeString(isObject(payload) ? payload.username : "", "User"),
    };
    const apiWorkspace = isObject(payload)
      ? payload.workspace || payload.current_workspace || payload.workspace_name
      : "";
    if (typeof apiWorkspace === "string" && apiWorkspace) {
      state.currentWorkspaceName = apiWorkspace;
    }
    const selectedStillExists = state.workspaces.some(
      (workspace) => workspace.name === state.selectedWorkspaceName,
    );
    if (!selectedStillExists) {
      const contextWorkspace = state.workspaces.find(
        (workspace) => workspace.name === state.currentWorkspaceName,
      );
      state.selectedWorkspaceName = contextWorkspace?.name || state.workspaces[0]?.name || "";
    }
  }

  async function loadAccount() {
    if (!state.sessionToken || state.userStatus === "loading") {
      return null;
    }
    state.userStatus = "loading";
    state.userError = null;
    render();
    try {
      const payload = await apiRequest("/v1/account/me");
      applyAccountPayload(payload);
      state.userStatus = "ready";
      render();
      return payload;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return null;
      }
      state.userStatus = "error";
      state.userError = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
      render();
      return null;
    }
  }

  function authGate(title, description) {
    const wrapper = node("div", "auth-gate");
    const mark = node("div", "auth-gate__mark", "o");
    const content = node("div", "auth-gate__content");
    content.append(
      node("p", "eyebrow", "AUTHENTICATION REQUIRED"),
      node("h2", "auth-gate__title", title),
      node("p", "auth-gate__description", description),
    );
    const actions = node("div", "button-row");
    actions.append(
      actionButton("Log in", "open-login", "button button--primary"),
      actionButton("Sign up", "open-signup", "button button--ghost"),
    );
    content.append(actions);
    wrapper.append(mark, content);
    return wrapper;
  }

  function actionButton(label, action, className = "button button--ghost") {
    const button = node("button", className, label);
    setAttributes(button, { type: "button", "data-action": action });
    return button;
  }

  function pageHeader(eyebrow, title, description, action = null) {
    const header = node("div", "page-header");
    const copy = node("div", "page-header__copy");
    copy.append(node("p", "eyebrow", eyebrow), node("h1", "page-title", title), node("p", "page-description", description));
    header.append(copy);
    if (action) {
      header.append(action);
    }
    return header;
  }

  function loadingState(label) {
    const card = node("div", "state-card");
    const spinner = node("span", "spinner");
    setAttributes(spinner, { role: "status", "aria-label": label });
    card.append(spinner, node("span", "state-card__label", label));
    return card;
  }

  function emptyState(title, description, action = null) {
    const card = node("div", "state-card state-card--empty");
    card.append(node("div", "empty-mark", "—"), node("h3", "state-card__title", title), node("p", "state-card__description", description));
    if (action) {
      card.append(action);
    }
    return card;
  }

  function errorState(error, retryAction, title = "Could not load this view") {
    const card = node("div", "state-card state-card--error");
    const heading = node("h3", "state-card__title", title);
    const message = error?.network
      ? "Server unreachable. Check that outo-llms is running on this LAN and try again."
      : safeString(error?.message, "The server returned an unexpected error.");
    card.append(node("div", "error-mark", "!"), heading, node("p", "state-card__description", message));
    if (retryAction) {
      card.append(retryAction);
    }
    return card;
  }

  function retryButton(action, label = "Retry") {
    return actionButton(label, action, "button button--ghost button--small");
  }

  function renderModels() {
    if (state.selectedModelName) {
      return renderModelDetail();
    }
    const view = state.views.models;
    const wrapper = node("div", "view view--models");
    wrapper.append(
      pageHeader(
        "CATALOG",
        "Models",
        "Registered models available through the OpenAI-compatible endpoint.",
        retryButton("retry-view", "Refresh"),
      ),
    );
    if (view.status === "loading" || view.status === "idle") {
      wrapper.append(loadingState("Loading models"));
      return wrapper;
    }
    if (view.status === "error") {
      wrapper.append(errorState(view.error, retryButton("retry-view")));
      return wrapper;
    }
    const models = Array.isArray(view.data) ? view.data : [];
    if (!models.length) {
      wrapper.append(
        emptyState(
          "No models registered",
          "Add a model from the command line to make it available here.",
        ),
      );
    } else {
      const card = node("div", "card table-card");
      const tableWrap = node("div", "table-wrap");
      const table = node("table", "data-table data-table--models");
      table.append(node("caption", "sr-only", "Registered models"));
      const head = node("thead");
      const headRow = node("tr");
      headRow.append(node("th", "", "Model name"));
      head.append(headRow);
      const body = node("tbody");
      models.forEach((model) => {
        const modelName = safeString(isObject(model) ? model.id : "", "");
        const row = node("tr");
        const cell = node("td", "model-row-cell");
        if (modelName) {
          const select = actionButton(modelName, "select-model", "model-row-button");
          setAttributes(select, {
            "data-model-name": modelName,
            "aria-label": `View details for ${modelName}`,
          });
          cell.append(select);
        } else {
          cell.append(node("span", "model-name", "—"));
        }
        row.append(cell);
        body.append(row);
      });
      table.append(head, body);
      tableWrap.append(table);
      card.append(tableWrap);
      wrapper.append(card);
    }
    const hint = node("p", "hint-line");
    hint.append(node("span", "hint-line__label", "CLI only"), node("span", "hint-line__text", "Manage models with the CLI: "), node("code", "inline-code", "outo-llms models add|list|remove"));
    wrapper.append(hint);
    return wrapper;
  }

  function renderModelDetail() {
    const view = state.modelDetail;
    const wrapper = node("div", "view view--models model-detail-view");
    wrapper.append(
      pageHeader(
        "CATALOG",
        "Model detail",
        "Inspect this registered model and copy a request example.",
        actionButton("Back to models", "back-models", "button button--ghost"),
      ),
    );
    if (view.status === "loading" || view.status === "idle") {
      wrapper.append(loadingState("Loading model details"));
      return wrapper;
    }
    if (view.status === "error") {
      const actions = node("div", "button-row");
      actions.append(
        actionButton("Back to models", "back-models", "button button--ghost button--small"),
        retryButton("retry-model-detail"),
      );
      const title = view.error instanceof ApiError && view.error.status === 404
        ? "Model not found"
        : "Could not load model details";
      wrapper.append(errorState(view.error, actions, title));
      return wrapper;
    }
    const model = isObject(view.data) ? view.data : null;
    const modelName = safeString(model?.name, "");
    if (!model || !modelName) {
      wrapper.append(
        emptyState(
          "Model details unavailable",
          "The server returned no details for this model.",
          actionButton("Back to models", "back-models", "button button--ghost button--small"),
        ),
      );
      return wrapper;
    }

    const content = node("div", "model-detail-content");
    const infoCard = node("section", "card model-detail-card");
    const heading = node("div", "card-heading");
    const headingCopy = node("div");
    headingCopy.append(node("p", "eyebrow", "MODEL"), node("h2", "card-title", modelName));
    const kind = safeString(model.kind, "unknown").toLowerCase();
    heading.append(headingCopy, node("span", "status-badge status-badge--accent", kind));
    const details = node("dl", "status-list model-detail-list");
    details.append(
      node("dt", "status-list__term", "Source"),
      node("dd", "status-list__value", safeString(model.source)),
      node("dt", "status-list__term", "Registered"),
      node("dd", "status-list__value", formatDate(model.created_at)),
    );
    infoCard.append(heading, details);
    content.append(infoCard, renderModelExamples(modelName));
    wrapper.append(content);
    return wrapper;
  }

  function renderModelExamples(modelName) {
    const section = node("section", "model-examples");
    const heading = node("div", "model-examples__heading");
    heading.append(
      node("h2", "card-title", "Example requests"),
      node("p", "muted-copy", "Copy a complete request and replace the placeholder API key."),
    );
    const examples = node("div", "request-examples");
    modelRequestExamples(modelName).forEach((example) => {
      examples.append(renderRequestExample(example.title, example.snippet));
    });
    section.append(
      heading,
      examples,
      node("p", "muted-copy", "Replace outo_sk_... with an inference API key from your workspace."),
    );
    return section;
  }

  function modelRequestExamples(modelName) {
    const origin = window.location.origin;
    const modelLiteral = JSON.stringify(modelName);
    const baseUrlLiteral = JSON.stringify(`${origin}/v1`);
    const requestBody = JSON.stringify({
      model: modelName,
      messages: [{ role: "user", content: "Hello!" }],
    });
    return [
      {
        title: "curl",
        snippet: `curl -s ${origin}/v1/chat/completions \\\n  -H "Authorization: Bearer outo_sk_..." \\\n  -H "Content-Type: application/json" \\\n  -d '${requestBody}'`,
      },
      {
        title: "Python",
        snippet: `from openai import OpenAI\n\nclient = OpenAI(base_url=${baseUrlLiteral}, api_key="outo_sk_...")\nresp = client.chat.completions.create(\n    model=${modelLiteral},\n    messages=[{"role": "user", "content": "Hello!"}],\n)\nprint(resp.choices[0].message.content)`,
      },
      {
        title: "Node.js",
        snippet: `import OpenAI from "openai";\n\nconst client = new OpenAI({ baseURL: ${baseUrlLiteral}, apiKey: "outo_sk_..." });\nconst resp = await client.chat.completions.create({\n  model: ${modelLiteral},\n  messages: [{ role: "user", content: "Hello!" }],\n});\nconsole.log(resp.choices[0].message.content);`,
      },
    ];
  }

  function renderRequestExample(title, snippet) {
    const card = node("article", "card request-example");
    const heading = node("div", "request-example__heading");
    const copy = actionButton("Copy", "copy-snippet", "button button--ghost button--small");
    setAttributes(copy, { "aria-label": `Copy ${title} example request` });
    heading.append(node("h3", "card-title", title), copy);
    const pre = node("pre", "request-example__pre");
    pre.append(node("code", "request-example__code", snippet));
    card.append(heading, pre);
    return card;
  }

  function resetModelDetail() {
    state.selectedModelName = "";
    state.modelDetail = {
      ...newViewState(),
      requestId: state.modelDetail.requestId + 1,
    };
  }

  function openModelDetail(modelName) {
    if (!modelName) {
      return;
    }
    state.selectedModelName = modelName;
    state.modelDetail = {
      ...newViewState(),
      requestId: state.modelDetail.requestId + 1,
    };
    render();
    loadModelDetail();
  }

  async function loadModelDetail() {
    const modelName = state.selectedModelName;
    if (!state.sessionToken || !modelName || state.modelDetail.status === "loading") {
      return;
    }
    const requestId = state.modelDetail.requestId + 1;
    state.modelDetail = {
      status: "loading",
      data: null,
      error: null,
      requestId,
    };
    render();
    try {
      const payload = await apiRequest(`/v1/models/${encodeURIComponent(modelName)}`);
      if (requestId !== state.modelDetail.requestId || state.selectedModelName !== modelName) {
        return;
      }
      state.modelDetail.data = payload;
      state.modelDetail.status = "ready";
      render();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      if (requestId !== state.modelDetail.requestId || state.selectedModelName !== modelName) {
        return;
      }
      state.modelDetail.error = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
      state.modelDetail.status = "error";
      render();
    }
  }

  function renderWorkspaces() {
    const wrapper = node("div", "view view--workspaces");
    wrapper.append(
      pageHeader(
        "ORGANIZATION",
        "Workspaces",
        "Keep inference keys, requests, and usage scoped to the work you are shipping.",
      ),
    );
    const layout = node("div", "workspace-layout");
    layout.append(renderWorkspaceSidebar(), renderWorkspaceDetail());
    wrapper.append(layout);
    return wrapper;
  }

  function renderWorkspaceSidebar() {
    const sidebar = node("aside", "card workspace-sidebar");
    const heading = node("div", "section-heading");
    heading.append(node("div", "section-heading__copy", "Your workspaces"), node("span", "count-badge", formatNumber(state.workspaces.length)));
    sidebar.append(heading);
    const list = node("div", "workspace-list");
    if (!state.workspaces.length) {
      list.append(node("p", "muted-copy", "No workspaces yet."));
    } else {
      state.workspaces.forEach((workspace) => {
        const item = node("button", "workspace-item");
        if (workspace.name === state.selectedWorkspaceName) {
          item.classList.add("workspace-item--active");
        }
        setAttributes(item, {
          type: "button",
          "data-action": "select-workspace",
          "data-workspace-name": workspace.name,
          "aria-current": workspace.name === state.selectedWorkspaceName ? "true" : "false",
        });
        const name = node("span", "workspace-item__name", workspace.name);
        const metaText = workspace.name === state.currentWorkspaceName ? "Usage context" : formatDate(workspace.created_at);
        item.append(name, node("span", "workspace-item__meta", metaText));
        list.append(item);
      });
    }
    sidebar.append(list, node("div", "section-divider"), createWorkspaceForm());
    return sidebar;
  }

  function createWorkspaceForm() {
    const form = node("form", "stack-form");
    setAttributes(form, { "data-form": "create-workspace", novalidate: "" });
    const heading = node("div", "form-heading", "Create workspace");
    const field = formField("workspace-name", "Name", "e.g. experiments", "text", true, 64);
    const submit = node("button", "button button--primary button--full", state.busyAction === "create-workspace" ? "Creating…" : "Create workspace");
    setAttributes(submit, { type: "submit", disabled: state.busyAction === "create-workspace" ? "" : null });
    form.append(heading, field, submit);
    if (state.workspaceFormError) {
      form.append(formError(state.workspaceFormError));
    }
    return form;
  }

  function renderWorkspaceDetail() {
    const detail = node("section", "workspace-detail");
    const selected = state.workspaces.find((workspace) => workspace.name === state.selectedWorkspaceName);
    if (!selected) {
      detail.append(emptyState("Select a workspace", "Choose a workspace from the list to manage its inference keys and usage."));
      return detail;
    }
    const header = node("div", "workspace-detail__header");
    const copy = node("div");
    copy.append(node("p", "eyebrow", "WORKSPACE"), node("h2", "workspace-detail__title", selected.name), node("p", "muted-copy", `Created ${formatDate(selected.created_at)}`));
    header.append(copy);
    detail.append(header, renderKeysCard(selected.name), renderUsageCard());
    return detail;
  }

  function renderKeysCard(workspaceName) {
    const card = node("div", "card keys-card");
    const heading = node("div", "card-heading");
    const headingCopy = node("div");
    headingCopy.append(
      node("p", "eyebrow", "ACCESS"),
      node("h3", "card-title", "Inference API keys"),
      node("p", "card-description", "Use these keys as Bearer tokens for /v1/chat/completions and other inference endpoints."),
      node("p", "card-description", "Keys you created in this browser can be copied again; keys created elsewhere were shown once."),
    );
    heading.append(headingCopy);
    card.append(heading);

    const data = state.workspaceData;
    if (data.keysStatus === "loading" || data.keysStatus === "idle") {
      card.append(loadingState("Loading inference API keys"));
    } else if (data.keysStatus === "error") {
      card.append(errorState(data.keysError, retryButton("retry-workspace", "Retry keys"), "Could not load inference API keys"));
    } else {
      const keys = Array.isArray(data.keys) ? data.keys : [];
      if (!keys.length) {
        card.append(emptyState("No inference API keys in this workspace", "Create an inference key for a local app or integration."));
      } else {
        card.append(renderKeysTable(keys));
      }
    }
    card.append(node("div", "section-divider"), createKeyForm(workspaceName));
    return card;
  }

  function renderKeysTable(keys) {
    const wrap = node("div", "table-wrap");
    const table = node("table", "data-table data-table--keys");
    table.append(node("caption", "sr-only", "Workspace inference API keys"));
    const head = node("thead");
    const row = node("tr");
    ["Label", "Created", "Status", ""].forEach((label) => row.append(node("th", "", label)));
    head.append(row);
    const body = node("tbody");
    keys.forEach((key) => {
      const item = node("tr");
      const label = safeString(isObject(key) ? key.label : "", "Unlabeled key");
      const id = isObject(key) ? key.id : "";
      const revoked = Boolean(isObject(key) && key.revoked);
      const cachedKey = getCachedInferenceKey(id);
      const status = node("span", revoked ? "status-badge status-badge--muted" : "status-badge status-badge--success", revoked ? "Revoked" : "Active");
      const keyCell = node("td");
      keyCell.append(node("span", "key-label", label));
      if (cachedKey) {
        const copy = actionButton("Copy key", "copy-cached-key", "button button--ghost button--small key-copy-control");
        setAttributes(copy, {
          "data-key-id": id,
          "aria-label": `Copy ${label} inference API key`,
        });
        keyCell.append(copy);
      } else {
        keyCell.append(node("span", "muted-copy key-copy-note", "Shown once at creation. Lost it? Revoke and recreate."));
      }
      const actionCell = node("td", "table-actions");
      if (!revoked) {
        const revoke = actionButton("Revoke", "revoke-key", "button button--danger-ghost button--small");
        setAttributes(revoke, { "data-key-id": id, "data-workspace-name": state.selectedWorkspaceName });
        actionCell.append(revoke);
      } else {
        actionCell.append(node("span", "muted-copy", "—"));
      }
      item.append(keyCell, node("td", "", formatDate(isObject(key) ? key.created_at : "")), node("td", "", status), actionCell);
      body.append(item);
    });
    table.append(head, body);
    wrap.append(table);
    return wrap;
  }

  function createKeyForm(workspaceName) {
    const form = node("form", "inline-form");
    setAttributes(form, { "data-form": "create-key", novalidate: "" });
    const field = formField("key-label", "New inference key label", "Optional", "text", false, 120);
    const submit = node("button", "button button--ghost", state.busyAction === "create-key" ? "Issuing…" : "Create inference key");
    setAttributes(submit, { type: "submit", disabled: state.busyAction === "create-key" ? "" : null, "data-workspace-name": workspaceName });
    form.append(field, submit);
    if (state.keyFormError) {
      form.append(formError(state.keyFormError));
    }
    return form;
  }

  function formField(
    id,
    labelText,
    placeholder,
    type = "text",
    required = false,
    maxLength = null,
    minLength = null,
    autocomplete = "off",
  ) {
    const field = node("label", "form-field");
    field.append(node("span", "form-field__label", labelText));
    const input = node("input", "text-input");
    setAttributes(input, {
      id,
      name: id,
      type,
      placeholder,
      required: required ? "" : null,
      maxlength: maxLength,
      minlength: minLength,
      autocomplete,
    });
    field.append(input);
    return field;
  }

  function formError(error) {
    const message = error?.network
      ? "Server unreachable. Check the connection and try again."
      : safeString(error?.message, "Please check the form and try again.");
    return node("p", "form-error", message);
  }

  function renderUsageCard() {
    const card = node("div", "card usage-card");
    const heading = node("div", "card-heading");
    const copy = node("div");
    copy.append(node("p", "eyebrow", "METERING"), node("h3", "card-title", "Usage summary"), node("p", "card-description", "Totals returned for the current workspace context."));
    heading.append(copy);
    card.append(heading);
    const data = state.workspaceData;
    if (data.usageStatus === "loading" || data.usageStatus === "idle") {
      card.append(loadingState("Loading usage"));
      return card;
    }
    if (data.usageStatus === "error") {
      card.append(errorState(data.usageError, retryButton("retry-workspace", "Retry usage"), "Could not load usage"));
      return card;
    }
    const usage = isObject(data.usage) ? data.usage : {};
    const summary = node("div", "metric-grid");
    summary.append(metric("Requests", formatNumber(usage.total_requests)), metric("Total tokens", formatNumber(usage.total_tokens)));
    card.append(node("p", "usage-context", `Usage workspace: ${safeString(usage.workspace, "Unavailable")}`), summary);
    const models = Array.isArray(usage.by_model) ? usage.by_model : [];
    if (models.length) {
      const tableWrap = node("div", "table-wrap table-wrap--usage");
      const table = node("table", "data-table");
      table.append(node("caption", "sr-only", "Usage by model"));
      const head = node("thead");
      const row = node("tr");
      ["Model", "Requests", "Prompt", "Completion", "Tokens"].forEach((label) => row.append(node("th", "", label)));
      head.append(row);
      const body = node("tbody");
      models.forEach((model) => {
        const modelRow = node("tr");
        modelRow.append(
          node("td", "model-name", safeString(model?.model)),
          node("td", "numeric-cell", formatNumber(model?.requests)),
          node("td", "numeric-cell", formatNumber(model?.prompt_tokens)),
          node("td", "numeric-cell", formatNumber(model?.completion_tokens)),
          node("td", "numeric-cell", formatNumber(model?.total_tokens)),
        );
        body.append(modelRow);
      });
      table.append(head, body);
      tableWrap.append(table);
      card.append(tableWrap);
    } else {
      card.append(node("p", "muted-copy usage-empty", "No model usage recorded yet."));
    }
    return card;
  }

  function metric(label, value) {
    const item = node("div", "metric");
    item.append(node("span", "metric__label", label), node("strong", "metric__value", value));
    return item;
  }

  async function loadWorkspaceData() {
    const workspaceName = state.selectedWorkspaceName;
    if (!state.sessionToken || !workspaceName || state.workspaceData.status === "loading") {
      return;
    }
    const requestId = state.workspaceData.requestId + 1;
    state.workspaceData = {
      status: "loading",
      keysStatus: "loading",
      keys: null,
      keysError: null,
      usageStatus: "loading",
      usage: null,
      usageError: null,
      requestId,
    };
    state.workspaceFormError = null;
    state.keyFormError = null;
    render();
    const encodedName = encodeURIComponent(workspaceName);
    const results = await Promise.allSettled([
      apiRequest(`/v1/workspaces/${encodedName}/keys`),
      apiRequest("/v1/usage"),
    ]);
    if (requestId !== state.workspaceData.requestId || state.selectedWorkspaceName !== workspaceName) {
      return;
    }
    const keysResult = results[0];
    const usageResult = results[1];
    if (keysResult.status === "fulfilled") {
      state.workspaceData.keysStatus = "ready";
      state.workspaceData.keys = Array.isArray(keysResult.value) ? keysResult.value : [];
    } else {
      state.workspaceData.keysStatus = "error";
      state.workspaceData.keysError = keysResult.reason instanceof ApiError ? keysResult.reason : new ApiError("server unreachable", 0, true);
    }
    if (usageResult.status === "fulfilled") {
      state.workspaceData.usageStatus = "ready";
      state.workspaceData.usage = usageResult.value;
      if (isObject(usageResult.value) && typeof usageResult.value.workspace === "string") {
        state.currentWorkspaceName = usageResult.value.workspace;
      }
    } else {
      state.workspaceData.usageStatus = "error";
      state.workspaceData.usageError = usageResult.reason instanceof ApiError ? usageResult.reason : new ApiError("server unreachable", 0, true);
    }
    if (state.workspaceData.keysStatus === "ready" && state.workspaceData.usageStatus === "ready") {
      state.workspaceData.status = "ready";
    } else {
      state.workspaceData.status = "error";
    }
    if (results.some((result) => result.status === "rejected" && result.reason instanceof ApiError && result.reason.status === 401)) {
      return;
    }
    render();
  }

  function renderStatus() {
    const view = state.views.status;
    const wrapper = node("div", "view view--status");
    wrapper.append(
      pageHeader(
        "OPERATIONS",
        "Server status",
        "A live snapshot of the API server, active engine, and managed resources.",
        retryButton("retry-view", "Refresh"),
      ),
    );
    if (view.status === "loading" || view.status === "idle") {
      wrapper.append(loadingState("Loading server status"));
      return wrapper;
    }
    if (view.status === "error") {
      wrapper.append(errorState(view.error, retryButton("retry-view")));
      return wrapper;
    }
    const payload = isObject(view.data) ? view.data : {};
    const server = isObject(payload.server) ? payload.server : {};
    const engine = isObject(payload.engine) ? payload.engine : {};
    const counts = isObject(payload.counts) ? payload.counts : {};
    const version = safeString(payload.version, "Unknown");
    const intro = node("div", "status-intro");
    intro.append(node("span", "status-intro__label", "API version"), node("strong", "status-intro__value", version));
    wrapper.append(intro);

    const grid = node("div", "status-grid");
    grid.append(
      statusCard("Server", "NETWORK", [
        ["Host", server.host],
        ["Port", server.port],
        ["HTTPS", renderBooleanValue(server.https, "Enabled", "Disabled")],
        ["Domain", server.domain],
      ]),
      engineStatusCard(engine),
      statusCard("Resources", "INVENTORY", [
        ["Users", formatNumber(counts.users)],
        ["Workspaces", formatNumber(counts.workspaces)],
        ["Models", formatNumber(counts.models)],
      ]),
    );
    wrapper.append(grid);
    return wrapper;
  }

  function statusCard(title, eyebrow, fields) {
    const card = node("div", "card status-card");
    card.append(node("p", "eyebrow", eyebrow), node("h2", "card-title", title));
    const list = node("dl", "status-list");
    fields.forEach(([label, value]) => {
      const term = node("dt", "status-list__term", label);
      const definition = node("dd", "status-list__value");
      if (value instanceof HTMLElement) {
        definition.append(value);
      } else {
        definition.textContent = safeString(value);
      }
      list.append(term, definition);
    });
    card.append(list);
    return card;
  }

  function engineStatusCard(engine) {
    const card = statusCard("Engine", "RUNTIME", [
      ["Engine", engine.engine],
      ["Installed", renderBooleanValue(engine.installed, "Ready", "Not installed")],
      ["PID", engine.pid],
      ["Model", engine.model],
      ["Port", engine.port],
      ["Base URL", engine.base_url],
    ]);
    const running = node("div", "engine-state");
    running.append(node("span", "engine-state__label", "Process"), statusBadge(Boolean(engine.running), "Running", "Stopped"));
    card.insertBefore(running, card.querySelector(".status-list"));
    return card;
  }

  function renderBooleanValue(value, positive, negative) {
    return statusBadge(Boolean(value), positive, negative);
  }

  function statusBadge(value, positive, negative) {
    return node("span", value ? "status-badge status-badge--success" : "status-badge status-badge--muted", value ? positive : negative);
  }

  async function loadView(viewName) {
    if (!state.sessionToken || !state.views[viewName] || state.views[viewName].status === "loading") {
      return;
    }
    const view = state.views[viewName];
    view.status = "loading";
    view.error = null;
    render();
    try {
      let payload;
      if (viewName === "models") {
        payload = await apiRequest("/v1/models");
        view.data = isObject(payload) ? (Array.isArray(payload.data) ? payload.data : []) : [];
      } else if (viewName === "live") {
        payload = await apiRequest("/v1/live");
        view.data = isObject(payload) && !Array.isArray(payload) ? payload : null;
      } else {
        payload = await apiRequest("/v1/status");
        view.data = payload;
      }
      view.status = "ready";
      render();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      view.status = "error";
      view.error = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
      render();
    }
  }

  function renderPasswordCard() {
    const card = node("div", "card context-card password-card");
    card.append(
      node("p", "eyebrow", "SECURITY"),
      node("h2", "card-title", "Change password"),
      node("p", "card-description", "Use at least 8 characters for your new password."),
    );
    const form = node("form", "stack-form modal-form");
    setAttributes(form, { "data-form": "change-password", novalidate: "" });
    form.append(
      formField("current_password", "Current password", "Enter current password", "password", true, 256, 8, "current-password"),
      formField("new_password", "New password", "At least 8 characters", "password", true, 256, 8, "new-password"),
      formField("confirm_password", "Confirm new password", "Enter the new password again", "password", true, 256, 8, "new-password"),
    );
    const busy = state.busyAction === "change-password";
    const submit = node("button", "button button--primary button--full", busy ? "Changing…" : "Change password");
    setAttributes(submit, { type: "submit", disabled: busy ? "" : null });
    form.append(submit);
    if (state.passwordFormError) {
      form.append(formError(state.passwordFormError));
    }
    card.append(form);
    return card;
  }

  function renderProfile() {
    const wrapper = node("div", "view view--profile");
    wrapper.append(pageHeader("ACCOUNT", "Profile", "Manage your account identity, workspaces, and password."));
    if (state.userStatus === "loading" || state.userStatus === "idle") {
      wrapper.append(loadingState("Loading profile"));
      return wrapper;
    }
    if (state.userStatus === "error") {
      wrapper.append(errorState(state.userError, actionButton("Retry profile", "retry-profile")));
      return wrapper;
    }
    const user = state.user || {};
    const content = node("div", "profile-grid");
    const identity = node("div", "card identity-card");
    identity.append(node("p", "eyebrow", "IDENTITY"), node("h2", "card-title", safeString(user.username, "User")));
    const identityList = node("dl", "status-list");
    identityList.append(node("dt", "status-list__term", "Username"), node("dd", "status-list__value", safeString(user.username, "User")), node("dt", "status-list__term", "User ID"), node("dd", "status-list__value", safeString(user.user_id)));
    identity.append(identityList);

    const workspaceCard = node("div", "card profile-workspaces-card");
    const workspaceHeading = node("div", "card-heading");
    workspaceHeading.append(node("div", "card-heading__copy", "Your workspaces"), node("span", "count-badge", formatNumber(state.workspaces.length)));
    workspaceCard.append(node("p", "eyebrow", "ACCESS"), workspaceHeading);
    const workspaceList = node("ul", "profile-workspace-list");
    if (!state.workspaces.length) {
      workspaceList.append(node("li", "muted-copy", "No workspaces available."));
    } else {
      state.workspaces.forEach((workspace) => {
        const item = node("li", "profile-workspace-item");
        const copy = node("div");
        copy.append(node("strong", "profile-workspace-item__name", workspace.name), node("span", "profile-workspace-item__meta", `Created ${formatDate(workspace.created_at)}`));
        item.append(copy);
        workspaceList.append(item);
      });
    }
    workspaceCard.append(workspaceList);

    content.append(identity, workspaceCard, renderPasswordCard());
    wrapper.append(content);
    return wrapper;
  }

  function render() {
    elements.nav.querySelectorAll(".nav-tab").forEach((tab) => {
      tab.setAttribute(
        "aria-selected",
        tab.dataset.view === state.activeView ? "true" : "false"
      );
    });
    renderNotice();
    renderView();
    renderProfileMenu();
    renderModal();
    updateLivePolling();
  }

  function renderView() {
    clear(elements.viewRoot);
    elements.viewRoot.setAttribute("role", "tabpanel");
    elements.viewRoot.setAttribute("aria-label", state.activeView === "status" ? "Server status" : `${state.activeView} view`);
    if (!state.sessionToken) {
      const titles = {
        models: "See your model catalog",
        workspaces: "Your work, in one place",
        status: "Connect to your server",
        live: "Watch your server in real time",
        profile: "Welcome to outo-llms",
      };
      const title = titles[state.activeView] || titles.models;
      elements.viewRoot.append(authGate(title, "Log in with your username and password, or sign up for an account."));
      return;
    }
    if (state.userStatus === "error") {
      elements.viewRoot.append(errorState(state.userError, actionButton("Retry connection", "retry-account"), "Could not reach the account endpoint"));
      return;
    }
    if (state.activeView === "models") {
      elements.viewRoot.append(renderModels());
    } else if (state.activeView === "workspaces") {
      if (state.userStatus === "loading" || state.userStatus === "idle") {
        elements.viewRoot.append(loadingState("Loading workspaces"));
      } else {
        elements.viewRoot.append(renderWorkspaces());
      }
    } else if (state.activeView === "status") {
      elements.viewRoot.append(renderStatus());
    } else if (state.activeView === "live") {
      elements.viewRoot.append(renderLive());
    } else {
      elements.viewRoot.append(renderProfile());
    }
  }

  function renderNotice() {
    clear(elements.noticeRegion);
    if (!state.notice) {
      return;
    }
    const notice = node("div", `notice notice--${state.notice.tone}`);
    notice.append(node("span", "notice__dot"), node("span", "notice__message", state.notice.message));
    elements.noticeRegion.append(notice);
  }

  function renderProfileMenu() {
    clear(elements.profileMenu);
    elements.profileMenu.hidden = !state.profileOpen;
    elements.profileTrigger.setAttribute("aria-expanded", state.profileOpen ? "true" : "false");
    const avatar = elements.profileTrigger.querySelector(".profile-trigger__avatar");
    const username = state.user?.username;
    if (avatar) {
      avatar.textContent = username ? username.slice(0, 1).toUpperCase() : "?";
    }
    if (!state.profileOpen) {
      return;
    }
    const menuHeader = node("div", "profile-menu__header");
    menuHeader.append(node("span", "eyebrow", state.sessionToken ? "SIGNED IN" : "LOCAL ACCESS"));
    if (state.sessionToken && state.user) {
      menuHeader.append(node("strong", "profile-menu__username", safeString(state.user.username, "User")));
    } else {
      menuHeader.append(node("strong", "profile-menu__username", "Not signed in"));
    }
    elements.profileMenu.append(menuHeader);
    if (state.authNotice) {
      elements.profileMenu.append(node("p", "profile-menu__notice", state.authNotice));
    }
    elements.profileMenu.append(node("div", "profile-menu__divider"));
    if (state.sessionToken) {
      const profile = menuButton("View profile", "profile-view");
      const loggingOut = state.busyAction === "logout";
      const logoutButton = menuButton(loggingOut ? "Logging out…" : "Log out", "logout");
      logoutButton.classList.add("menu-item--danger");
      setAttributes(logoutButton, { disabled: loggingOut ? "" : null });
      elements.profileMenu.append(profile, logoutButton);
    } else {
      elements.profileMenu.append(menuButton("Log in", "open-login"), menuButton("Sign up", "open-signup"));
    }
  }

  function menuButton(label, action) {
    const button = node("button", "menu-item", label);
    setAttributes(button, { type: "button", role: "menuitem", "data-action": action });
    return button;
  }

  function renderModal() {
    clear(elements.modalRoot);
    elements.modalRoot.hidden = !state.modal;
    document.body.classList.toggle("modal-open", Boolean(state.modal));
    if (!state.modal) {
      return;
    }
    const backdrop = node("div", "modal-backdrop");
    const panel = node("section", "modal-panel");
    setAttributes(panel, { role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-title" });
    const close = node("button", "modal-close", "Close");
    setAttributes(close, { type: "button", "data-action": "close-modal", "aria-label": "Close dialog" });
    panel.append(close);
    if (state.modal.kind === "secret") {
      renderSecretModal(panel);
    } else {
      renderAuthModal(panel, state.modal.kind);
    }
    backdrop.append(panel);
    elements.modalRoot.append(backdrop);
  }

  function renderAuthModal(panel, kind) {
    const isLogin = kind === "login";
    const title = isLogin ? "Log in" : "Create your account";
    const description = isLogin
      ? "Log in with your username and password."
      : "Choose a username and password to create your local account.";
    panel.append(node("p", "eyebrow", isLogin ? "EXISTING ACCOUNT" : "NEW ACCOUNT"), setAttributes(node("h2", "modal-title", title), { id: "modal-title" }), node("p", "modal-description", description));
    const form = node("form", "modal-form");
    setAttributes(form, { "data-form": isLogin ? "login" : "signup", novalidate: "" });
    const prefix = isLogin ? "login" : "signup";
    form.append(
      formField(`${prefix}-username`, "Username", "e.g. username", "text", true, 64, null, "username"),
      formField(
        `${prefix}-password`,
        "Password",
        "At least 8 characters",
        "password",
        true,
        256,
        8,
        isLogin ? "current-password" : "new-password",
      ),
    );
    const submit = node("button", "button button--primary button--full", state.modal.busy ? "Working…" : isLogin ? "Log in" : "Sign up");
    setAttributes(submit, { type: "submit", disabled: state.modal.busy ? "" : null });
    form.append(submit);
    if (state.modal.error) {
      form.append(formError(state.modal.error));
    }
    panel.append(form);
  }

  function renderSecretModal(panel) {
    panel.append(node("p", "eyebrow", "SAVE THIS KEY"), setAttributes(node("h2", "modal-title", state.modal.title), { id: "modal-title" }), node("p", "modal-description", state.modal.description));
    const warning = node("div", "secret-warning");
    warning.append(node("strong", "secret-warning__title", "Returned only once"), node("p", "secret-warning__copy", "The server will not return this plaintext key again. This browser keeps a local copy so you can copy it again from the workspace."));
    const secret = node("code", "secret-value", state.modal.secret);
    setAttributes(secret, { tabindex: "0", "aria-label": "New inference API key" });
    const copy = actionButton("Copy key", "copy-secret", "button button--primary");
    const actions = node("div", "modal-actions");
    actions.append(copy, actionButton("I saved it", "close-modal", "button button--ghost"));
    panel.append(warning, secret, actions);
  }

  function openAuthModal(kind) {
    state.profileOpen = false;
    state.authNotice = "";
    state.modal = { kind, busy: false, error: null };
    render();
    window.setTimeout(() => {
      document.getElementById(`${kind}-username`)?.focus();
    }, 0);
  }

  function openSecretModal(title, description, secret) {
    state.modal = { kind: "secret", title, description, secret };
    render();
  }

  function closeModal() {
    state.modal = null;
    render();
  }

  async function copySecret(button, plaintext = "") {
    const secret = plaintext || (state.modal?.kind === "secret" ? state.modal.secret : "");
    if (!secret) {
      return;
    }
    const original = button.textContent;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(secret);
      } else {
        const input = node("textarea", "clipboard-fallback", secret);
        setAttributes(input, { readonly: "" });
        document.body.append(input);
        input.select();
        document.execCommand("copy");
        input.remove();
      }
      button.textContent = "Copied";
      window.setTimeout(() => {
        if (button.isConnected) {
          button.textContent = original;
        }
      }, 1800);
    } catch (_error) {
      button.textContent = "Copy failed";
      window.setTimeout(() => {
        if (button.isConnected) {
          button.textContent = original;
        }
      }, 1800);
    }
  }

  async function submitLogin(form) {
    if (!state.modal || state.modal.kind !== "login") {
      return;
    }
    const formData = new FormData(form);
    const username = String(formData.get("login-username") || "").trim();
    const password = String(formData.get("login-password") || "");
    if (!username) {
      state.modal.error = new ApiError("Enter your username to continue.");
      render();
      return;
    }
    if (password.length < 8) {
      state.modal.error = new ApiError("Enter a password with at least 8 characters.");
      render();
      return;
    }
    state.modal.busy = true;
    state.modal.error = null;
    render();
    try {
      const payload = await apiRequest(
        "/v1/account/login",
        { method: "POST", body: JSON.stringify({ username, password }) },
        "",
        false,
      );
      const sessionToken = isObject(payload) && typeof payload.session_token === "string" ? payload.session_token : "";
      if (!sessionToken) {
        throw new ApiError("The server did not return a session token.");
      }
      state.sessionToken = sessionToken;
      storeSession(sessionToken);
      state.authNotice = "";
      state.modal = null;
      state.profileOpen = false;
      state.activeView = "profile";
      applyAccountPayload(payload);
      state.userStatus = "ready";
      render();
    } catch (error) {
      if (state.modal) {
        state.modal.busy = false;
        state.modal.error = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
        render();
      }
    }
  }

  async function submitSignup(form) {
    if (!state.modal || state.modal.kind !== "signup") {
      return;
    }
    const formData = new FormData(form);
    const username = String(formData.get("signup-username") || "").trim();
    const password = String(formData.get("signup-password") || "");
    if (!username) {
      state.modal.error = new ApiError("Enter a username to continue.");
      render();
      return;
    }
    if (password.length < 8) {
      state.modal.error = new ApiError("Enter a password with at least 8 characters.");
      render();
      return;
    }
    state.modal.busy = true;
    state.modal.error = null;
    render();
    try {
      const payload = await apiRequest(
        "/v1/account/signup",
        { method: "POST", body: JSON.stringify({ username, password }) },
        "",
        false,
      );
      const apiKey = isObject(payload) && typeof payload.api_key === "string" ? payload.api_key : "";
      const sessionToken = isObject(payload) && typeof payload.session_token === "string" ? payload.session_token : "";
      if (!apiKey) {
        throw new ApiError("The server did not return an API key.");
      }
      if (!sessionToken) {
        throw new ApiError("The server did not return a session token.");
      }
      state.sessionToken = sessionToken;
      storeSession(sessionToken);
      const workspace = isObject(payload) ? payload.workspace : null;
      state.currentWorkspaceName = typeof workspace === "string"
        ? workspace
        : safeString(isObject(workspace) ? workspace.name : "", "");
      state.activeView = "profile";
      state.profileOpen = false;
      state.userStatus = "idle";
      openSecretModal(
        "Your inference API key",
        "This key is for inference clients (curl, OpenAI SDK). Store it somewhere safe - it is shown once.",
        apiKey,
      );
      cacheCreatedInferenceKey(state.currentWorkspaceName, apiKey, new Set());
      loadAccount();
    } catch (error) {
      if (state.modal) {
        state.modal.busy = false;
        state.modal.error = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
        render();
      }
    }
  }

  async function submitPassword(form) {
    const formData = new FormData(form);
    const currentPassword = String(formData.get("current_password") || "");
    const newPassword = String(formData.get("new_password") || "");
    const confirmPassword = String(formData.get("confirm_password") || "");
    if (currentPassword.length < 8 || newPassword.length < 8 || confirmPassword.length < 8) {
      state.passwordFormError = new ApiError("All password fields must contain at least 8 characters.");
      render();
      return;
    }
    if (newPassword !== confirmPassword) {
      state.passwordFormError = new ApiError("New password and confirmation do not match.");
      render();
      return;
    }
    state.busyAction = "change-password";
    state.passwordFormError = null;
    render();
    try {
      const payload = await apiRequest(
        "/v1/account/password",
        {
          method: "POST",
          body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        },
        undefined,
        false,
      );
      if (!isObject(payload) || payload.changed !== true) {
        throw new ApiError("The server did not confirm the password change.");
      }
      state.busyAction = "";
      state.passwordFormError = null;
      showNotice("Password changed.", "success");
    } catch (error) {
      state.busyAction = "";
      state.passwordFormError = error instanceof ApiError && error.status === 401
        ? new ApiError("current password is incorrect", 401)
        : error instanceof ApiError
          ? error
          : new ApiError("server unreachable", 0, true);
      render();
    }
  }

  async function submitWorkspace(form) {
    const formData = new FormData(form);
    const name = String(formData.get("workspace-name") || "").trim();
    if (!name) {
      state.workspaceFormError = new ApiError("Enter a workspace name to continue.");
      render();
      return;
    }
    state.busyAction = "create-workspace";
    state.workspaceFormError = null;
    render();
    try {
      const payload = await apiRequest("/v1/workspaces", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      showNotice("Workspace created.", "success");
      state.busyAction = "";
      await loadAccount();
      const createdName = isObject(payload) ? safeString(payload.name, name) : name;
      state.selectedWorkspaceName = createdName;
      state.workspaceData = {
        status: "idle",
        keysStatus: "idle",
        keys: null,
        keysError: null,
        usageStatus: "idle",
        usage: null,
        usageError: null,
        requestId: state.workspaceData.requestId + 1,
      };
      render();
      loadWorkspaceData();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      state.busyAction = "";
      state.workspaceFormError = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
      render();
    }
  }

  async function submitKey(form) {
    const workspaceName = state.selectedWorkspaceName;
    if (!workspaceName) {
      return;
    }
    const formData = new FormData(form);
    const label = String(formData.get("key-label") || "").trim();
    const knownKeyIds = listedInferenceKeyIds(state.workspaceData.keys);
    state.busyAction = "create-key";
    state.keyFormError = null;
    render();
    try {
      const payload = await apiRequest(`/v1/workspaces/${encodeURIComponent(workspaceName)}/keys`, {
        method: "POST",
        body: JSON.stringify({ label }),
      });
      const apiKey = isObject(payload) && typeof payload.api_key === "string" ? payload.api_key : "";
      if (!apiKey) {
        throw new ApiError("The server did not return an API key.");
      }
      state.busyAction = "";
      await loadWorkspaceData();
      await cacheCreatedInferenceKey(
        workspaceName,
        apiKey,
        knownKeyIds,
        state.workspaceData.keys,
      );
      openSecretModal(
        "Your new inference API key",
        `This inference key grants access to the ${workspaceName} workspace. Store it somewhere safe - it is shown once.`,
        apiKey,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      state.busyAction = "";
      state.keyFormError = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
      render();
    }
  }

  async function revokeKey(button) {
    const keyId = button.dataset.keyId || "";
    const workspaceName = button.dataset.workspaceName || state.selectedWorkspaceName;
    if (!keyId) {
      return;
    }
    const label = button.closest("tr")?.querySelector(".key-label")?.textContent || "this key";
    if (!window.confirm(`Revoke ${label} from ${workspaceName}? This cannot be undone.`)) {
      return;
    }
    state.busyAction = `revoke-${keyId}`;
    render();
    try {
      await apiRequest(`/v1/keys/${encodeURIComponent(keyId)}`, { method: "DELETE" });
      removeCachedInferenceKey(keyId);
      state.busyAction = "";
      showNotice("Inference API key revoked.", "success");
      await loadWorkspaceData();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      state.busyAction = "";
      state.keyFormError = error instanceof ApiError ? error : new ApiError("server unreachable", 0, true);
      render();
    }
  }

  async function logout() {
    if (!state.sessionToken || state.busyAction === "logout") {
      return;
    }
    const sessionToken = state.sessionToken;
    state.busyAction = "logout";
    render();
    try {
      await apiRequest("/v1/account/logout", { method: "POST" }, sessionToken, false);
    } catch (_error) {
    }
    state.sessionToken = "";
    storeSession("");
    state.userStatus = "idle";
    state.user = null;
    state.userError = null;
    state.workspaces = [];
    state.selectedWorkspaceName = "";
    state.currentWorkspaceName = "";
    resetModelDetail();
    state.workspaceData = {
      status: "idle",
      keysStatus: "idle",
      keys: null,
      keysError: null,
      usageStatus: "idle",
      usage: null,
      usageError: null,
      requestId: state.workspaceData.requestId + 1,
    };
    state.workspaceFormError = null;
    state.keyFormError = null;
    state.passwordFormError = null;
    state.busyAction = "";
    state.authNotice = "";
    state.profileOpen = false;
    state.activeView = "models";
    render();
    showNotice("You are logged out.", "success");
  }

  function switchView(viewName) {
    if (!["models", "workspaces", "status", "live", "profile"].includes(viewName)) {
      return;
    }
    state.activeView = viewName;
    state.profileOpen = false;
    state.notice = null;
    render();
    if (!state.sessionToken) {
      return;
    }
    if (state.userStatus === "idle") {
      loadAccount().then((payload) => {
        if (payload) {
          loadActiveView();
        }
      });
    } else if (state.userStatus === "ready") {
      loadActiveView();
    }
  }

  function loadActiveView() {
    if (!state.sessionToken || state.userStatus !== "ready") {
      return;
    }
    if (state.activeView === "models") {
      if (state.selectedModelName) {
        loadModelDetail();
      } else {
        loadView("models");
      }
    } else if (state.activeView === "workspaces") {
      loadWorkspaceData();
    } else if (state.activeView === "status") {
      loadView("status");
    } else if (state.activeView === "live") {
      loadView("live");
    }
  }

  function retryAccount() {
    state.userStatus = "idle";
    loadAccount().then((payload) => {
      if (payload) {
        loadActiveView();
      }
    });
  }

  function retryView(viewName) {
    if (viewName === "profile" || viewName === "account") {
      retryAccount();
      return;
    }
    const view = state.views[viewName];
    if (!view) {
      return;
    }
    view.status = "idle";
    view.error = null;
    render();
    loadView(viewName);
  }

  function retryWorkspace() {
    state.workspaceData.status = "idle";
    loadWorkspaceData();
  }

  function onClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) {
      return;
    }
    if (state.modal && target.classList.contains("modal-backdrop")) {
      closeModal();
      return;
    }
    const actionElement = target.closest("[data-action]");
    if (actionElement) {
      const action = actionElement.dataset.action;
      if (action === "view") {
        switchView(actionElement.dataset.view || "models");
      } else if (action === "toggle-profile") {
        state.profileOpen = !state.profileOpen;
        render();
      } else if (action === "open-login" || action === "open-signup") {
        openAuthModal(action === "open-login" ? "login" : "signup");
      } else if (action === "profile-view") {
        switchView("profile");
      } else if (action === "logout") {
        logout();
      } else if (action === "close-modal") {
        closeModal();
      } else if (action === "copy-secret") {
        copySecret(actionElement);
      } else if (action === "copy-cached-key") {
        copySecret(actionElement, getCachedInferenceKey(actionElement.dataset.keyId || ""));
      } else if (action === "copy-snippet") {
        const code = actionElement.closest(".request-example")?.querySelector(".request-example__code");
        copySecret(actionElement, code?.textContent || "");
      } else if (action === "select-model") {
        openModelDetail(actionElement.dataset.modelName || "");
      } else if (action === "back-models") {
        resetModelDetail();
        render();
      } else if (action === "retry-model-detail") {
        loadModelDetail();
      } else if (action === "retry-view") {
        retryView(actionElement.dataset.view || state.activeView);
      } else if (action === "retry-account" || action === "retry-profile") {
        retryView("account");
      } else if (action === "retry-workspace") {
        retryWorkspace();
      } else if (action === "select-workspace") {
        const workspaceName = actionElement.dataset.workspaceName || "";
        if (workspaceName && workspaceName !== state.selectedWorkspaceName) {
          state.selectedWorkspaceName = workspaceName;
          state.workspaceData = {
            status: "idle",
            keysStatus: "idle",
            keys: null,
            keysError: null,
            usageStatus: "idle",
            usage: null,
            usageError: null,
            requestId: state.workspaceData.requestId + 1,
          };
          render();
          loadWorkspaceData();
        }
      } else if (action === "revoke-key") {
        revokeKey(actionElement);
      }
      return;
    }
    if (state.profileOpen && !target.closest(".profile-anchor")) {
      state.profileOpen = false;
      render();
    }
  }

  function onSubmit(event) {
    const form = event.target instanceof HTMLFormElement ? event.target : null;
    if (!form) {
      return;
    }
    event.preventDefault();
    const formName = form.dataset.form;
    if (formName === "login") {
      submitLogin(form);
    } else if (formName === "signup") {
      submitSignup(form);
    } else if (formName === "change-password") {
      submitPassword(form);
    } else if (formName === "create-workspace") {
      submitWorkspace(form);
    } else if (formName === "create-key") {
      submitKey(form);
    }
  }

  function onKeyDown(event) {
    if (event.key !== "Escape") {
      return;
    }
    if (state.modal) {
      closeModal();
    } else if (state.profileOpen) {
      state.profileOpen = false;
      render();
    } else if (state.activeView === "models" && state.selectedModelName) {
      resetModelDetail();
      render();
    }
  }

  function renderLive() {
    const view = state.views.live;
    const wrapper = node("div", "view view--live");
    wrapper.append(
      pageHeader(
        "OBSERVABILITY",
        "Live activity",
        "Real-time engine status, in-flight inference, and per-model call counts. Refreshes every 5 seconds while this view is open.",
        retryButton("retry-view", "Refresh"),
      ),
    );

    const hasData = isObject(view.data);
    if (!hasData) {
      if (view.status === "loading" || view.status === "idle") {
        wrapper.append(loadingState("Loading live activity"));
        return wrapper;
      }
      if (view.status === "error") {
        wrapper.append(errorState(view.error, retryButton("retry-view")));
        return wrapper;
      }
    }

    if (view.status === "error" && view.error) {
      const banner = node("div", "live-banner live-banner--error");
      banner.append(
        node("span", "live-banner__dot"),
        node("span", "live-banner__text", "Live refresh failed. Showing the last known values."),
        retryButton("retry-view", "Retry now"),
      );
      wrapper.append(banner);
    }

    const stack = node("div", "live-stack");
    stack.append(
      renderLiveEngineCard(view),
      renderLiveInflightCard(view),
      renderLiveModelsCard(view),
    );
    wrapper.append(stack);
    return wrapper;
  }

  function renderLiveEngineCard(view) {
    const data = isObject(view.data) ? view.data : {};
    const engineData = isObject(data.engine) ? data.engine : {};
    const card = node("section", "card live-card live-card--engine");
    const heading = node("div", "card-heading");
    const headingCopy = node("div");
    headingCopy.append(
      node("p", "eyebrow", "ENGINE"),
      node("h3", "card-title", "Loaded model"),
      node("p", "card-description", "Active engine and the model it currently has in memory."),
    );
    const processBadge = statusBadge(Boolean(engineData.running), "Running", "Stopped");
    setAttributes(processBadge, { "aria-label": engineData.running ? "Engine is running" : "Engine is stopped" });
    heading.append(headingCopy, processBadge);
    card.append(heading);

    const list = node("dl", "status-list");
    const fields = [
      ["Engine", safeString(engineData.engine, "—")],
      ["Model", safeString(engineData.model, "no model loaded")],
      ["Port", safeString(engineData.port, "—")],
      ["Loaded at", formatDate(engineData.loaded_at)],
      ["Uptime", humanizeUptime(engineData.uptime_seconds)],
    ];
    fields.forEach(([label, value]) => {
      list.append(node("dt", "status-list__term", label));
      list.append(node("dd", "status-list__value", value));
    });
    card.append(list);
    return card;
  }

  function renderLiveInflightCard(view) {
    const data = isObject(view.data) ? view.data : {};
    const inflight = isObject(data.inflight) ? data.inflight : { count: 0, requests: [] };
    const count = Number(inflight.count) || 0;
    const requests = Array.isArray(inflight.requests) ? inflight.requests : [];

    const card = node("section", "card live-card live-card--inflight");
    const heading = node("div", "card-heading");
    const headingCopy = node("div");
    headingCopy.append(
      node("p", "eyebrow", "TRAFFIC"),
      node("h3", "card-title", "In-flight requests"),
      node("p", "card-description", "Active inference calls currently being processed right now."),
    );
    const badge = node("span", count > 0 ? "status-badge status-badge--accent" : "count-badge");
    setAttributes(badge, {
      "aria-label": `${count} ${count === 1 ? "request" : "requests"} in flight`,
    });
    badge.append(node("span", "", String(count)));
    heading.append(headingCopy, badge);
    card.append(heading);

    if (!requests.length) {
      card.append(
        emptyState(
          "No requests in flight",
          "Inference is idle right now. New calls will appear here as they arrive.",
        ),
      );
      return card;
    }

    const wrap = node("div", "table-wrap");
    const table = node("table", "data-table data-table--live-inflight");
    setAttributes(table, { "aria-label": "In-flight inference requests" });
    table.append(node("caption", "sr-only", "In-flight inference requests"));
    const head = node("thead");
    const headRow = node("tr");
    ["User", "Workspace", "Model", "Endpoint", "Elapsed"].forEach((label) => headRow.append(node("th", "", label)));
    head.append(headRow);
    const body = node("tbody");
    requests.forEach((req) => {
      const elapsed = Number(req?.elapsed_seconds);
      const elapsedText = Number.isFinite(elapsed) ? `${elapsed.toFixed(1)}s` : "—";
      const row = node("tr");
      row.append(
        node("td", "model-name", safeString(req?.user, "—")),
        node("td", "", safeString(req?.workspace, "—")),
        node("td", "model-name", safeString(req?.model, "—")),
        node("td", "", safeString(req?.endpoint, "—")),
        node("td", "numeric-cell", elapsedText),
      );
      body.append(row);
    });
    table.append(head, body);
    wrap.append(table);
    card.append(wrap);
    return card;
  }

  function renderLiveModelsCard(view) {
    const data = isObject(view.data) ? view.data : {};
    const models = Array.isArray(data.models) ? data.models : [];

    const card = node("section", "card live-card live-card--models");
    const heading = node("div", "card-heading");
    const headingCopy = node("div");
    headingCopy.append(
      node("p", "eyebrow", "CALL TOTALS"),
      node("h3", "card-title", "Model calls"),
      node("p", "card-description", "Cumulative inference calls and tokens recorded for each model."),
    );
    heading.append(headingCopy);
    card.append(heading);

    if (!models.length) {
      card.append(node("p", "muted-copy live-empty", "No inference calls recorded yet."));
      return card;
    }

    const wrap = node("div", "table-wrap table-wrap--usage");
    const table = node("table", "data-table");
    setAttributes(table, { "aria-label": "Model call totals" });
    table.append(node("caption", "sr-only", "Model call totals"));
    const head = node("thead");
    const headRow = node("tr");
    ["Model", "Requests", "Total tokens"].forEach((label) => headRow.append(node("th", "", label)));
    head.append(headRow);
    const body = node("tbody");
    models.forEach((entry) => {
      const row = node("tr");
      row.append(
        node("td", "model-name", safeString(entry?.model, "—")),
        node("td", "numeric-cell", formatNumber(entry?.requests)),
        node("td", "numeric-cell", formatNumber(entry?.total_tokens)),
      );
      body.append(row);
    });
    table.append(head, body);
    wrap.append(table);
    card.append(wrap);
    return card;
  }

  function humanizeUptime(seconds) {
    if (seconds === null || seconds === undefined) {
      return "—";
    }
    const total = Number(seconds);
    if (!Number.isFinite(total) || total < 0) {
      return "—";
    }
    const totalSecs = Math.floor(total);
    if (totalSecs < 60) {
      return `${totalSecs}s`;
    }
    if (totalSecs < 3600) {
      const minutes = Math.floor(totalSecs / 60);
      const secs = totalSecs % 60;
      return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
    }
    if (totalSecs < 86400) {
      const hours = Math.floor(totalSecs / 3600);
      const minutes = Math.floor((totalSecs % 3600) / 60);
      return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }
    const days = Math.floor(totalSecs / 86400);
    const hours = Math.floor((totalSecs % 86400) / 3600);
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }

  function updateLivePolling() {
    if (state.liveTimer) {
      window.clearInterval(state.liveTimer);
      state.liveTimer = 0;
    }
    const shouldRun = state.activeView === "live"
      && Boolean(state.sessionToken)
      && typeof document !== "undefined"
      && !document.hidden;
    if (shouldRun) {
      state.liveTimer = window.setInterval(() => {
        if (state.activeView === "live" && state.sessionToken && !document.hidden) {
          loadView("live");
        } else {
          updateLivePolling();
        }
      }, 5000);
    }
  }

  function onVisibilityChange() {
    if (document.hidden) {
      updateLivePolling();
      return;
    }
    updateLivePolling();
    if (state.activeView === "live" && state.sessionToken) {
      loadView("live");
    }
  }

  function initialize() {
    document.addEventListener("click", onClick);
    document.addEventListener("submit", onSubmit);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("visibilitychange", onVisibilityChange);
    render();
    if (migratedLegacyKey) {
      showNotice(SIGN_IN_MIGRATION_NOTICE);
    }
    if (state.sessionToken) {
      loadAccount().then((payload) => {
        if (payload) {
          loadActiveView();
        }
      });
    }
  }

  initialize();
})();
