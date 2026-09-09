import { api, discardReviewRequest } from "../shared/api.js";
import {
  defaultProgress,
  loadLocalProgress,
  mergeProgress,
  progressStorageKeys,
} from "../shared/progress.js";

const emptyErrors = () => ({ auth: null, progress: null, recordings: null, reviews: null });
const messageOf = error => error?.message || "Не удалось загрузить данные";

function publicState(state) {
  return {
    ...state,
    recordings: [...state.recordings],
    reviewRequests: [...state.reviewRequests],
    sourceErrors: { ...state.sourceErrors },
  };
}

export function createHistoryPageController({
  request = api,
  discard = discardReviewRequest,
  storage = globalThis.localStorage,
  render,
}) {
  let generation = 0;
  let state = {
    mode: "guest",
    user: null,
    progress: defaultProgress(),
    recordings: [],
    reviewRequests: [],
    sourceErrors: emptyErrors(),
  };

  const publish = () => render(publicState(state));
  const current = (token, userId = null) => (
    token === generation && (userId === null || state.user?.id === userId)
  );

  function localProgress(userId, sourceErrors) {
    return loadLocalProgress(progressStorageKeys(userId), {
      storage,
      onError: message => { sourceErrors.progress = message; },
    });
  }

  function showGuest({ authError = null } = {}) {
    const sourceErrors = emptyErrors();
    sourceErrors.auth = authError;
    state = {
      mode: "guest",
      user: null,
      progress: localProgress(null, sourceErrors),
      recordings: [],
      reviewRequests: [],
      sourceErrors,
    };
    publish();
  }

  function expireToGuest(error) {
    generation += 1;
    showGuest({ authError: messageOf(error) });
  }

  async function synchronizeProgress(token, user) {
    let remote;
    try {
      remote = await request("/api/progress");
    } catch (error) {
      if (!current(token, user.id)) return false;
      if (error.status === 401) {
        expireToGuest(error);
        return false;
      }
      state.sourceErrors.progress = messageOf(error);
      publish();
      return true;
    }
    if (!current(token, user.id)) return false;
    const merged = mergeProgress(state.progress, remote.progress);
    state.progress = merged;
    storage.setItem(progressStorageKeys(user.id).current, JSON.stringify(merged));
    try {
      await request("/api/progress", {
        method: "PUT",
        body: JSON.stringify({ progress: merged }),
      });
      if (!current(token, user.id)) return false;
      state.sourceErrors.progress = null;
    } catch (error) {
      if (!current(token, user.id)) return false;
      if (error.status === 401) {
        expireToGuest(error);
        return false;
      }
      state.sourceErrors.progress = messageOf(error);
    }
    if (current(token, user.id)) publish();
    return current(token, user.id);
  }

  async function loadStudentSource(source, token, user) {
    const paths = {
      recordings: "/api/personal-recordings",
      reviews: "/api/student/review-requests",
    };
    try {
      const payload = await request(paths[source]);
      if (!current(token, user.id)) return;
      if (source === "recordings") state.recordings = payload.recordings || [];
      else state.reviewRequests = payload.requests || [];
      state.sourceErrors[source] = null;
      publish();
    } catch (error) {
      if (!current(token, user.id)) return;
      if (error.status === 401) {
        expireToGuest(error);
        return;
      }
      state.sourceErrors[source] = messageOf(error);
      publish();
    }
  }

  async function load() {
    const token = ++generation;
    let user;
    try {
      user = (await request("/api/auth/me")).user;
    } catch (error) {
      if (!current(token)) return;
      showGuest({ authError: error.status === 401 ? null : messageOf(error) });
      return;
    }
    if (!current(token)) return;
    if (user.role === "teacher") {
      state = {
        mode: "teacher",
        user,
        progress: defaultProgress(),
        recordings: [],
        reviewRequests: [],
        sourceErrors: emptyErrors(),
      };
      publish();
      return;
    }

    const sourceErrors = emptyErrors();
    state = {
      mode: "student",
      user,
      progress: localProgress(user.id, sourceErrors),
      recordings: [],
      reviewRequests: [],
      sourceErrors,
    };
    publish();
    if (!await synchronizeProgress(token, user)) return;
    await Promise.all([
      loadStudentSource("recordings", token, user),
      loadStudentSource("reviews", token, user),
    ]);
  }

  async function retry(source) {
    const token = generation;
    const user = state.user;
    if (state.mode !== "student" || !user) return;
    if (source === "progress") await synchronizeProgress(token, user);
    if (source === "recordings" || source === "reviews") await loadStudentSource(source, token, user);
  }

  async function discardUploadingReviewRequest(requestId) {
    if (!Number.isInteger(requestId) || requestId <= 0 || state.mode !== "student") return false;
    try {
      await discard(requestId);
    } catch (error) {
      if (error.status === 401) expireToGuest(error);
      else {
        state.sourceErrors.reviews = messageOf(error);
        publish();
      }
      return false;
    }
    await retry("reviews");
    return true;
  }

  return {
    load,
    retry,
    discardReviewRequest: discardUploadingReviewRequest,
  };
}
