import { createAccountAssignmentsController } from "./account-assignments-controller.js";
import { createAccountAuthController } from "./account-auth-controller.js";
import { createAccountGroupsController } from "./account-groups-controller.js";
import { createAccountReviewsController } from "./account-reviews-controller.js";
import { createAccountReviewRequestsController } from "./account-review-requests-controller.js";
import { createAccountSecurityController } from "./account-security-controller.js";

export function createAccountController(ctx) {
  let assignments;
  let groups;
  let reviews;
  let reviewRequests;
  let security;

  const refreshAccountData = async () => {
    if (!auth.user) return;
    if (auth.user.role === "teacher") {
      await Promise.all([groups.loadTeacherDashboard(), reviews.loadTeacherSubmissions(), assignments.loadTeacherAssignments()]);
    } else {
      await Promise.all([groups.loadStudentGroups(), assignments.loadStudentAssignments(), reviewRequests.loadStudentReviewRequests()]);
    }
  };

  const resetAccountViews = () => {
    groups?.reset();
    assignments?.reset();
    reviews?.reset();
    reviewRequests?.reset();
  };

  const auth = createAccountAuthController({
    ...ctx,
    refreshAccountData,
    resetAccountViews,
    isPasswordResetting: () => security?.isPasswordResetting() || false,
  });

  groups = createAccountGroupsController({
    toast: ctx.toast,
    getUser: () => auth.user,
    loadStudentAssignments: () => assignments.loadStudentAssignments(),
    onTeacherGroupsChanged: () => assignments.renderAssignmentOptions(),
  });
  assignments = createAccountAssignmentsController({
    ...ctx,
    getUser: () => auth.user,
    getTeacherGroups: groups.getTeacherGroups,
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
    loadStudentGroups: groups.loadStudentGroups,
    joinGroup: groups.joinGroup,
    loadTeacherDashboard: groups.loadTeacherDashboard,
    createGroup: groups.createGroup,
    loadStudentAssignments: assignments.loadStudentAssignments,
    loadStudentReviewRequests: reviewRequests.loadStudentReviewRequests,
    submitReviewRequest: reviewRequests.submitReviewRequest,
    clearPendingReviewRequest: reviewRequests.clearPendingReviewRequest,
    startAssignedRun: assignments.startAssignedRun,
    renderAssignmentOptions: assignments.renderAssignmentOptions,
    createAssignment: assignments.createAssignment,
    loadTeacherAssignments: assignments.loadTeacherAssignments,
    handleAssignmentAction: assignments.handleAssignmentAction,
    loadTeacherSubmissions: reviews.loadTeacherSubmissions,
    showAttemptHistory: reviews.showAttemptHistory,
    submitReview: reviews.submitReview,
    requestPasswordReset: security.requestPasswordReset,
    submitPasswordReset: security.submitPasswordReset,
    cancelPasswordReset: security.cancelPasswordReset,
    sendVerificationEmail: security.sendVerificationEmail,
    loadAuditLog: security.loadAuditLog,
    deleteAccount: security.deleteAccount,
    handleAccountLinks: security.handleAccountLinks,
  };
}
