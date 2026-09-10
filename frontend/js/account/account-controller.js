import { createAccountAuthController } from "./account-auth-controller.js";
import { createAccountReviewRequestsController } from "./account-review-requests-controller.js";
import { createAccountSecurityController } from "./account-security-controller.js";
import { createAccountPersonalRecordingsController } from "./account-personal-recordings-controller.js";

export function createAccountController(ctx) {
  let reviewRequests;
  let security;
  let personalRecordings;

  const resetAccountViews = () => {
    reviewRequests?.reset();
    personalRecordings?.reset();
  };

  const auth = createAccountAuthController({
    ...ctx,
    resetAccountViews,
    isPasswordResetting: () => security?.isPasswordResetting() || false,
  });

  reviewRequests = createAccountReviewRequestsController({ ...ctx, getUser: () => auth.user });
  personalRecordings = createAccountPersonalRecordingsController({ ...ctx, getUser: () => auth.user });
  security = createAccountSecurityController({ ...ctx, auth });

  return {
    get user() { return auth.user; },
    get progressHydrated() { return auth.progressHydrated; },
    initAuth: auth.initAuth,
    renderAuth: auth.renderAuth,
    setAuthMode: auth.setAuthMode,
    openModal: auth.openModal,
    closeModal: auth.closeModal,
    submitAuth: auth.submitAuth,
    logout: auth.logout,
    scheduleProgressSync: auth.scheduleProgressSync,
    pushProgress: auth.pushProgress,
    syncProgress: auth.syncProgress,
    submitReviewRequest: reviewRequests.submitReviewRequest,
    clearPendingReviewRequest: reviewRequests.clearPendingReviewRequest,
    archiveCompletedRun: personalRecordings.archiveCompletedRun,
    retryArchive: personalRecordings.retryArchive,
    requestPasswordReset: security.requestPasswordReset,
    submitPasswordReset: security.submitPasswordReset,
    cancelPasswordReset: security.cancelPasswordReset,
    sendVerificationEmail: security.sendVerificationEmail,
    handleAccountLinks: security.handleAccountLinks,
  };
}
