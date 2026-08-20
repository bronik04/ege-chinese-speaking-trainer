import { createAccountAuthController } from "./account-auth-controller.js";
import { createAccountReviewsController } from "./account-reviews-controller.js";
import { createAccountReviewRequestsController } from "./account-review-requests-controller.js";
import { createAccountSecurityController } from "./account-security-controller.js";

export function createAccountController(ctx) {
  let reviews;
  let reviewRequests;
  let security;

  const refreshAccountData = async () => {
    if (!auth.user) return;
    if (auth.user.role === "teacher") {
      await reviews.loadTeacherReviewRequests();
    } else {
      await reviewRequests.loadStudentReviewRequests();
    }
  };

  const resetAccountViews = () => {
    reviews?.reset();
    reviewRequests?.reset();
  };

  const auth = createAccountAuthController({
    ...ctx,
    refreshAccountData,
    resetAccountViews,
    isPasswordResetting: () => security?.isPasswordResetting() || false,
  });

  reviews = createAccountReviewsController({ toast: ctx.toast, getUser: () => auth.user });
  reviewRequests = createAccountReviewRequestsController({ ...ctx, getUser: () => auth.user });
  security = createAccountSecurityController({ ...ctx, auth });

  return {
    get user() { return auth.user; },
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
    refreshAccountData,
    loadStudentReviewRequests: reviewRequests.loadStudentReviewRequests,
    submitReviewRequest: reviewRequests.submitReviewRequest,
    discardUploadingReviewRequest: reviewRequests.discardUploadingReviewRequest,
    clearPendingReviewRequest: reviewRequests.clearPendingReviewRequest,
    loadTeacherReviewRequests: reviews.loadTeacherReviewRequests,
    showStudentReviewHistory: reviews.showStudentReviewHistory,
    saveReviewScores: reviews.saveReviewScores,
    requestPasswordReset: security.requestPasswordReset,
    submitPasswordReset: security.submitPasswordReset,
    cancelPasswordReset: security.cancelPasswordReset,
    sendVerificationEmail: security.sendVerificationEmail,
    loadAuditLog: security.loadAuditLog,
    deleteAccount: security.deleteAccount,
    handleAccountLinks: security.handleAccountLinks,
  };
}
